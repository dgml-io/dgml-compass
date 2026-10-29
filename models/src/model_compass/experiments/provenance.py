"""What a run records about where it ran: git state, tool versions and the corpus hash."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from model_compass import __version__, ids
from model_compass.config import REPO_ROOT
from model_compass.engine.dgml_cli import DgmlCli
from model_compass.errors import ConfigError
from model_compass.experiments.manifest import Provenance, RepoProvenance

if TYPE_CHECKING:
    from model_compass.config import Settings
    from model_compass.corpus.models import Corpus

log = logging.getLogger(__name__)


def _git(path: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repo_provenance(name: str, path: Path) -> RepoProvenance:
    """An unreadable or non-git path counts as dirty: we cannot claim it is clean."""
    commit = _git(path, "rev-parse", "HEAD")
    status = _git(path, "status", "--porcelain", "--", ".")
    return RepoProvenance(
        name=name,
        path=str(path),
        commit=commit,
        branch=_git(path, "rev-parse", "--abbrev-ref", "HEAD") or None,
        dirty=bool(status) if status is not None else commit is None,
    )


def _prices_version(prices_file: Path) -> str | None:
    try:
        raw = yaml.safe_load(prices_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    version = (raw or {}).get("version") if isinstance(raw, dict) else None
    return str(version) if version else None


def _dgml_version(settings: Settings) -> str | None:
    if not settings.dgml_repo.is_dir() or shutil.which("uv") is None:
        return None
    try:
        return DgmlCli(workspace=settings.work_dir, repo_root=settings.dgml_repo).version()
    except Exception as exc:  # provenance is best effort
        log.debug("dgml version unavailable: %s", exc)
        return None


def capture_provenance(settings: Settings, *, corpus_hash: str | None) -> Provenance:
    """Git state of dgml, the corpus and this repo, tool versions and the corpus hash."""
    paths = {
        "dgml": settings.dgml_repo,
        "corpus": settings.corpus_root,
        "dgml-compass": REPO_ROOT,
    }
    return Provenance(
        repos={name: repo_provenance(name, path) for name, path in paths.items()},
        dgml_version=_dgml_version(settings),
        python_version=sys.version.split()[0],
        package_version=__version__,
        corpus_hash=corpus_hash,
        prices_version=_prices_version(settings.prices_file),
    )


def require_clean_corpus(provenance: Provenance, *, allow_dirty: bool = False) -> None:
    """Two runs are comparable only if they read the same bytes."""
    repo = provenance.repos.get("corpus")
    if repo is None or not repo.dirty or allow_dirty:
        return
    raise ConfigError(
        f"the corpus at {repo.path} has uncommitted changes, so this run would not be "
        "reproducible or comparable; commit it, or allow a dirty corpus explicitly",
        code="corpus_dirty",
    )


def corpus_fingerprint(corpus: Corpus) -> str | None:
    root = Path(corpus.root)
    existing = [root / p for p in corpus.consumed_paths() if (root / p).is_file()]
    return ids.corpus_hash(existing, root=root) if existing else None
