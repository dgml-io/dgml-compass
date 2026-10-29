"""Content-addressed identifiers.

A ``cell_id`` must stay byte-identical across versions: existing runs are resumed, adopted
and compared by it. So the canonical JSON, the blake2b digest and the domain prefixes
(``mca.cell.v1`` ...) are kept exactly, names and all; ``mca`` is the fixed namespace prefix
of every digest domain, not a setting.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence, Set
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Final

CELL_ID_LENGTH: Final[int] = 12
_RUN_SUFFIX_LENGTH: Final[int] = 8
_CORPUS_HASH_LENGTH: Final[int] = 16
RUN_ID_TIMESTAMP_FORMAT: Final[str] = "%Y%m%d-%H%M%S"
"""The UTC timestamp a run id starts with."""


def normalize(value: Any) -> Any:
    """One stable spelling per value: sorted keys, ``-0.0`` → ``0.0``, enums by value, no NaN."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"cannot hash a non-finite float: {value!r}")
        return 0.0 if value == 0.0 else value
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, Path | PurePosixPath):
        return value.as_posix()
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(k): normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, Set):
        return sorted((normalize(v) for v in value), key=_sort_key)
    if isinstance(value, Sequence):
        return [normalize(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return normalize(dump(mode="json"))
    raise TypeError(f"cannot canonicalise {type(value).__name__} for hashing")


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any, *, length: int = CELL_ID_LENGTH, prefix: bytes = b"") -> str:
    """blake2b of the canonical JSON, truncated; ``prefix`` separates the hash spaces."""
    if not 4 <= length <= 128:
        raise ValueError("length must be between 4 and 128 hex characters")
    hasher = hashlib.blake2b(digest_size=(length + 1) // 2)
    if prefix:
        hasher.update(prefix + b"\x00")
    hasher.update(canonical_json(value))
    return hasher.hexdigest()[:length]


def cell_id(identity: Mapping[str, Any]) -> str:
    """Hash of ``{org, docset, settings, seed}`` -- never draws, shape or descriptions."""
    if not identity:
        raise ValueError("a cell identity must not be empty")
    return digest(identity, length=CELL_ID_LENGTH, prefix=b"mca.cell.v1")


def run_id(spec: Any, provenance: Any, *, now: datetime | None = None) -> str:
    """``YYYYMMDD-HHMMSS-<8 hex>``: sortable by time, unique by content."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    suffix = digest(
        {"spec": spec, "provenance": provenance, "at": moment},
        length=_RUN_SUFFIX_LENGTH,
        prefix=b"mca.run.v1",
    )
    return f"{moment.strftime(RUN_ID_TIMESTAMP_FORMAT)}-{suffix}"


def _file_fingerprint(path: Path, *, root: Path) -> tuple[str, int, str]:
    """``(path relative to root, size, sha256)``."""
    resolved = path.resolve()
    hasher = hashlib.sha256()
    size = 0
    with resolved.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            size += len(chunk)
            hasher.update(chunk)
    return resolved.relative_to(root.resolve()).as_posix(), size, hasher.hexdigest()


def corpus_hash(paths: Iterable[Path], *, root: Path) -> str:
    """Order-independent, content-sensitive hash of the files a run consumed."""
    fingerprints = sorted(_file_fingerprint(path, root=root) for path in paths)
    if not fingerprints:
        raise ValueError("refusing to hash an empty corpus selection")
    return digest(
        [list(item) for item in fingerprints], length=_CORPUS_HASH_LENGTH, prefix=b"mca.corpus.v1"
    )
