"""Flattening: a DGML document as a reading-order token stream carrying chunk metadata, and the
one token alignment (and the chunk alignment derived from it) that every tree metric reads."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from model_compass.metrics.dgml_xml import local_name, parse_origin, qualified_name
from model_compass.metrics.text import WORD_RE

if TYPE_CHECKING:
    from collections.abc import Sequence
    from xml.etree import ElementTree

Box = tuple[int, int, int, int, int]


def _attr(elem: ElementTree.Element, name: str) -> str | None:
    """Attribute by local name: namespaced (``dg:origin``) or bare (``origin``, as in gold)."""
    for key, value in elem.attrib.items():
        if local_name(key) == name:
            return value
    return None


@dataclass(frozen=True)
class Chunk:
    """One text-bearing element: the unit a side chose to emit as a whole."""

    norm: str
    n_tokens: int
    tag: str
    """The element's own name, ``dg:`` wrappers included."""
    depth: int
    parent: int
    anc: tuple[int, ...]
    """Element-index path, root..self."""
    path: tuple[str, ...]
    """Tag-name path, root..self."""
    struct_path: tuple[str, ...]
    """``structure`` attribute path, root..self (``-`` where absent)."""
    boxes: tuple[Box, ...]

    @property
    def sem_tag(self) -> str:
        """Nearest enclosing semantic (non-``dg:``) tag, self included."""
        for name in reversed(self.path):
            if not name.startswith("dg:"):
                return name
        return self.path[-1] if self.path else "?"


@dataclass
class FlatDoc:
    """A document as a reading-order token stream plus its chunk table."""

    chunks: list[Chunk] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    tok_chunk: list[int] = field(default_factory=list)
    n_elements: int = 0

    @property
    def empty(self) -> bool:
        return not self.chunks


def flatten(root: ElementTree.Element) -> FlatDoc:
    """Flatten a parsed DGML document.

    Text nodes are emitted in document order so the stream really is reading order, but every
    text node belonging to one element is folded into that element's single chunk: an element
    whose text is interrupted by a child is one unit, not two.
    """
    doc = FlatDoc()
    counter = 0
    open_chunks: dict[int, tuple[int, list[str]]] = {}

    def emit(owner: int, text: str, template: Chunk) -> None:
        toks = WORD_RE.findall(text.lower())
        if not toks:
            return
        if owner in open_chunks:
            index, acc = open_chunks[owner]
            acc.extend(toks)
        else:
            index = len(doc.chunks)
            doc.chunks.append(template)
            acc = list(toks)
            open_chunks[owner] = (index, acc)
        doc.tokens.extend(toks)
        doc.tok_chunk.extend([index] * len(toks))

    def walk(
        elem: ElementTree.Element,
        depth: int,
        parent: int,
        anc: tuple[int, ...],
        path: tuple[str, ...],
        spath: tuple[str, ...],
    ) -> None:
        nonlocal counter
        my_index = counter
        counter += 1
        name = qualified_name(elem) or "?"
        struct = _attr(elem, "structure") or ""
        origin = _attr(elem, "origin")
        template = Chunk(
            norm="",
            n_tokens=0,
            tag=name,
            depth=depth,
            parent=parent,
            anc=(*anc, my_index),
            path=(*path, name),
            struct_path=(*spath, struct or "-"),
            boxes=tuple(parse_origin(origin)) if origin else (),
        )
        emit(my_index, elem.text or "", template)
        for child in elem:
            if local_name(child.tag) is None:
                continue
            walk(
                child, depth + 1, my_index, (*anc, my_index), (*path, name), (*spath, struct or "-")
            )
            emit(my_index, child.tail or "", template)  # a tail is the PARENT's text

    walk(root, 0, -1, (), (), ())
    doc.n_elements = counter
    finished: list[Chunk] = list(doc.chunks)
    for index, acc in open_chunks.values():
        finished[index] = replace(finished[index], norm=" ".join(acc), n_tokens=len(acc))
    doc.chunks = finished
    return doc


def align_tokens(gold: FlatDoc, pred: FlatDoc) -> list[tuple[int, int]]:
    """Canonical token alignment: ``(index_in_gold, index_in_pred)`` pairs, in order."""
    pairs: list[tuple[int, int]] = []
    matcher = SequenceMatcher(None, gold.tokens, pred.tokens, autojunk=False)
    for block in matcher.get_matching_blocks():
        pairs.extend((block.a + k, block.b + k) for k in range(block.size))
    return pairs


def align_chunks(
    gold: FlatDoc, pred: FlatDoc, pairs: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Chunk alignment derived from the token alignment: each gold chunk is matched to the
    predicted chunk it shares the most aligned tokens with. Survives partial rewrites, which
    matching on exact normalised text does not."""
    votes: dict[int, Counter[int]] = defaultdict(Counter)
    for ig, ip in pairs:
        votes[gold.tok_chunk[ig]][pred.tok_chunk[ip]] += 1
    return [(cg, votes[cg].most_common(1)[0][0]) for cg in sorted(votes)]
