"""Which documents a draw sees (DECISIONS 0017).

- ``fixed``: the first ``max_files_per_docset`` documents, gold-bearing first, then by name.
  Every draw sees the same files, so the spread between draws is generation noise.
- ``random``: each draw takes its own seeded sample from the whole docset, in name order.
  The generator is seeded with a string (SHA-512 inside ``random``, independent of
  ``PYTHONHASHSEED``) built from the seed, the docset and the 1-based draw number, so any
  harness using the same string picks the same documents. A draw whose set repeats an earlier
  draw's is re-drawn from its own generator.
"""

from __future__ import annotations

import random
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from model_compass.errors import ConfigError, EngineError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from model_compass.corpus.models import Corpus, Docset, Document
    from model_compass.corpus.selector import CorpusSelector
    from model_compass.experiments.cells import Cell
    from model_compass.experiments.spec import ExperimentSpec

SAMPLE_SEED_NAMESPACE: Final[str] = "dgml.sample.v1"
MAX_REDRAWS: Final[int] = 64


class SamplingMode(StrEnum):
    FIXED = "fixed"
    RANDOM = "random"


def _by_name(document: Document) -> tuple[str, str]:
    return (document.name, document.file_id or "")


def fixed_selection(docset: Docset, maximum: int) -> Docset:
    if len(docset.documents) <= maximum:
        return docset
    gold = docset.flat_ref.file_ids if docset.flat_ref else frozenset()
    ordered = sorted(docset.documents, key=lambda d: (d.file_id not in gold, d.name))
    return docset.model_copy(update={"documents": tuple(ordered[:maximum])})


def sample_seed(seed: int, org: str, docset_id: str, draw_index: int) -> str:
    return f"{SAMPLE_SEED_NAMESPACE}:{seed}:{org}/{docset_id}:{draw_index + 1}"


def _sample_sets(
    population: Sequence[Document], maximum: int, *, seed: int, org: str, docset_id: str, upto: int
) -> list[tuple[Document, ...]]:
    """Samples of draws ``0..upto``, each distinct from those before it."""
    taken: list[tuple[Document, ...]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for index in range(upto + 1):
        generator = random.Random(sample_seed(seed, org, docset_id, index))
        for _ in range(MAX_REDRAWS):
            chosen = tuple(sorted(generator.sample(population, k=maximum), key=_by_name))
            key = tuple(_by_name(doc) for doc in chosen)
            if key not in seen:
                break
        else:  # pragma: no cover - needs more draws than distinct subsets
            raise ConfigError(
                f"{org}/{docset_id}: no unused document set for draw {index}",
                code="sampling_exhausted",
            )
        seen.add(key)
        taken.append(chosen)
    return taken


def random_selection(docset: Docset, maximum: int, *, seed: int, draw_index: int) -> Docset:
    if maximum < 1:
        raise ConfigError(
            f"a draw must see at least one document, not {maximum}", code="sampling_invalid"
        )
    population = sorted(docset.documents, key=_by_name)
    if len(population) <= maximum:
        return docset.model_copy(update={"documents": tuple(population)})
    samples = _sample_sets(
        population, maximum, seed=seed, org=docset.org, docset_id=docset.docset_id, upto=draw_index
    )
    return docset.model_copy(update={"documents": samples[draw_index]})


def select_for_draw(
    docset: Docset, selector: CorpusSelector, *, draw_index: int, seed: int | None
) -> Docset:
    if selector.sampling is SamplingMode.FIXED:
        return fixed_selection(docset, selector.max_files_per_docset)
    if seed is None:
        raise ConfigError("random document sampling needs a `seed`", code="sampling_needs_seed")
    return random_selection(docset, selector.max_files_per_docset, seed=seed, draw_index=draw_index)


def documents_per_draw(docset: Docset, selector: CorpusSelector) -> int:
    return min(len(docset.documents), selector.max_files_per_docset)


def draw_corpus(corpus: Corpus, cell: Cell, spec: ExperimentSpec, draw_index: int) -> Corpus:
    """The cell's docset only (DECISIONS 0015), narrowed to this draw's documents
    (DECISIONS 0017)."""
    mine = corpus.for_ref(cell.ref)
    if not mine.docsets:
        raise EngineError(
            f"cell {cell.cell_id} is about {cell.ref}, which is not in the loaded corpus; "
            "refusing to build a workspace that would generate the wrong documents",
            code="cell_docset_absent",
        )
    orgs = tuple(
        org.model_copy(
            update={
                "docsets": tuple(
                    select_for_draw(d, spec.corpus, draw_index=draw_index, seed=spec.seed)
                    for d in org.docsets
                )
            }
        )
        for org in mine.orgs
    )
    return mine.model_copy(update={"orgs": orgs})

