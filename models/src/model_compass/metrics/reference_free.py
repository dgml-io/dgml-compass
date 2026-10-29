"""Quality without gold (docs/METRICS.md §2): tag consistency, grounding, structural health.

Runs on every docset, gold or not. ``empty_containers`` follows the structural-defects
definition (DECISIONS 0009); a single-document docset reports no consistency score rather than a
coerced 0 (DECISIONS 0008).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import cached_property
from itertools import combinations
from typing import TYPE_CHECKING, Final

from model_compass.metrics.dgml_xml import (
    ORIGIN_ATTR,
    has_structure,
    is_frame,
    local_name,
    parse_origin,
    walk_semantic,
)
from model_compass.metrics.outputs import PageWords

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from xml.etree import ElementTree

CAMEL_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")
"""Splits a PascalCase tag NAME (``EffectiveDate`` -> effective, date)."""
BAG_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
"""Bag-of-words tokens of lowercased document text."""

SYNONYM_JACCARD: Final[float] = 0.6
CO_OCCURRENCE_MAX: Final[float] = 0.5
"""Tags co-occurring in more than this share of their documents are distinct roles."""
CONTENT_COSINE_MIN: Final[float] = 0.6
CHAR_SIMILARITY_MIN: Final[float] = 0.92
"""Character path for OCR/typo variants; ExhibitA/ExhibitB (0.875) must stay out."""
MIN_CONTENT_TOKENS: Final[int] = 5
DEFECT_FLOOR: Final[float] = 400.0
"""Defects per 1k elements at which ``structural_score`` bottoms out (relative scale)."""
_OOB_TOLERANCE: Final[float] = 1.02

CONSISTENCY_METRICS: Final[tuple[str, ...]] = (
    "vocabulary_reuse_rate",
    "singleton_rate",
    "mean_pairwise_jaccard",
    "tag_inflation",
    "synonym_rate",
    "consistency_score",
)
GROUNDING_METRICS: Final[tuple[str, ...]] = (
    "grounded_leaf_rate",
    "origin_text_match",
    "out_of_bounds_rate",
    "degenerate_box_rate",
)
STRUCTURAL_METRICS: Final[tuple[str, ...]] = (
    "dual_role_tags",
    "dual_role_tags_attr",
    "empty_containers",
    "self_nesting",
    "self_nesting_direct",
    "defects_per_1k_elements",
    "structural_score",
)
ALL_REFERENCE_FREE_METRICS: Final[tuple[str, ...]] = (
    *CONSISTENCY_METRICS,
    *GROUNDING_METRICS,
    *STRUCTURAL_METRICS,
)


def tag_tokens(name: str) -> frozenset[str]:
    return frozenset(t.lower() for t in CAMEL_RE.findall(name) if t)


def _computable(obj: object, names: Sequence[str]) -> dict[str, float]:
    return {n: float(v) for n in names if (v := getattr(obj, n)) is not None}


# -- A. tag consistency ------------------------------------------------------------------


@dataclass(frozen=True)
class TagConsistency:
    documents: int = 0
    vocabulary: int = 0
    vocabulary_reuse_rate: float | None = None
    singleton_rate: float | None = None
    mean_pairwise_jaccard: float | None = None
    tag_inflation: float | None = None
    synonym_rate: float | None = None
    consistency_score: float | None = None
    synonym_examples: tuple[str, ...] = ()

    @property
    def values(self) -> dict[str, float]:
        return _computable(self, CONSISTENCY_METRICS)


@dataclass
class TagEvidence:
    """Usage evidence that decides a lexically proposed synonym pair."""

    doc_ids: dict[str, set[int]] = field(default_factory=dict)
    content: dict[str, Counter[str]] = field(default_factory=dict)

    def doc_overlap(self, a: str, b: str) -> float | None:
        sa, sb = self.doc_ids.get(a), self.doc_ids.get(b)
        if not sa or not sb:
            return None
        return len(sa & sb) / len(sa | sb)

    def content_cosine(self, a: str, b: str) -> float | None:
        """TF-IDF cosine of pooled subtree text; ``None`` (cannot judge) with too little text.
        IDF is ``log(1 + n/(1 + df))`` so it never goes negative."""
        ca, cb = self.content.get(a), self.content.get(b)
        if not ca or not cb:
            return None
        if sum(ca.values()) < MIN_CONTENT_TOKENS or sum(cb.values()) < MIN_CONTENT_TOKENS:
            return None
        n = max(len(self.content), 2)

        def weight(count: int, token: str) -> float:
            return (1 + math.log(count)) * math.log(1 + n / (1 + self._df[token]))

        va = {w: weight(v, w) for w, v in ca.items()}
        vb = {w: weight(v, w) for w, v in cb.items()}
        dot = sum(v * vb[w] for w, v in va.items() if w in vb)
        na = math.sqrt(sum(v * v for v in va.values()))
        nb = math.sqrt(sum(v * v for v in vb.values()))
        return dot / (na * nb) if na and nb else None

    @cached_property
    def _df(self) -> Counter[str]:
        df: Counter[str] = Counter()
        for counts in self.content.values():
            df.update(set(counts))
        return df


def lexical_similarity(a: str, b: str) -> float:
    """1.0 for a token subset, else token Jaccard; a very high character ratio also qualifies."""
    ta, tb = tag_tokens(a), tag_tokens(b)
    if not (ta or tb):
        return 0.0
    if ta <= tb or tb <= ta:
        return 1.0
    token_sim = len(ta & tb) / len(ta | tb)
    if token_sim >= SYNONYM_JACCARD:
        return token_sim
    char_sim = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return SYNONYM_JACCARD if char_sim >= CHAR_SIMILARITY_MIN else token_sim


def is_synonym_pair(a: str, b: str, evidence: TagEvidence | None = None) -> bool:
    """Lexical similarity proposes; a co-occurrence veto and a content gate decide."""
    if lexical_similarity(a, b) < SYNONYM_JACCARD:
        return False
    if evidence is None:
        return True
    overlap = evidence.doc_overlap(a, b)
    if overlap is not None and overlap > CO_OCCURRENCE_MAX:
        return False
    cosine = evidence.content_cosine(a, b)
    return not (cosine is not None and cosine < CONTENT_COSINE_MIN)


def synonym_clusters(names: Iterable[str], evidence: TagEvidence | None = None) -> list[list[str]]:
    """Complete-link clusters (single-link chains Date ~ EffectiveDate ~ TerminationDate);
    candidates only within shared-token buckets."""
    ordered = sorted(set(names))
    by_token: dict[str, list[str]] = defaultdict(list)
    for name in ordered:
        for token in tag_tokens(name):
            by_token[token].append(name)
    adjacency: dict[str, set[str]] = defaultdict(set)
    checked: set[tuple[str, str]] = set()
    for bucket in by_token.values():
        if len(bucket) < 2:
            continue
        for a, b in combinations(bucket, 2):
            key = (a, b) if a < b else (b, a)
            if key in checked:
                continue
            checked.add(key)
            if is_synonym_pair(a, b, evidence):
                adjacency[a].add(b)
                adjacency[b].add(a)
    groups: list[list[str]] = []
    for name in ordered:
        if not adjacency[name]:
            continue
        for group in groups:
            if all(member in adjacency[name] for member in group):
                group.append(name)
                break
        else:
            groups.append([name])
    return [sorted(g) for g in groups if len(g) > 1]


def tag_consistency(
    per_doc_tags: Sequence[frozenset[str]], content: Mapping[str, Counter[str]] | None = None
) -> TagConsistency:
    documents = len(per_doc_tags)
    if not per_doc_tags:
        return TagConsistency(documents=0)
    counts: Counter[str] = Counter()
    for tags in per_doc_tags:
        counts.update(tags)
    vocab = list(counts)
    if not vocab:
        return TagConsistency(documents=documents, vocabulary=0)
    reuse_rate = 100.0 * sum(1 for t in vocab if counts[t] >= 2) / len(vocab)

    jaccard: float | None = None
    inflation: float | None = None
    if documents >= 2:
        sims = [
            100.0 * len(a & b) / len(a | b) for a, b in combinations(per_doc_tags, 2) if (a | b)
        ]
        jaccard = sum(sims) / len(sims) if sims else 0.0
        seen: set[str] = set()
        for tags in per_doc_tags[:-1]:
            seen |= tags
        inflation = 100.0 * len(per_doc_tags[-1] - seen) / len(vocab)

    doc_ids: dict[str, set[int]] = defaultdict(set)
    for index, tags in enumerate(per_doc_tags):
        for tag in tags:
            doc_ids[tag].add(index)
    clusters = synonym_clusters(
        vocab, TagEvidence(doc_ids=dict(doc_ids), content=dict(content or {}))
    )
    synonym_rate = 100.0 * sum(len(c) - 1 for c in clusters) / len(vocab)

    score: float | None = None
    if jaccard is not None and inflation is not None:
        score = max(
            0.0,
            min(
                100.0,
                0.4 * reuse_rate
                + 0.3 * jaccard
                + 0.15 * (100.0 - inflation)
                + 0.15 * (100.0 - synonym_rate),
            ),
        )
    return TagConsistency(
        documents=documents,
        vocabulary=len(vocab),
        vocabulary_reuse_rate=reuse_rate,
        singleton_rate=100.0 - reuse_rate,
        mean_pairwise_jaccard=jaccard,
        tag_inflation=inflation,
        synonym_rate=synonym_rate,
        consistency_score=score,
        synonym_examples=tuple(
            " / ".join(c[:4]) for c in sorted(clusters, key=len, reverse=True)[:5]
        ),
    )


def document_tags(root: ElementTree.Element) -> frozenset[str]:
    return frozenset(name for elem, _ in walk_semantic(root) if (name := local_name(elem.tag)))


def pooled_content(root: ElementTree.Element, into: dict[str, Counter[str]]) -> None:
    """Each tag's pooled subtree tokens (``itertext``, so ``dg:``-wrapped values count)."""
    for elem, _ in walk_semantic(root):
        name = local_name(elem.tag)
        if name is not None:
            into.setdefault(name, Counter()).update(
                BAG_WORD_RE.findall(" ".join(elem.itertext()).lower())
            )


