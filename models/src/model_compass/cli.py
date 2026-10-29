"""``dgc``: the Model Compass command line.

    dgc corpus check                       is the corpus loadable and consistent?
    dgc plan -e SPEC [-e SPEC ...]         cells x draws, priced; spends nothing
    dgc run -e SPEC --dry-run | --yes      execute draws locally under the budget cap
    dgc adopt -e SPEC --from RUN ...       seed draws from earlier runs' executions
    dgc score -r RUN                       artifacts -> metrics/<cell_id>.jsonl
    dgc aggregate -r RUN                   metrics -> grid/compass_grid.csv + validity.json
    dgc compare RUN_A RUN_B                paired comparison, Markdown + CSV
    dgc report -r RUN                      report/report.md + CSV tables
    dgc sweep [--spec NAME] [--yes]        the configured sweeps, each run, scored, aggregated,
                                           reported and exported; plans and stops without --yes
    dgc reference report|export|match      the reference results in results/reference/
    dgc figure                             figures/quality_cost.svg from the reference results

Every command takes ``--dry-run``: compute and print, spend nothing, write nothing -- except
``run --dry-run``, which writes the full run directory with estimates.
Exit codes: 0 ok, 1 error, 2 findings (incomparable rows, regressions, corpus errors,
nothing scored), 3 budget exceeded.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from model_compass.config import MODELS_DIR, REPO_ROOT, Settings, load_dotenv, load_settings
from model_compass.errors import CompassError, ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from model_compass.corpus.models import Corpus


def _out(*lines: str) -> None:
    for line in lines:
        print(line)


def _run_dir(value: str, settings: Settings) -> Path:
    """A run directory, or a run id under ``runs_dir``."""
    path = Path(value).expanduser()
    return path.resolve() if path.is_dir() else settings.runs_dir / value


def _run_corpus(run_dir: Path, settings: Settings) -> Corpus:
    from model_compass.corpus.loader import load_corpus
    from model_compass.corpus.selector import CorpusSelector
    from model_compass.runs import load_manifest

    selector = CorpusSelector.model_validate(load_manifest(run_dir).spec.corpus)
    return load_corpus(settings.require("corpus_root"), selector)[0]


# -- commands ----------------------------------------------------------------------------------


def cmd_corpus_check(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.corpus.loader import load_corpus
    from model_compass.corpus.selector import CorpusSelector

    selector = CorpusSelector.model_validate(
        {"docsets": {"all_with_refs": True}, "max_files_per_docset": 1000}
    )
    corpus, report = load_corpus(
        settings.require("corpus_root"), selector, check_text_layer=args.text_layer
    )
    labels = corpus.labels
    summed = sum(len(d.labels) for d in corpus.docsets)
    _out(
        f"{len(corpus.docsets)} docsets with gold, {len(corpus.documents)} documents",
        f"labels    {len(labels)} distinct ({summed} summed per docset)",  # DECISIONS 0005
    )
    for finding in report.findings:
        _out(f"  {finding.severity.value:5} {finding.code}: {finding.message}")
    return ExitCode.OK if report.ok else ExitCode.FINDINGS


def cmd_plan(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.corpus.loader import load_corpus
    from model_compass.experiments.plan import plan
    from model_compass.experiments.spec import load_spec

    total, plans = 0.0, []
    for path in args.spec:
        spec = load_spec(path)
        corpus, _ = load_corpus(settings.require("corpus_root"), spec.corpus)
        built = plan(spec, settings, corpus, budget_usd=args.budget_usd, dry_run=True)
        plans.append(built)
        total += built.estimated_usd
        if not args.json:
            _out(built.render())
    if args.json:
        payload = [json.loads(p.to_json()) for p in plans]
        _out(json.dumps(payload[0] if len(payload) == 1 else payload, indent=2))
    elif len(plans) > 1:
        _out(f"total estimate over {len(plans)} specs: ${total:,.2f}")
    return ExitCode.OK if all(p.within_budget for p in plans) else ExitCode.BUDGET_EXCEEDED


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.experiments.manifest import RunOutcome
    from model_compass.experiments.run import run
    from model_compass.experiments.spec import load_spec

    manifest = run(
        load_spec(args.spec),
        settings,
        dry_run=args.dry_run,
        resume_run_id=args.resume,
        retry_empty=args.retry_empty,
        yes=args.yes,
        budget_usd=args.budget_usd,
        allow_dirty_corpus=args.allow_dirty_corpus,
    )
    _out(
        f"run {manifest.run_id}: {manifest.outcome.value}",
        f"estimated ${manifest.costs.estimated_usd:,.2f}, actual ${manifest.costs.actual_usd:,.2f}",
        f"wrote {settings.runs_dir / manifest.run_id}",
    )
    if manifest.outcome is RunOutcome.BUDGET_ABORTED:
        return ExitCode.BUDGET_EXCEEDED
    ok = (RunOutcome.SUCCEEDED, RunOutcome.DRY_RUN)
    return ExitCode.OK if manifest.outcome in ok else ExitCode.ERROR


def cmd_adopt(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.experiments.adopt import adopt
    from model_compass.experiments.spec import load_spec

    result = adopt(
        load_spec(args.spec),
        settings,
        args.sources,
        exclude_models=args.exclude_model,
        into=args.into,
        allow_partial=args.allow_partial,
        dry_run=args.dry_run,
    )
    for cell in result.cells:
        _out(f"{cell.action:12} {cell.cell_id} {cell.ref} {cell.reason}".rstrip())
    _out(f"{len(result.adopted)} of {len(result.cells)} cells adopted into {result.run_id}")
    return ExitCode.OK


def cmd_score(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.scoring import score_run

    run_dir = _run_dir(args.run, settings)
    result = score_run(
        run_dir,
        corpus=_run_corpus(run_dir, settings),
        families=args.metric,
        work_dir=settings.work_dir,
        workers=args.workers or max(1, min(settings.max_parallel_cells, os.cpu_count() or 1)),
        resume=args.resume,
        dry_run=args.dry_run,
    )
    for cell in result.cells:
        state = "kept" if cell.kept else "scored" if cell.scored else "skipped"
        draws = f" {cell.draws_scored}/{cell.draws} draws" if cell.draws > 1 else ""
        _out(f"{state:8} {cell.cell_id} {cell.records} records{draws} {cell.reason or ''}".rstrip())
        _out(*(f"    {w}" for w in cell.warnings))
    families = ", ".join(f.value for f in result.families)
    _out(f"{len(result.scored)} of {len(result.cells)} cells scored; families: {families}")
    return ExitCode.OK if result.scored else ExitCode.FINDINGS


def cmd_aggregate(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.aggregate.grid import aggregate_run

    result = aggregate_run(
        _run_dir(args.run, settings),
        min_docsets=args.min_docsets,
        quality_metric=args.quality_metric,
        dry_run=args.dry_run,
    )
    _out(*result.summary())
    if args.pivot:
        from model_compass.aggregate.render import pivot

        _out(*(",".join(row) for row in pivot(result.grid, args.pivot)))
    return ExitCode.FINDINGS if result.n_incomparable else ExitCode.OK


def cmd_compare(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.aggregate.compare import compare_runs

    table = compare_runs(
        _run_dir(args.baseline, settings),
        _run_dir(args.candidate, settings),
        min_docsets=args.min_docsets,
        out_dir=args.out,
        dry_run=args.dry_run,
    )
    _out(
        f"{len(table.deltas)} compared rows, {table.n_regressed} regressed, "
        f"{table.n_incomparable} not comparable",
        *table.warnings,
        *(f"wrote {path}" for path in table.written),
    )
    return ExitCode.FINDINGS if table.n_regressed or table.n_incomparable else ExitCode.OK


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.report import write_report

    report = write_report(_run_dir(args.run, settings), dry_run=args.dry_run)
    _out(report.summary, *(f"wrote {path}" for path in report.written))
    if args.dry_run:
        _out(report.markdown)
    return ExitCode.FINDINGS if report.partial else ExitCode.OK


def cmd_sweep(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.reference import SWEEPS, sweep

    given = (
        ("--profile", args.profile),
        ("--env-file", args.env_file),
        ("--runs-dir", args.runs_dir),
        ("--corpus-root", args.corpus_root),
        ("--work-dir", args.work_dir),
    )
    flags = [f for name, value in given if value is not None for f in (name, str(value))]
    flags += ["-v"] if args.verbose else []
    run_flags = ["--allow-dirty-corpus"] if args.allow_dirty_corpus else []
    return sweep(args.spec or list(SWEEPS), args.out, flags, args.yes, args.dry_run, run_flags)


def cmd_reference_report(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.reference import report

    _out(report(args.reference, write=not args.dry_run))
    return ExitCode.OK


def cmd_reference_export(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.reference import export

    run_dir = _run_dir(args.run, settings)
    if args.dry_run:
        _out(f"would export {run_dir} into {args.out}")
        return ExitCode.OK
    _out(f"wrote {export(run_dir, args.out, args.spec)}")
    return ExitCode.OK


def cmd_reference_match(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.match_reference import match

    args.run_dir = _run_dir(args.run, settings)
    return match(args)


def cmd_figure(args: argparse.Namespace, settings: Settings) -> int:
    from model_compass.figure import points, render, write

    if args.dry_run:
        _out(render(points()))
        return ExitCode.OK
    _out(f"wrote {write(args.out)}")
    return ExitCode.OK


# -- parser ------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    from model_compass.aggregate.render import PIVOT_AXES

    parser = argparse.ArgumentParser(prog="dgc", description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", type=Path, help="settings profile YAML, e.g. local.yaml")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="KEY=value file loaded into the environment (default: .env here, then in models/)",
    )
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, handler: Callable, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--dry-run", action="store_true", help="write nothing, spend nothing")
        p.set_defaults(handler=handler)
        return p

    corpus = sub.add_parser("corpus", help="the reference corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)
    check = corpus_sub.add_parser("check", help="load the corpus and report findings")
    check.add_argument("--dry-run", action="store_true", help="(reads only; accepted)")
    check.add_argument("--text-layer", action="store_true", help="also flag scanned PDFs")
    check.set_defaults(handler=cmd_corpus_check)

    p = command("plan", cmd_plan, "price a spec; reads only, so --dry-run changes nothing")
    p.add_argument("-e", "--spec", type=Path, action="append", required=True)
    p.add_argument("--budget-usd", type=float, help="cap (default: the spec's, else settings)")
    p.add_argument("--json", action="store_true", help="print the plan as JSON")

    p = command("run", cmd_run, "execute a spec's draws locally")
    p.add_argument("-e", "--spec", type=Path, required=True)
    p.add_argument("--resume", metavar="RUN_ID", help="continue a run: execute only missing draws")
    p.add_argument("--retry-empty", action="store_true", help="re-run draws that made no DGML")
    p.add_argument("--budget-usd", type=float, help="cap (default: the spec's, else settings)")
    p.add_argument("--yes", action="store_true", help="confirm a paid run")
    p.add_argument(
        "--allow-dirty-corpus", action="store_true", help="run on a corpus with uncommitted changes"
    )

    p = command("adopt", cmd_adopt, "seed draws from earlier runs' executions (DECISIONS 0018)")
    p.add_argument("-e", "--spec", type=Path, required=True)
    p.add_argument("--from", dest="sources", action="append", required=True, metavar="RUN")
    p.add_argument("--exclude-model", action="append", default=[])
    p.add_argument("--into", metavar="RUN_ID")
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="also adopt executions where some documents produced no DGML",
    )

    p = command("score", cmd_score, "score a run's artifacts")
    p.add_argument("-r", "--run", required=True)
    p.add_argument("--metric", action="append", help="family to score; repeatable")
    p.add_argument("--workers", type=int, help="default: max_parallel_cells, capped at CPUs")
    p.add_argument(
        "--resume", action="store_true", help="skip cells already scored for every draw and family"
    )

    p = command("aggregate", cmd_aggregate, "metric records -> compass_grid.csv")
    p.add_argument("-r", "--run", required=True)
    p.add_argument("--min-docsets", type=int, default=3)
    p.add_argument("--quality-metric", default="individual_overlap_f1")
    p.add_argument("--pivot", choices=PIVOT_AXES, help="also print the pivot on this axis")

    p = command("compare", cmd_compare, "compare two runs arm by arm")
    p.add_argument("baseline")
    p.add_argument("candidate")
    p.add_argument("--min-docsets", type=int, default=3)
    p.add_argument("-o", "--out", type=Path)

    p = command("report", cmd_report, "report.md and CSV tables for a run")
    p.add_argument("-r", "--run", required=True)

    p = command("sweep", cmd_sweep, "the configured sweeps end to end (paid with --yes)")
    p.add_argument("--spec", action="append", metavar="NAME", help="specs/NAME.yaml; repeatable")
    p.add_argument("--out", type=Path, default=Path("results/latest"), help="the results set")
    p.add_argument("--yes", action="store_true", help="spend: without it, plan and stop")
    p.add_argument("--allow-dirty-corpus", action="store_true", help="passed to dgc run")

    reference = MODELS_DIR / "results" / "reference"
    ref = sub.add_parser("reference", help="the reference results (results/reference/)")
    ref_sub = ref.add_subparsers(dest="reference_command", required=True)

    def ref_command(name: str, handler: Callable, help_: str) -> argparse.ArgumentParser:
        p = ref_sub.add_parser(name, help=help_)
        p.add_argument("--dry-run", action="store_true", help="write nothing")
        p.set_defaults(handler=handler)
        return p

    p = ref_command("report", cmd_reference_report, "rebuild the README.md over a results set")
    p.add_argument("--reference", type=Path, default=reference)
    p = ref_command("export", cmd_reference_export, "copy a scored run's tables into <out>/<spec>/")
    p.add_argument("run", help="run id or directory")
    p.add_argument("--out", type=Path, required=True, help="results set, e.g. results/reference")
    p.add_argument("--spec", help="directory name (default: the spec name in the manifest)")
    p = ref_command("match", cmd_reference_match, "how closely a scored run matches the reference")
    p.add_argument("run", help="run id or directory, scored (dgc score -r ...)")
    p.add_argument("--reference", type=Path, default=reference)
    p.add_argument("--spec", help="compare against this reference spec only")
    p.add_argument("--tolerance", type=float, default=5.0, help="quality points (0-100)")
    p.add_argument("--token-ratio", type=float, default=2.0)
    p.add_argument("-o", "--out", type=Path, help="also write the report here (.md)")
    p.add_argument("--json", type=Path, help="also write the pairs as JSON here")

    p = command("figure", cmd_figure, "draw figures/quality_cost.svg from results/reference/")
    p.add_argument("--out", type=Path, default=MODELS_DIR / "figures" / "quality_cost.svg")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    env_files = [args.env_file] if args.env_file else [Path.cwd() / ".env", MODELS_DIR / ".env"]
    for env_file in dict.fromkeys(env_files):
        if loaded := load_dotenv(env_file):
            logging.info("loaded %s from %s", ", ".join(loaded), env_file)
    stale = REPO_ROOT / ".env"  # where .env lived before models/ became its own project
    if not args.env_file and stale.is_file() and stale.resolve() != (Path.cwd() / ".env").resolve():
        logging.warning("%s is not read any more: move it to %s", stale, MODELS_DIR / ".env")
    try:
        settings = load_settings(
            profile=args.profile,
            runs_dir=args.runs_dir,
            corpus_root=args.corpus_root,
            work_dir=args.work_dir,
        )
        return int(args.handler(args, settings))
    except CompassError as exc:
        print(json.dumps(exc.as_dict(), default=str), file=sys.stderr)
        return int(exc.exit_code)


if __name__ == "__main__":
    sys.exit(main())
