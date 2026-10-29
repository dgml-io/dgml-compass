"""Paths and helpers shared across test packages."""

from __future__ import annotations

import tarfile
from pathlib import Path

from model_compass.config import MODELS_DIR

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
GOLDEN = TESTS / "golden"
MINI = FIXTURES / "mini_corpus"
SPECS = MODELS_DIR / "specs"


def extract(archive: Path, into: Path) -> Path:
    """Unpack a fixture tarball into ``into`` and return ``into``."""
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")
    return into
