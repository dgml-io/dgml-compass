"""A dgml double: the real adapter, with its CLI calls answered from recorded payloads.

``scripted_runner`` fakes ``subprocess.run`` so the real :class:`DgmlCli` (argv, JSON parsing,
error envelopes, retry classification, log capture) runs against recorded output.
:class:`FakeDgml` subclasses the adapter and "generates": it writes a small DGML file per
document and appends the recorded ``usage.jsonl`` rows, so a run made with it is scorable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from model_compass.engine.dgml_cli import DgmlCli

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cli_responses"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["dgml"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def scripted_runner(script):
    """Pops one outcome per call: a CompletedProcess, a callable taking argv, or an exception."""
    remaining = list(script)
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if not remaining:
            raise AssertionError(f"unexpected extra dgml call: {argv}")
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome(argv) if callable(outcome) else outcome

    run.calls = calls
    return run


def _refuse(argv, **kwargs):
    raise AssertionError(f"the double must not start a subprocess: {argv}")


DGML = (
    '<dg:chunk xmlns:dg="http://dgml.io/ns/dg#" dg:structure="document">'
    "<Party_Name>ACME LIMITED</Party_Name><Effective_Date>1 APRIL 2015</Effective_Date>"
    "<dg:chunk>{name}</dg:chunk></dg:chunk>"
)


class FakeDgml(DgmlCli):
    """``outcome``: ``converted`` (DGML for every document), ``failed`` (dgml reports every
    document failed) or ``unreported`` (an empty results array: succeeded, but no DGML)."""

    def __init__(self, workspace: Path, *, outcome: str = "converted") -> None:
        super().__init__(workspace=workspace, runner=_refuse, retries=0)
        self.outcome = outcome
        self.calls: list[tuple[str, dict]] = []
        self.files: dict[str, Path] = {}
        self.docsets: dict[str, list[str]] = {}

    def workspace_create(self, *, name, organization):
        self.calls.append(("workspace_create", {"name": name}))
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "workspace.json").write_text(json.dumps({"name": name}))
        return {**load("workspace_create.json"), "name": name, "organization": organization}

    def file_add(self, path, *, text_mode="digital", on_conflict="skip"):
        self.calls.append(("file_add", {"path": str(path), "text_mode": text_mode}))
        file_id = f"f{len(self.files) + 1:03d}"
        self.files[file_id] = Path(path)
        return {**load("file_add.json"), "file_id": file_id}

    def docset_create(self, *, name, description=""):
        self.calls.append(("docset_create", {"name": name}))
        docset_id = f"d{len(self.docsets) + 1:03d}"
        self.docsets[docset_id] = []
        return {**load("docset_create.json"), "docset_id": docset_id, "name": name}

    def docset_add_file(self, file_id, *, docset_id):
        self.docsets[docset_id].append(file_id)
        return {**load("docset_add_file.json"), "file_id": file_id, "docset_id": docset_id}

    def docset_generate(self, docset_id, **options):
        self.calls.append(("docset_generate", {"docset_id": docset_id, **options}))
        if docset_id not in self.docsets:  # a reused workspace: dgml would remember it
            sidecar = json.loads((self.workspace / "mca-workspace.json").read_text())
            for entry in sidecar["entries"]:
                self.files[entry["dgml_file_id"]] = Path(entry["source_path"])
                self.docsets.setdefault(entry["dgml_docset_id"], []).append(entry["dgml_file_id"])
        results = []
        for file_id in self.docsets[docset_id] if self.outcome != "unreported" else []:
            source = self.files[file_id]
            if self.outcome == "failed":
                error = {"code": "GENERATION_FAILED", "message": "provider refused"}
                results.append(
                    {"file_id": file_id, "source": source.name, "status": "failed", "error": error}
                )
                continue
            output = f"docsets/{docset_id}/files/{file_id}/{source.stem}.dgml.xml"
            target = self.workspace / output
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(DGML.format(name=source.name))
            results.append(
                {"file_id": file_id, "output": output, "source": source.name, "status": "converted"}
            )
        with (self.workspace / "usage.jsonl").open("a") as usage:
            usage.write(raw("usage.jsonl").splitlines()[0] + "\n")
        converted = sum(1 for r in results if r["status"] == "converted")
        return {
            "docset_id": docset_id,
            "models": {"model": options.get("model") or ""},
            "results": results,
            "summary": {
                "total": len(results),
                "converted": converted,
                "skipped": 0,
                "failed": len(results) - converted,
            },
        }

    def version(self):
        return raw("version.txt").strip()