# -- B. grounding ------------------------------------------------------------------------


@dataclass(frozen=True)
class Grounding:
    text_leaves: int = 0
    grounded_leaves: int = 0
    boxes: int = 0
    out_of_bounds: int = 0
    degenerate: int = 0
    matches: tuple[float, ...] = ()

    @property
    def grounded_leaf_rate(self) -> float | None:
        return 100.0 * self.grounded_leaves / self.text_leaves if self.text_leaves else None

    @property
    def origin_text_match(self) -> float | None:
        return sum(self.matches) / len(self.matches) if self.matches else None

    @property
    def out_of_bounds_rate(self) -> float | None:
        return 100.0 * self.out_of_bounds / self.boxes if self.boxes else None

    @property
    def degenerate_box_rate(self) -> float | None:
        return 100.0 * self.degenerate / self.boxes if self.boxes else None


def grounding_quality(root: ElementTree.Element, pages: Mapping[int, PageWords]) -> Grounding:
    """Each text leaf's ``dg:origin`` against the OCR words whose CENTRE falls in its box."""
    text_leaves = grounded = boxes = out_of_bounds = degenerate = 0
    matches: list[float] = []
    for elem, _ in walk_semantic(root):
        text = (elem.text or "").strip()
        if any(not is_frame(c) and local_name(c.tag) for c in elem) or not text:
            continue
        text_leaves += 1
        origin = elem.get(ORIGIN_ATTR) or elem.get("origin")
        if not origin:
            continue
        spans = parse_origin(origin)
        if not spans:
            continue
        want = set(BAG_WORD_RE.findall(text.lower()))
        if not want:
            continue
        grounded += 1
        found: set[str] = set()
        for page_number, x1, y1, x2, y2 in spans:
            boxes += 1
            page = pages.get(page_number, PageWords())
            if x2 <= x1 or y2 <= y1:
                degenerate += 1
                continue
            if (
                page.width
                and page.height
                and (
                    x1 < 0
                    or y1 < 0
                    or x2 > page.width * _OOB_TOLERANCE
                    or y2 > page.height * _OOB_TOLERANCE
                )
            ):
                out_of_bounds += 1
            for word, wx1, wy1, wx2, wy2 in page.words:
                cx, cy = (wx1 + wx2) / 2, (wy1 + wy2) / 2
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    found |= set(BAG_WORD_RE.findall(word.lower()))
        matches.append(100.0 * len(want & found) / len(want))
    return Grounding(
        text_leaves=text_leaves,
        grounded_leaves=grounded,
        boxes=boxes,
        out_of_bounds=out_of_bounds,
        degenerate=degenerate,
        matches=tuple(matches),
    )


