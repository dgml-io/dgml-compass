"""Tree edit distance between gold and predicted DGML (docs/METRICS.md §4).

Zhang-Shasha over the element tree (``dg:`` frames included as ``dg:<name>``). Insert/delete
cost 1; rename costs 1 when names differ, and when they match 0 (label variant) or the
word-level distance of the elements' own text (``teds``, as TEDS does for table cells).
Variants, each ``1 - TED / max(|gold|, |pred|)``: ``teds`` (names + text), ``teds_struct``
(names), ``teds_shape`` (renames free). Operations prediction -> gold come from the
``teds_struct`` alignment, fewest renames among optimal scripts.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final, Literal

from model_compass.metrics.dgml_xml import local_name, qualified_name
from model_compass.metrics.text import WORD_RE

if TYPE_CHECKING:
    from xml.etree import ElementTree

MAX_TED_NODES: Final[int] = 2500
"""Elements per side above which TED is skipped (it is quadratic in tree size)."""
TED_METRICS: Final[tuple[str, ...]] = (
    "teds",
    "teds_struct",
    "teds_shape",
    "tree_ins",
    "tree_del",
    "tree_ren",
    "tree_edit_rate",
)
TedMode = Literal["text", "label", "shape"]
_REN_BITS: Final[int] = 1 << 20
"""Label-variant cost encoding: ``cost * _REN_BITS + renames``."""


class PostorderTree:
    __slots__ = ("keyroots", "labels", "lmd", "texts")

    def __init__(self, labels: list[str], texts: list[tuple[str, ...]], lmd: list[int]) -> None:
        self.labels, self.texts, self.lmd = labels, texts, lmd
        last: dict[int, int] = {}
        for index, leftmost in enumerate(lmd):
            last[leftmost] = index
        self.keyroots = sorted(last.values())

    def __len__(self) -> int:
        return len(self.labels)


def postorder(root: ElementTree.Element) -> PostorderTree:
    """Postorder labels, own-text tokens and leftmost-leaf indices; iterative (deep trees)."""
    labels: list[str] = []
    texts: list[tuple[str, ...]] = []
    lmd: list[int] = []
    stack: list[tuple[ElementTree.Element, list[ElementTree.Element], int, int]] = []

    def push(elem: ElementTree.Element) -> None:
        stack.append((elem, [c for c in elem if local_name(c.tag) is not None], 0, -1))

    push(root)
    child_leftmost = -1
    while stack:
        elem, kids, pos, first = stack[-1]
        if child_leftmost >= 0 and first < 0:
            first = child_leftmost
        child_leftmost = -1
        if pos < len(kids):
            stack[-1] = (elem, kids, pos + 1, first)
            push(kids[pos])
            continue
        stack.pop()
        index = len(labels)
        own = (elem.text or "") + "".join(c.tail or "" for c in elem)
        labels.append(qualified_name(elem) or "?")
        texts.append(tuple(WORD_RE.findall(own.lower())))
        lmd.append(index if first < 0 else first)
        child_leftmost = lmd[index]
    return PostorderTree(labels, texts, lmd)


def zhang_shasha(source: PostorderTree, target: PostorderTree, *, mode: TedMode) -> float:
    """Edit distance; ``mode`` is ``text``, ``label`` (integer-encoded) or ``shape``."""
    la, lb, ta, tb = source.labels, target.labels, source.texts, target.texts
    lma, lmb = source.lmd, target.lmd
    n, m = len(la), len(lb)
    unit = _REN_BITS if mode == "label" else 1
    zero: float = 0 if mode == "label" else 0.0
    cache: dict[tuple[int, int], float] = {}

    def rename(i: int, j: int) -> float:
        if mode == "shape":
            return 0.0
        if la[i] != lb[j]:
            return _REN_BITS + 1 if mode == "label" else 1.0
        if mode == "label" or ta[i] == tb[j]:
            return zero
        value = cache.get((i, j))
        if value is None:
            value = 1.0 - SequenceMatcher(None, ta[i], tb[j], autojunk=False).ratio()
            cache[(i, j)] = value
        return value

    td: list[list[float]] = [[zero] * m for _ in range(n)]
    for i0 in source.keyroots:
        li = lma[i0]
        ni = i0 - li + 2
        for j0 in target.keyroots:
            lj = lmb[j0]
            nj = j0 - lj + 2
            fd: list[list[float]] = [[zero] * nj for _ in range(ni)]
            for x in range(1, ni):
                fd[x][0] = fd[x - 1][0] + unit
            row0 = fd[0]
            for y in range(1, nj):
                row0[y] = row0[y - 1] + unit
            for x in range(1, ni):
                i = li + x - 1
                lmi = lma[i]
                prev, cur, tdi = fd[x - 1], fd[x], td[i]
                if lmi == li:
                    prev_base = fd[0]
                    for y in range(1, nj):
                        j = lj + y - 1
                        a, b = prev[y] + unit, cur[y - 1] + unit
                        v = a if a < b else b
                        if lmb[j] == lj:
                            c = prev[y - 1] + rename(i, j)
                            if c < v:
                                v = c
                            cur[y] = v
                            tdi[j] = v
                        else:
                            c = prev_base[lmb[j] - lj] + tdi[j]
                            cur[y] = c if c < v else v
                else:
                    base = fd[lmi - li]
                    for y in range(1, nj):
                        j = lj + y - 1
                        a, b = prev[y] + unit, cur[y - 1] + unit
                        v = a if a < b else b
                        c = base[lmb[j] - lj] + tdi[j]
                        cur[y] = c if c < v else v
    return td[n - 1][m - 1]


def tree_edit_metrics(
    gold: ElementTree.Element, pred: ElementTree.Element, *, max_nodes: int = MAX_TED_NODES
) -> dict[str, float] | None:
    """The TED metrics for one pair, or ``None`` when a side exceeds ``max_nodes``."""
    g, p = postorder(gold), postorder(pred)
    if len(g) > max_nodes or len(p) > max_nodes:
        return None
    size = max(len(g), len(p))
    cost, ren = divmod(int(zhang_shasha(p, g, mode="label")), _REN_BITS)
    spare, diff = cost - ren, len(p) - len(g)  # del + ins = spare ; del - ins = diff
    return {
        "teds": 1.0 - zhang_shasha(p, g, mode="text") / size,
        "teds_struct": 1.0 - cost / size,
        "teds_shape": 1.0 - zhang_shasha(p, g, mode="shape") / size,
        "tree_ins": float((spare - diff) // 2),
        "tree_del": float((spare + diff) // 2),
        "tree_ren": float(ren),
        "tree_edit_rate": cost / len(g),
    }
