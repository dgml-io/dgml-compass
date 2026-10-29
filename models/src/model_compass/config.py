"""Settings: where things are, how wide to run, how much to spend.

Precedence, highest first: explicit overrides (CLI flags) > ``DGC_<FIELD>`` environment
variables > a profile YAML > defaults. Paths are only checked when a command needs them, so
``dgc report`` works on a machine without a dgml checkout.

Provider API keys are not settings: dgml reads them from the environment itself. ``dgc``
loads a ``.env`` file (see :func:`load_dotenv`) into its environment before anything runs, so
keys and ``DGC_*`` values kept there reach both the settings and the dgml subprocesses.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from model_compass.errors import ConfigError, to_config_error

MODELS_DIR: Final[Path] = Path(__file__).resolve().parents[2]
"""The ``models/`` folder: holds ``conf/``, ``data/``, ``specs/`` and the ``.env`` read when ``dgc``
starts."""

REPO_ROOT: Final[Path] = MODELS_DIR.parent
"""The dgml-compass checkout, whose commit each run records."""

_CHECKOUT_PARENT: Final[Path] = REPO_ROOT.parent
"""The folder holding this repo; the dgml checkout defaults to a sibling of it."""

ENV_PREFIX: Final[str] = "DGC_"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dgml_repo: Path = Field(
        default_factory=lambda: _CHECKOUT_PARENT / "dgml",
        description="dgml checkout; `dgc run` calls `uv run dgml` inside it.",
    )
    corpus_root: Path = Field(default_factory=lambda: MODELS_DIR / "data" / "corpus")
    prices_file: Path = Field(
        default_factory=lambda: MODELS_DIR / "conf" / "prices.yaml",
        description="Per-model token prices for plan estimates and the budget cap.",
    )
    runs_dir: Path = Path("./runs")
    work_dir: Path = Path("./.dgc/work")
    max_parallel_cells: int = Field(default=4, ge=1, le=256)
    max_parallel_calls: int = Field(default=8, ge=1, le=256)
    budget_usd: float = Field(default=25.0, gt=0.0)

    @field_validator("dgml_repo", "corpus_root", "prices_file", "runs_dir", "work_dir")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return Path(value).expanduser().resolve()

    def require(self, field: str) -> Path:
        """A path setting that must exist now, or a ConfigError naming how to set it."""
        path = getattr(self, field)
        if not path.exists():
            raise ConfigError(
                f"{field} not found at {path}; set {ENV_PREFIX}{field.upper()} or a profile",
                code="path_missing",
                field=field,
            )
        return path


def load_dotenv(path: Path, environ: dict[str, str] | None = None) -> list[str]:
    """Set ``KEY=value`` lines from ``path`` into ``environ`` (default ``os.environ``).

    Never overrides a variable that is already set: the real environment wins. Accepts
    ``# comments``, blank lines, ``export KEY=value`` and single- or double-quoted values;
    an empty value (``KEY=``) is skipped so a placeholder never masks anything. Returns the
    names it set -- never the values.
    """
    env = os.environ if environ is None else environ
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif value.startswith("#"):
            value = ""  # `KEY=   # comment` is an empty placeholder
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and value and key not in env:
            env[key] = value
            loaded.append(key)
    return loaded


def _read_profile(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"profile not found: {path}", code="profile_missing") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"profile {path} is not valid YAML: {exc}", code="profile_invalid"
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"profile {path} must be a mapping", code="profile_invalid")
    unknown = sorted(set(raw) - set(Settings.model_fields))
    if unknown:
        raise ConfigError(
            f"profile {path} sets unknown settings: {', '.join(unknown)}",
            code="profile_unknown_key",
        )
    return raw


def load_settings(
    *, profile: Path | None = None, environ: dict[str, str] | None = None, **overrides: Any
) -> Settings:
    """Merge defaults < profile < ``DGC_*`` env < overrides (``None`` overrides are ignored)."""
    env = os.environ if environ is None else environ
    data: dict[str, Any] = _read_profile(profile) if profile else {}
    for field in Settings.model_fields:
        if (value := env.get(f"{ENV_PREFIX}{field.upper()}")) is not None:
            data[field] = value
    data.update({k: v for k, v in overrides.items() if v is not None})
    try:
        return Settings(**data)
    except ValidationError as exc:
        raise to_config_error(exc, source=f"settings ({profile or 'defaults'})") from exc
