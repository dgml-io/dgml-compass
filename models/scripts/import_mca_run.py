#!/usr/bin/env python3
"""Import a run of the earlier implementation as a dgml-compass run, scoped to the bundled corpus.

The earlier implementation wrote the same run layout this package reads (``runs.py``), so
importing is filtering and relabelling, never re-scoring or re-generating:

- cells whose docset is not in ``shapes.yaml`` of the target corpus are dropped (EmailBody,
  the private docsets);
- an org is renamed where the corpus moved a docset (R1: Cruise Itineraries moved from its
  original org to ``z4ervk9ic0oo``) -- in ``cells.json``, ``result.json`` and the sidecar.
  The ``cell_id`` string is kept, so metrics stay joinable to the source run;
- the spec's corpus selection becomes the explicit include list of the kept docsets, and
  ``metrics`` becomes all four families;
- ``cells/<cell>/.../{result.json, workspace/mca-workspace.json, dgml/}`` are copied; logs
  are not;
- the dgml workspaces stay where they are: ``<work_dir>/<run_id>`` is symlinked to the source
  scratch directory and each ``result.json`` records its workspace under ``work_dir``, so
  ``locate_workspace`` finds them on either side of the move (pass the same ``--work-dir`` to
  ``dgc``).

``import.json`` in the new run records all of it. Nothing in the source is touched.

    python scripts/import_mca_run.py <source_run_dir> --runs-dir <runs_dir> \
        --work-dir <work_dir> --source-work <source scratch dir> \
        [--corpus-root data/corpus] [--org-map OLD=NEW] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ALL_FAMILIES = ["extraction", "reference_free", "economics", "tree"]


def _allowed_docsets(corpus_root: Path) -> dict[str, str]:
    """docset_id -> org for every docset the shape map lists."""
    shapes = yaml.safe_load((corpus_root.parent / "shapes.yaml").read_text(encoding="utf-8"))
    return {d["docset_id"]: d["org"] for d in shapes["docsets"]}


def _map_org(org: str, org_map: dict[str, str]) -> str:
    return org_map.get(org, org)


def _reroot_workspace(recorded: str, work_dir: Path, source_work: Path) -> str:
    """The workspace as it will be reachable through ``<work_dir>/<run_id>`` (a symlink to the
    source scratch directory). Draws adopted from another run keep that run's id in the tail,
    exactly as ``locate_workspace`` expects. A path recorded on another machine is re-rooted
    by its ``<scratch name>/`` marker, so no stale absolute path is left behind."""
    if not recorded:
        return recorded
    marker = f"/{source_work.name}/"
    posix = Path(recorded).as_posix()
    if marker in posix:
        return str(work_dir / posix.split(marker, 1)[1])
    return recorded


def _relabel_result(
    result: dict[str, Any], org_map: dict[str, str], work_dir: Path, source_work: Path
) -> dict[str, Any]:
    out = dict(result)
    out["workspace"] = _reroot_workspace(result.get("workspace", ""), work_dir, source_work)
    out["docsets"] = [{**d, "org": _map_org(d["org"], org_map)} for d in result.get("docsets", [])]
    out["documents"] = [
        {**d, "org": _map_org(d["org"], org_map)} for d in result.get("documents", [])
    ]
    return out


def _relabel_sidecar(plan: dict[str, Any], org_map: dict[str, str]) -> dict[str, Any]:
    out = dict(plan)
    out["entries"] = [{**e, "org": _map_org(e["org"], org_map)} for e in plan.get("entries", [])]
    ids = {}
    for ref, dgml_id in plan.get("docset_ids", {}).items():
        org, _, docset = ref.partition("/")
        ids[f"{_map_org(org, org_map)}/{docset}"] = dgml_id
    out["docset_ids"] = ids
    return out


def _draw_dirs(cell_dir: Path) -> list[Path]:
    if (cell_dir / "result.json").is_file():
        return [cell_dir]
    draws = cell_dir / "draws"
    if not draws.is_dir():
        return []
    return sorted(d for d in draws.iterdir() if (d / "result.json").is_file())


def import_run(
    source: Path,
    runs_dir: Path,
    work_dir: Path,
    source_work: Path,
    corpus_root: Path,
    org_map: dict[str, str],
    dry_run: bool,
) -> dict[str, Any]:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    cells = json.loads((source / "cells.json").read_text(encoding="utf-8"))
    if isinstance(cells, list):
        cells = {c["cell_id"]: c for c in cells}
    allowed = _allowed_docsets(corpus_root)
    run_id = manifest["run_id"]
    target = runs_dir / run_id
    if target.exists():
        raise SystemExit(f"{target} exists; remove it first")

    kept: dict[str, Any] = {}
    dropped: dict[str, str] = {}
    renamed: list[str] = []
    for cell_id, cell in sorted(cells.items()):
        org = _map_org(cell["org"], org_map)
        if cell["docset"] not in allowed or allowed[cell["docset"]] != org:
            dropped[cell_id] = f"{cell['org']}/{cell['docset']}"
            continue
        if org != cell["org"]:
            renamed.append(cell_id)
        kept[cell_id] = {**cell, "org": org}

    include = sorted({f"{c['org']}/{c['docset']}" for c in kept.values()})
    spec = dict(manifest["spec"])
    corpus = dict(spec.get("corpus", {}))
    corpus["orgs"] = []
    corpus["docsets"] = {"include": include, "exclude": [], "all_with_refs": False}
    spec["corpus"] = corpus
    spec["metrics"] = ALL_FAMILIES
    new_manifest = dict(manifest)
    new_manifest["spec"] = spec
    new_manifest["cells"] = {k: v for k, v in manifest.get("cells", {}).items() if k in kept}
    new_manifest["updated_at"] = datetime.now(UTC).isoformat()

    draws_copied = 0
    dgml_files = 0
    sidecars_missing: list[str] = []
    if not dry_run:
        target.mkdir(parents=True)
        (target / "cells").mkdir()
        for cell_id in kept:
            src_cell = source / "cells" / cell_id
            for src_draw in _draw_dirs(src_cell):
                rel = src_draw.relative_to(source)
                dst_draw = target / rel
                dst_draw.mkdir(parents=True, exist_ok=True)
                result = json.loads((src_draw / "result.json").read_text(encoding="utf-8"))
                (dst_draw / "result.json").write_text(
                    json.dumps(_relabel_result(result, org_map, work_dir, source_work), indent=2),
                    encoding="utf-8",
                )
                sidecar = src_draw / "workspace" / "mca-workspace.json"
                if sidecar.is_file():
                    plan = json.loads(sidecar.read_text(encoding="utf-8"))
                    (dst_draw / "workspace").mkdir(exist_ok=True)
                    (dst_draw / "workspace" / "mca-workspace.json").write_text(
                        json.dumps(_relabel_sidecar(plan, org_map), indent=2), encoding="utf-8"
                    )
                else:
                    sidecars_missing.append(str(rel))
                if (src_draw / "dgml").is_dir():
                    shutil.copytree(src_draw / "dgml", dst_draw / "dgml")
                    dgml_files += sum(1 for _ in (dst_draw / "dgml").rglob("*") if _.is_file())
                for name in ("status.json",):
                    if (src_draw / name).is_file():
                        shutil.copy2(src_draw / name, dst_draw / name)
                draws_copied += 1
            if (src_cell / "status.json").is_file():
                shutil.copy2(src_cell / "status.json", target / "cells" / cell_id / "status.json")
        (target / "cells.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")
        (target / "manifest.json").write_text(json.dumps(new_manifest, indent=2), encoding="utf-8")
        for name in ("spec.resolved.yaml", "prices.json", "adoption.json"):
            if (source / name).is_file():
                shutil.copy2(source / name, target / name)
        work_dir.mkdir(parents=True, exist_ok=True)
        link = work_dir / run_id
        src_ws = source_work / run_id
        if src_ws.is_dir() and not link.exists():
            # relative, so the link survives the checkout moving or being mounted elsewhere
            link.symlink_to(os.path.relpath(src_ws, link.parent), target_is_directory=True)
    record = {
        "schema_version": 1,
        "imported_at": datetime.now(UTC).isoformat(),
        "source_run": run_id,
        "source_path": os.path.relpath(source, runs_dir),
        "source_work": os.path.relpath(source_work / run_id, work_dir),
        "corpus_root": str(corpus_root),
        "org_map": org_map,
        "cells_kept": len(kept),
        "cells_dropped": dropped,
        "cells_org_renamed": renamed,
        "draws_copied": draws_copied,
        "dgml_files_copied": dgml_files,
        "sidecars_missing": sidecars_missing,
        "docsets": include,
        "dry_run": dry_run,
    }
    if not dry_run:
        (target / "import.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="the earlier implementation's run directory")
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--source-work",
        type=Path,
        required=True,
        help="the earlier implementation's scratch (workspace) directory",
    )
    parser.add_argument("--corpus-root", type=Path, default=Path("data/corpus"))
    parser.add_argument(
        "--org-map", action="append", default=[], metavar="OLD=NEW", help="rename an org"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    org_map = dict(item.split("=", 1) for item in args.org_map)
    record = import_run(
        args.source.expanduser().resolve(),
        args.runs_dir.expanduser(),
        args.work_dir.expanduser(),
        args.source_work.expanduser(),
        args.corpus_root.expanduser().resolve(),
        org_map,
        args.dry_run,
    )
    summary = {k: v for k, v in record.items() if k != "cells_dropped"}
    summary["cells_dropped"] = len(record["cells_dropped"])
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
