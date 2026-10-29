"""Generated DGML -> the ``{file_id: {label: [values]}}`` table extraction scores.

Definitions: docs/METRICS.md §1.

Its quirks are deliberate and kept -- changing any of them moves the extraction numbers:

- Path parts are Clark-notation tags and the ``dg:`` frame is NOT transparent here (unlike
  the structural families): extraction asks which text lives under which tag name.
- Every path suffix is a label: a value at ``A/B/C`` is offered as ``C``, ``B+C``, ``A+B+C``.
- A value with a ``structure="lim"`` child (list marker) is also offered without it, under a
  ``+nolim`` label.
- An element without own text whose children are all inline (no ``structure``) is a value
  with its whole subtree text.
- The level loop REPLACES a (file, label) entry at each level.
- A ``dg:extraction`` root child (grounded-extraction output) is split off first.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree

from model_compass.metrics.dgml_xml import has_structure, local_name

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

PATH_JOIN: Final[str] = "+"
NOLIM: Final[str] = "nolim"


@dataclass(frozen=True)
class LeafRecord:
    path: tuple[str, ...]
    text: str


@dataclass
class PredictionSet:
    by_file: dict[str, dict[str, list[str]]] = field(default_factory=dict)


def split_extraction(
    root: ElementTree.Element,
) -> tuple[ElementTree.Element, ElementTree.Element | None]:
    """``(generation view, values view or None)``; ``root`` is not modified."""
    extraction = [child for child in root if local_name(child.tag) == "extraction"]
    generation = ElementTree.Element(root.tag, dict(root.attrib))
    generation.text = root.text
    for child in root:
        if child not in extraction:
            generation.append(child)
    if not extraction:
        return generation, None
    values = ElementTree.Element(root.tag, dict(root.attrib))
    for wrapper in extraction:
        for child in wrapper:
            values.append(child)
    return generation, values


def _is_lim(elem: ElementTree.Element) -> bool:
    return any(local_name(k) == "structure" and str(v) == "lim" for k, v in elem.attrib.items())


def _own_text(elem: ElementTree.Element) -> bool:
    if elem.text and elem.text.strip():
        return True
    return any(child.tail and child.tail.strip() for child in elem)


def _subtree_text(elem: ElementTree.Element) -> str:
    return "".join(elem.itertext()).strip()


def _text_without_lims(elem: ElementTree.Element) -> str:
    parts = [elem.text or ""]
    for child in elem:
        if not _is_lim(child):
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return "".join(parts).strip()


def collect_leaf_paths(root: ElementTree.Element) -> tuple[list[LeafRecord], int]:
    """Text-bearing elements as ``(path, text)`` in document order, plus the maximum depth
    over all elements (it bounds the level loop)."""
    records: list[LeafRecord] = []
    max_depth = 0

    def emit(elem: ElementTree.Element, path: tuple[str, ...], text: str) -> None:
        nonlocal max_depth
        records.append(LeafRecord(path, text))
        stripped = _text_without_lims(elem)
        if stripped and stripped != text:
            records.append(LeafRecord((*path, NOLIM), stripped))
            max_depth = max(max_depth, len(path) + 1)

    def walk(elem: ElementTree.Element, path: tuple[str, ...]) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, len(path))
        if _own_text(elem):
            emit(elem, path, _subtree_text(elem))
        elif len(elem) and all(not has_structure(child) for child in elem):
            text = _subtree_text(elem)
            if text:
                emit(elem, path, text)
        for child in elem:
            walk(child, (*path, child.tag))

    for child in root:
        walk(child, (child.tag,))
    return records, max_depth


def construct_predictions(roots: Mapping[str, ElementTree.Element]) -> PredictionSet:
    """File ids sorted, records in document order: the matcher's tie-break is first-best, so
    insertion order is part of the metric."""
    file_ids = sorted(roots)
    records_by_file: dict[str, list[LeafRecord]] = {}
    max_depth = 0
    for file_id in file_ids:
        records, depth = collect_leaf_paths(roots[file_id])
        records_by_file[file_id] = records
        max_depth = max(max_depth, depth)

    result = PredictionSet()
    data: dict[tuple[str, str], list[str]] = {}
    for level in range(1, max_depth + 1):
        for file_id in file_ids:
            out: dict[str, list[str]] = defaultdict(list)
            for record in records_by_file[file_id]:
                label = PATH_JOIN.join(record.path[-level:])
                out[label].append(record.text)
            for label, values in out.items():
                data[(file_id, label)] = values  # replaced per level, not merged

    for (file_id, label), values in data.items():
        result.by_file.setdefault(file_id, {})[label] = values
    for file_id in file_ids:
        result.by_file.setdefault(file_id, {})
    return result


def predictions_for_documents(roots: Iterable[tuple[str, ElementTree.Element]]) -> PredictionSet:
    return construct_predictions({fid: split_extraction(root)[0] for fid, root in roots})
