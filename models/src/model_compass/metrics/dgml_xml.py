"""Reading DGML safely, and what counts as an element.

DGML carries the docset's semantic tags and the ``dg:`` structural frame. For the structural
families the frame is transparent: not counted, no container/leaf role, not in ancestor chains
(DECISIONS 0009). Parsing is stdlib ``ElementTree``; any ``DOCTYPE`` is refused (no entity
expansion).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DG_NS: Final[str] = "http://dgml.io/ns/dg#"
ORIGIN_ATTR: Final[str] = f"{{{DG_NS}}}origin"
_DOCTYPE: Final[re.Pattern[bytes]] = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


class UnparseableDocument(Exception):
    """Counted and reported, never skipped silently."""


def parse_dgml_bytes(data: bytes, *, source: str = "<bytes>") -> ElementTree.Element:
    if _DOCTYPE.search(data):
        raise UnparseableDocument(f"{source}: DGML must not carry a DOCTYPE declaration")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise UnparseableDocument(f"{source}: {exc}") from exc


def parse_dgml(path: Path) -> ElementTree.Element:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UnparseableDocument(f"{path}: {exc}") from exc
    return parse_dgml_bytes(data, source=str(path))


def local_name(tag: object) -> str | None:
    """Name without namespace; ``None`` for comments and processing instructions."""
    if not isinstance(tag, str):
        return None
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def is_frame(elem: ElementTree.Element) -> bool:
    return str(elem.tag).startswith(f"{{{DG_NS}}}")


def qualified_name(elem: ElementTree.Element) -> str | None:
    """Local name, with the ``dg:`` frame kept distinguishable from docset vocabulary."""
    name = local_name(elem.tag)
    if name is None:
        return None
    return f"dg:{name}" if is_frame(elem) else name


def has_structure(elem: ElementTree.Element) -> bool:
    """``dg:structure`` or a bare ``structure`` (gold DGML and flat-layout output)."""
    return any(local_name(key) == "structure" for key in elem.attrib)


def walk_semantic(
    root: ElementTree.Element,
) -> Iterator[tuple[ElementTree.Element, tuple[str, ...]]]:
    """Every semantic element with its semantic ancestor names, outermost first."""
    stack: list[tuple[ElementTree.Element, tuple[str, ...]]] = [(root, ())]
    while stack:
        elem, ancestors = stack.pop()
        name = local_name(elem.tag)
        if name is None:
            continue
        frame = is_frame(elem)
        if not frame:
            yield elem, ancestors
        child_ancestors = ancestors if frame else (*ancestors, name)
        for child in reversed(list(elem)):
            stack.append((child, child_ancestors))


def parse_origin(value: str) -> list[tuple[int, int, int, int, int]]:
    """``"1 300 527 2023 1194; 2 ..."`` -> ``[(page, x1, y1, x2, y2), ...]``; malformed spans
    are skipped."""
    spans: list[tuple[int, int, int, int, int]] = []
    for part in value.split(";"):
        bits = part.split()
        if len(bits) != 5:
            continue
        try:
            page, x1, y1, x2, y2 = (int(float(b)) for b in bits)
        except ValueError:
            continue
        spans.append((page, x1, y1, x2, y2))
    return spans
