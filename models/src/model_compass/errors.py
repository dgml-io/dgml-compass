"""Exceptions with a machine-readable ``code``, and the process exit codes the CLI uses."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from pydantic import ValidationError


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    FINDINGS = 2
    BUDGET_EXCEEDED = 3


class CompassError(Exception):
    default_code: ClassVar[str] = "compass_error"
    exit_code: ClassVar[ExitCode] = ExitCode.ERROR

    def __init__(self, message: str, *, code: str | None = None, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.context: dict[str, Any] = dict(context)

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        """The JSON error envelope written to stderr and the event log."""
        return {"error": {"code": self.code, "message": self.message, "context": self.context}}


class ConfigError(CompassError):
    default_code = "config_invalid"


class CorpusError(CompassError):
    default_code = "corpus_invalid"


class EngineError(CompassError):
    default_code = "engine_failed"


class BudgetExceeded(CompassError):
    default_code = "budget_exceeded"
    exit_code = ExitCode.BUDGET_EXCEEDED


def to_config_error(
    exc: ValidationError, *, source: str, code: str = "config_invalid"
) -> ConfigError:
    """Name every offending field path (``corpus.docsets.include[2]``) instead of a traceback."""

    def path(loc: tuple[int | str, ...]) -> str:
        out = ""
        for part in loc:
            out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
        return out or "<root>"

    errors = exc.errors()
    fields = [path(tuple(e["loc"])) for e in errors]
    lines = [f"  {f}: {e['msg']}" for f, e in zip(fields, errors, strict=True)][:10]
    noun = "error" if len(errors) == 1 else "errors"
    message = f"{source}: {len(errors)} validation {noun}\n" + "\n".join(lines)
    return ConfigError(message, code=code, source=source, fields=fields)
