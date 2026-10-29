"""The ``dgml`` subprocess adapter: argv, JSON payloads, error classification, config.toml.

The CLI contract: stdout is a JSON payload, stderr an ``{"error": {"code", "message"}}``
envelope, exit 0 ok / 1 error / 2 ``check`` found issues. Two things to know:

- ``usage.jsonl`` exists only under ``--debug``, so generation always passes it; without it
  every economics metric would be silently empty.
- Every invocation's stdout and stderr is kept (``logs/NNNN-<command>.{stdout,stderr}.log``
  under the draw), whether it succeeded or not.

dgml has no rate-limit error code: a provider 429 surfaces as ``INTERNAL_ERROR`` with the
message as the only clue. So classification reads the message, and the default is
*permanent* -- retrying a schema error costs money and cannot succeed.
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from model_compass.domain import ModelSlot
from model_compass.errors import CompassError, ConfigError, EngineError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from model_compass.domain import AxisValue

log = logging.getLogger(__name__)

CONFIG_FILENAME: Final[str] = "config.toml"
_EXIT_OK: Final[int] = 0
_MAX_STDERR_IN_MESSAGE: Final[int] = 800
_TIMEOUT_S: Final[float] = 1800.0

# -- error classification ----------------------------------------------------------------

PERMANENT_CODES: Final[frozenset[str]] = frozenset(
    {
        "AUTH_ERROR",
        "CHAIN_CONFIG",
        "CLASSIFICATION_CONFIG_INVALID",
        "CLASSIFICATION_CONFIG_MISSING",
        "CLUSTERING_CONFIG_INVALID",
        "CONFLICT",
        "CONVERSION_CONFIG_INVALID",
        "CORRUPT_METADATA",
        "DOCSET_NOT_FOUND",
        "FILE_NOT_FOUND",
        "GROUNDED_CONFIG_INVALID",
        "GROUNDED_CONFIG_MISSING",
        "INVALID_ARGUMENT",
        "INVALID_PDF",
        "LEGACY_CONFIG_PRESENT",
        "MANIFEST_INVALID",
        "MISSING_EXTRA",
        "MODELS_CONFIG_INVALID",
        "MODEL_NOT_SUPPORTED",
        "NOT_FOUND",
        "NOT_IMPLEMENTED",
        "NO_FILES",
        "OCR_CONFIG_INVALID",
        "OCR_CONFIG_MISSING",
        "SCHEMA_INVALID",
        "SCHEMA_NOT_FOUND",
        "STORAGE_BACKEND_MISMATCH",
        "STORAGE_CONFIG_INVALID",
        "STORAGE_PROVIDER_UNRESOLVABLE",
        "STYLE_CONFIG_INVALID",
        "TEXT_EXTRACTION_CONFIG_INVALID",
        "UNSUPPORTED_FILE_TYPE",
        "VALUES_NOT_FOUND",
        "WORKSPACE_NOT_INITIALIZED",
    }
)
"""dgml codes meaning the input or configuration is wrong. Never retried."""

_TRANSIENT_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"\b429\b|rate[ _-]?limit|too many requests|quota exceeded", re.I), "rate_limited"),
    (re.compile(r"\boverload|\bcapacity\b|model is busy", re.I), "overloaded"),
    (re.compile(r"\btimed? ?out\b|\btimeout\b|deadline exceeded", re.I), "timeout"),
    (
        re.compile(r"\b(5\d\d)\b|internal server error|bad gateway|service unavailable", re.I),
        "server_error",
    ),
    (
        re.compile(
            r"connection (reset|aborted|error)|temporarily unavailable|\bdns\b|network", re.I
        ),
        "network",
    ),
    (
        re.compile(r"APIConnectionError|ServiceUnavailable|InternalServerError", re.I),
        "provider_unavailable",
    ),
)

TRANSIENT_CODES: Final[frozenset[str]] = frozenset(code for _, code in _TRANSIENT_PATTERNS)


def classify(code: str | None, message: str | None) -> str:
    """The code to record: a permanent dgml code wins outright (``AUTH_ERROR ... 429`` is never
    retried); otherwise the message may mark it transient; anything unrecognised stays
    permanent."""
    normalized = (code or "DGML_ERROR").strip().upper()
    if normalized in PERMANENT_CODES:
        return normalized.lower()
    for pattern, transient in _TRANSIENT_PATTERNS:
        if pattern.search(message or ""):
            return transient
    return normalized.lower()


def is_transient(exc: BaseException) -> bool:
    """Worth retrying: a transient dgml code, or a timeout or OS-level hiccup."""
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, EngineError):
        return exc.code in TRANSIENT_CODES
    if isinstance(exc, CompassError):
        return False
    return isinstance(exc, OSError)


# -- config.toml ---------------------------------------------------------------------------

_SECTIONS: Final[tuple[tuple[str, tuple[tuple[ModelSlot, str], ...]], ...]] = (
    ("classification", ((ModelSlot.CLASSIFICATION, "model"),)),
    ("generation", ((ModelSlot.GENERATION, "model"), (ModelSlot.LABEL, "label_model"))),
    ("grounded", ((ModelSlot.SCHEMA, "schema_model"), (ModelSlot.VALUES, "values_model"))),
)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_config_toml(settings: Mapping[str, AxisValue], *, header: str = "") -> str:
    """The per-workspace ``config.toml`` layer: the model slots a cell sets, plus
    ``generation.thinking``. Unset slots are absent, so dgml falls back to the machine's
    configuration -- what "we are not sweeping this slot" should mean."""
    lines: list[str] = []
    if header:
        lines += [f"# {line}" for line in header.splitlines()]
        lines.append("")
    lines.append("# Written by dgml-compass. Per-workspace overrides only.")
    for section, slots in _SECTIONS:
        assigned = [
            (key, str(settings[slot.value])) for slot, key in slots if settings.get(slot.value)
        ]
        if section == "generation" and settings.get("generation.thinking"):
            assigned.append(("thinking", str(settings["generation.thinking"])))
        if not assigned:
            continue
        lines += ["", f"[{section}]"]
        lines += [f'{key} = "{_escape(value)}"' for key, value in assigned]
    return "\n".join(lines) + "\n"


# -- the adapter -------------------------------------------------------------------------


class DgmlCli:
    """Drives the real CLI with argument vectors, never a shell string."""

    def __init__(
        self,
        *,
        workspace: Path,
        repo_root: Path | None = None,
        log_dir: Path | None = None,
        retries: int = 2,
        retry_initial_s: float = 1.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._workspace = Path(workspace)
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._log_dir = log_dir
        self._retries = retries
        self._retry_initial_s = retry_initial_s
        self._runner = runner or (lambda argv, **kw: subprocess.run(list(argv), **kw))
        self._sequence = 0

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def base_argv(self) -> tuple[str, ...]:
        """``uv run dgml`` inside the dgml checkout, else an installed ``dgml``."""
        return ("uv", "run", "dgml") if self._repo_root is not None else ("dgml",)

    def _argv(self, args: Sequence[str], *, workspace: bool = True) -> tuple[str, ...]:
        head = list(self.base_argv)
        if workspace:
            head += ["--workspace", str(self._workspace), "--format", "json"]
        return (*head, *args)

    def _capture(self, name: str, stdout: str, stderr: str) -> None:
        if self._log_dir is None:
            return
        self._sequence += 1
        for suffix, text in (("stdout", stdout), ("stderr", stderr)):
            if text:
                path = self._log_dir / f"{self._sequence:04d}-{name}.{suffix}.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

    def _run_once(self, argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._repo_root,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(
                f"dgml exceeded {timeout:g}s: {' '.join(argv[:6])}", code="timeout"
            ) from exc
        except FileNotFoundError as exc:
            raise ConfigError(
                f"could not run {argv[0]!r}; install dgml or set DGC_DGML_REPO to a checkout",
                code="dgml_missing",
            ) from exc

    def _invoke(self, *args: str, retries: int | None = None) -> dict[str, Any]:
        """One command; transient failures are retried with jittered exponential backoff."""
        argv = self._argv(args)
        name = "-".join(part for part in args[:2] if not part.startswith("-")) or "dgml"
        attempts = 1 + max(0, self._retries if retries is None else retries)
        for attempt in range(attempts):
            started = datetime.now(UTC)
            try:
                completed = self._run_once(argv, _TIMEOUT_S)
                self._capture(name, completed.stdout or "", completed.stderr or "")
                log.debug(
                    "dgml %s exited %d in %.3fs",
                    name,
                    completed.returncode,
                    (datetime.now(UTC) - started).total_seconds(),
                )
                if completed.returncode != _EXIT_OK:
                    raise self._error(name, argv, completed)
                return self._parse_stdout(name, completed.stdout or "")
            except Exception as exc:
                if attempt + 1 >= attempts or not is_transient(exc):
                    raise
                delay = min(30.0, self._retry_initial_s * 2**attempt)
                time.sleep(delay + random.uniform(0, self._retry_initial_s))
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _parse_stdout(name: str, stdout: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EngineError(
                f"dgml {name} produced output that is not JSON: {text[:200]}", code="bad_payload"
            ) from exc
        return payload if isinstance(payload, dict) else {"result": payload}

    @staticmethod
    def _error(
        name: str, argv: Sequence[str], completed: subprocess.CompletedProcess[str]
    ) -> EngineError:
        stderr = (completed.stderr or "").strip()
        dgml_code: str | None = None
        message = stderr[:_MAX_STDERR_IN_MESSAGE] or f"dgml {name} exited {completed.returncode}"
        try:
            error = json.loads(stderr)["error"]
            dgml_code = str(error.get("code") or "")
            message = str(error.get("message") or message)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass  # not an envelope; the raw stderr is the message
        return EngineError(
            f"dgml {name}: {message}",
            code=classify(dgml_code, message),
            dgml_code=dgml_code,
            returncode=completed.returncode,
            argv=list(argv),
        )

    def workspace_create(self, *, name: str, organization: str) -> dict[str, Any]:
        return self._invoke(
            "workspace",
            "create",
            str(self._workspace),
            "--organization",
            organization,
            "--name",
            name,
            retries=0,
        )

    def file_add(
        self, path: Path, *, text_mode: str = "digital", on_conflict: str = "skip"
    ) -> dict[str, Any]:
        """``--on-conflict skip`` makes re-adding a document a no-op."""
        return self._invoke(
            "file", "add", str(path), "--on-conflict", on_conflict, "--text-mode", text_mode
        )

    def docset_create(self, *, name: str, description: str = "") -> dict[str, Any]:
        args = ["docset", "create", "--name", name]
        if description:
            args += ["--description", description]
        return self._invoke(*args, retries=0)

    def docset_add_file(self, file_id: str, *, docset_id: str) -> dict[str, Any]:
        return self._invoke("docset", "add-file", file_id, "--docset", docset_id, retries=0)

    def docset_generate(
        self,
        docset_id: str,
        *,
        model: str | None = None,
        label_model: str | None = None,
        window_size: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_parallel_calls: int | None = None,
    ) -> dict[str, Any]:
        args = ["docset", "generate", docset_id, "--debug"]
        for flag, value in (
            ("--model", model),
            ("--label-model", label_model),
            ("--window-size", window_size),
            ("--temperature", temperature),
            ("--max-tokens", max_tokens),
            ("--max-parallel-calls", max_parallel_calls),
        ):
            if value is not None:
                args += [flag, str(value)]
        return self._invoke(*args)

    def version(self) -> str:
        argv = self._argv(["--version"], workspace=False)
        completed = self._run_once(argv, 60.0)
        if completed.returncode != _EXIT_OK:
            raise self._error("version", argv, completed)
        return (completed.stdout or "").strip()
