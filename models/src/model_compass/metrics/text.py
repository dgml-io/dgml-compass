"""The one value normalisation every extraction metric uses, and the keying schemes
(docs/METRICS.md §1).

A gold value's ``#N`` suffix is provenance, never a comparison key: it indexes a token stream
the corpus does not ship.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

EMPTY: Final[str] = "empty"
"""Sentinel for "this field is absent". Passes through normalisation untouched (DECISIONS 0014)."""

SEP: Final[str] = "__"
"""Separator in the ``<file_id>__<label>`` scoring key."""

WORD_RE: Final[re.Pattern[str]] = re.compile(r"\w+")
"""Word tokens of the tree family's reading-order streams and tree edit distance."""

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\w+(?:[.,]\w+)*", re.UNICODE)
_PUNCT_BULLET: Final[frozenset[str]] = frozenset(string.punctuation + "•")
_PROVENANCE: Final[re.Pattern[str]] = re.compile(r"^(?P<text>.*)#(?P<offset>\d+)$", re.DOTALL)


def normalize_text(text: str) -> str:
    """NFKC, lower-case, tokens of ``\\w+(?:[.,]\\w+)*`` (so ``1,250.00`` stays whole), drop
    punctuation and bullets, rejoin with single spaces. The sentinel is exempt (DECISIONS 0007)."""
    if text == EMPTY:
        return text
    folded = unicodedata.normalize("NFKC", text).lower()
    tokens = (
        "".join("".join(ch for ch in token if ch not in _PUNCT_BULLET).split())
        for token in _TOKEN_RE.findall(folded)
    )
    return " ".join(token for token in tokens if token)


def strip_provenance(value: str) -> tuple[str, int | None]:
    """``"<text>#<offset>"`` -> ``(text, offset)``; text may itself contain ``#``."""
    match = _PROVENANCE.match(value)
    if not match:
        return value, None
    return match["text"], int(match["offset"])


def positional_keys(values: Sequence[str]) -> set[str]:
    """Strict scheme: ``"<normalised>#<index in reading order>"``; order-sensitive."""
    keys: set[str] = set()
    for index, raw in enumerate(values):
        base = normalize_text(raw)
        keys.add(base if base == EMPTY else f"{base}#{index}")
    return keys


def occurrence_keys(values: Iterable[str]) -> set[str]:
    """Relaxed scheme: an order-free multiset; repeats of a value get ``#2``, ``#3``, ..."""
    seen: Counter[str] = Counter()
    keys: set[str] = set()
    for raw in values:
        base = normalize_text(raw)
        if base == EMPTY:
            keys.add(base)
            continue
        seen[base] += 1
        keys.add(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return keys


def score_key(file_id: str, label: str) -> str:
    return f"{file_id}{SEP}{label}"


def split_key(key: str) -> tuple[str, str]:
    """Inverse of :func:`score_key`; splits at the first separator."""
    file_id, _, label = key.partition(SEP)
    return file_id, label
