"""Reading a generated dgml workspace once, for the families that measure the output itself::

    <workspace>/usage.jsonl                                (only under --debug)
    <workspace>/config.toml                                (config.json in older workspaces)
    <workspace>/files/<file_id>/page_text/page_N.json      OCR words
    <workspace>/docsets/<docset_id>/files/<file_id>/<stem>.dgml.xml

An unparseable document is counted, never skipped silently.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from model_compass.engine.dgml_cli import CONFIG_FILENAME
from model_compass.metrics.dgml_xml import UnparseableDocument, parse_dgml_bytes

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path
    from xml.etree import ElementTree


@dataclass(frozen=True)
class PageWords:
    """One ``page_N.json``: OCR words with boxes, and the page extent."""

    words: tuple[tuple[str, float, float, float, float], ...] = ()
    width: int = 0
    height: int = 0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PageWords:
        words: list[tuple[str, float, float, float, float]] = []
        for word in data.get("words") or []:
            location = word.get("l") or []
            if len(location) != 4:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in location)
            except (TypeError, ValueError):
                continue
            words.append((str(word.get("t") or ""), x1, y1, x2, y2))
        return cls(
            words=tuple(words),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
        )


@dataclass
class DocsetWorkspace:
    docset_id: str
    roots: list[ElementTree.Element] = field(default_factory=list)
    dgml_texts: list[str] = field(default_factory=list)
    page_words: dict[str, dict[int, PageWords]] = field(default_factory=dict)
    file_ids: list[str] = field(default_factory=list)
    documents_expected: int = 0
    unparseable: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def documents(self) -> int:
        return len(self.roots)

    @property
    def has_page_text(self) -> bool:
        return any(self.page_words.values())

    def page_word_lengths(self) -> Iterator[Sequence[int]]:
        for pages in self.page_words.values():
            for page in pages.values():
                yield [len(word) for word, *_ in page.words]


def read_page_words(page_text_dir: Path) -> dict[int, PageWords]:
    """A malformed page is missing evidence, not a page without words: it is left out."""
    pages: dict[int, PageWords] = {}
    if not page_text_dir.is_dir():
        return pages
    for path in sorted(page_text_dir.glob("page_*.json")):
        try:
            number = int(path.stem.split("_", 1)[1])
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (IndexError, ValueError, OSError):
            continue
        if isinstance(data, dict):
            pages[number] = PageWords.from_json(data)
    return pages


def read_docset(workspace: Path, docset_id: str) -> DocsetWorkspace:
    out = DocsetWorkspace(docset_id=docset_id)
    docset_dir = workspace / "docsets" / docset_id
    if not docset_dir.is_dir():
        out.warnings.append("no_docset_directory")
        return out
    out.documents_expected = sum(1 for p in (docset_dir / "files").glob("*") if p.is_dir())
    # older workspaces put DGML flat in the docset directory
    xml_paths = sorted(docset_dir.glob("files/*/*.dgml.xml")) or sorted(
        docset_dir.glob("*.dgml.xml")
    )
    for path in xml_paths:
        file_id = path.parent.name
        try:
            data = path.read_bytes()
            root = parse_dgml_bytes(data, source=str(path))
        except (OSError, UnparseableDocument):
            out.unparseable.append(file_id)
            continue
        out.roots.append(root)
        out.dgml_texts.append(data.decode("utf-8", errors="replace"))
        out.file_ids.append(file_id)
        out.page_words[file_id] = read_page_words(workspace / "files" / file_id / "page_text")
    if out.unparseable:
        out.warnings.append(f"unparseable_documents:{len(out.unparseable)}")
    if not out.has_page_text:
        out.warnings.append("no_page_text")
    return out


def read_config_label_model(workspace: Path) -> tuple[str | None, list[str]]:
    """The configured ``generation.label_model``, for the label-model mismatch check: from
    ``config.toml``, or from the ``config.json`` (``//`` comments tolerated) that dgml wrote
    before it moved to TOML. A config without the key means dgml's machine default."""
    toml_path = workspace / CONFIG_FILENAME
    json_path = workspace / "config.json"
    try:
        if toml_path.is_file():
            parsed: Any = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        elif json_path.is_file():
            lines = json_path.read_text(encoding="utf-8").splitlines()
            parsed = json.loads("\n".join(ln for ln in lines if not ln.lstrip().startswith("//")))
        else:
            return None, ["no_config"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return None, ["config_unreadable"]
    if not isinstance(parsed, dict):
        return None, ["config_unreadable"]
    generation = parsed.get("generation")
    model = generation.get("label_model") if isinstance(generation, dict) else None
    return (str(model) if model else None), []