# -- C. structural health ----------------------------------------------------------------


@dataclass(frozen=True)
class Structural:
    elements: int = 0
    dual_role_tags: int = 0
    dual_role_names: tuple[str, ...] = ()
    dual_role_tags_attr: int = 0
    empty_containers: int = 0
    self_nesting: int = 0
    self_nesting_direct: int = 0

    @property
    def defects_per_1k_elements(self) -> float | None:
        if not self.elements:
            return None
        defects = self.dual_role_tags + self.empty_containers + self.self_nesting
        return 1000.0 * defects / self.elements

    @property
    def structural_score(self) -> float | None:
        rate = self.defects_per_1k_elements
        return None if rate is None else max(0.0, 100.0 * (1.0 - rate / DEFECT_FLOOR))

    @property
    def values(self) -> dict[str, float]:
        return _computable(self, STRUCTURAL_METRICS)


def structural_health(roots: Sequence[ElementTree.Element]) -> Structural:
    as_container: set[str] = set()
    as_leaf: set[str] = set()
    attr_container: set[str] = set()
    attr_leaf: set[str] = set()
    elements = empty_containers = self_nesting = self_nesting_direct = 0
    for root in roots:
        for elem, ancestors in walk_semantic(root):
            name = local_name(elem.tag)
            if name is None:
                continue
            elements += 1
            children = [c for c in elem if local_name(c.tag) is not None]
            semantic = [c for c in children if not is_frame(c)]
            text = bool((elem.text or "").strip())
            if semantic:
                as_container.add(name)
            elif text:
                as_leaf.add(name)
            if has_structure(elem):
                attr_container.add(name)
            elif text:
                attr_leaf.add(name)
            # `children` includes dg: wrappers: text one level down is still content
            # (DECISIONS 0009)
            if has_structure(elem) and not children and not text:
                empty_containers += 1
            if name in ancestors:
                self_nesting += 1
            if any(local_name(c.tag) == name for c in semantic):
                self_nesting_direct += 1
    dual = sorted(as_container & as_leaf)
    return Structural(
        elements=elements,
        dual_role_tags=len(dual),
        dual_role_names=tuple(dual),
        dual_role_tags_attr=len(attr_container & attr_leaf),
        empty_containers=empty_containers,
        self_nesting=self_nesting,
        self_nesting_direct=self_nesting_direct,
    )
