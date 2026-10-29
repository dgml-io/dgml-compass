"""Read the corpus (``corpus_root``) into typed objects. The only module that knows its layout:

    <root>/<org>.files_mapping.json           document inventory (name, id, docsetId)
    <root>/<org>/<docset_id>/*.pdf|*.docx     source documents
    <root>/<org>/<docset_id>/<stem>.dgml.xml  gold DGML beside a document (optional)
    <root>/<org>/<docset_id>/<docset>_<org>.{ref,ref.type,complex_ref}.json   gold refs

Symlinks are never followed (one pointing at the corpus root would recurse), documents
resolve by ``(docset_id, name)``, and a flawed corpus is reported, not raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from model_compass.corpus.check import Collector, audit, audit_text_layers
from model_compass.corpus.models import (
    Corpus,
    Docset,
    Document,
    IntegrityReport,
    MappingRecord,
    Org,
)
from model_compass.corpus.refs import (
    REF_SUFFIXES,
    ComplexEntry,
    ComplexInstance,
    ComplexRef,
    ComplexTypeSpec,
    ComplexValidation,
    FlatRef,
    InstanceState,
    RefValue,
    SpecSource,
    TypedEntry,
    TypedRef,
    ref_filename,
)
from model_compass.corpus.sampling import SamplingMode, fixed_selection
from model_compass.corpus.selector import SOURCE_SUFFIXES
from model_compass.corpus.shapes import ShapeMap, load_shape_map
from model_compass.errors import ConfigError, CorpusError

if TYPE_CHECKING:
    from model_compass.config import Settings
    from model_compass.corpus.selector import CorpusSelector
    from model_compass.experiments.spec import ExperimentSpec

SKIP_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        "NO_REF",
        "Schemas",
        "field_name_check",
        ".render_cache",
        ".git",
        ".venv",
        "__pycache__",
        ".idea",
    }
)
XML_SUFFIX: Final[str] = ".dgml.xml"
MAPPING_SUFFIX: Final[str] = ".files_mapping.json"


def _read_json(path: Path, out: Collector, **where: Any) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out.error("unreadable_json", f"{path}: {exc}", **where)
        return None


def _values(raw: Any) -> tuple[RefValue, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    return tuple(RefValue.parse(item if isinstance(item, str) else str(item)) for item in raw)


def _flat(raw: dict[str, Any], docset_id: str, org: str) -> FlatRef:
    return FlatRef(
        docset_id=docset_id, org=org, entries={str(k): _values(v) for k, v in raw.items()}
    )


def _typed(raw: dict[str, Any], docset_id: str, org: str) -> TypedRef:
    entries = {
        str(key): TypedEntry(type=str(body.get("type", "")), values=_values(body.get("values")))
        for key, body in raw.items()
        if isinstance(body, dict)
    }
    return TypedRef(docset_id=docset_id, org=org, entries=entries)


def _members(raw: Any) -> dict[str, str | tuple[str, ...] | None]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): None
        if value is None
        else tuple(str(v) for v in value)
        if isinstance(value, list)
        else str(value)
        for name, value in raw.items()
    }


def _complex_entries(instances: Any) -> tuple[ComplexEntry, ...]:
    """``[]`` is verified absence, ``null`` is unverified; keep them apart."""
    if not isinstance(instances, dict):
        return ()
    entries: list[ComplexEntry] = []
    for file_id, by_type in sorted(instances.items()):
        if not isinstance(by_type, dict):
            continue
        for type_name, value in sorted(by_type.items()):
            items: tuple[ComplexInstance, ...] = ()
            if value is None:
                state = InstanceState.UNVERIFIED
            elif isinstance(value, list) and not value:
                state = InstanceState.ABSENT
            else:
                state = InstanceState.VERIFIED
                raw_items = value if isinstance(value, list) else [value]
                items = tuple(ComplexInstance(members=_members(item)) for item in raw_items)
            entries.append(
                ComplexEntry(
                    file_id=str(file_id), type_name=str(type_name), state=state, instances=items
                )
            )
    return tuple(entries)


def _complex(
    raw: dict[str, Any], docset_id: str, org: str, path: Path, out: Collector
) -> ComplexRef:
    types: dict[str, ComplexTypeSpec] = {}
    for name, spec in (raw.get("types") or {}).items():
        if not isinstance(spec, dict):
            continue
        try:
            types[str(name)] = ComplexTypeSpec(
                name=str(name),
                scope=spec.get("scope", "group"),
                members=tuple(str(m) for m in spec.get("members") or ()),
                optional=tuple(str(m) for m in spec.get("optional") or ()),
            )
        except ValueError as exc:
            out.error(
                "unreadable_json", f"{path}: type {name}: {exc}", org=org, docset_id=docset_id
            )
    validation = {
        str(name): ComplexValidation.model_validate(body)
        for name, body in (raw.get("validation") or {}).items()
        if isinstance(body, dict)
    }
    try:
        source = SpecSource(raw.get("spec_source", "curated"))
    except ValueError:
        source = SpecSource.CURATED
    return ComplexRef(
        docset_id=docset_id,
        org=org,
        derived_from=str(raw.get("derived_from", "")),
        spec_source=source,
        note=str(raw.get("note", "")),
        reference_xml=raw.get("reference_xml") and str(raw["reference_xml"]),
        types=types,
        entries=_complex_entries(raw.get("instances")),
        validation=validation,
    )


def _load_docset(
    path: Path,
    root: Path,
    org: str,
    index: dict[tuple[str, str], str],
    shapes: ShapeMap,
    out: Collector,
) -> Docset:
    docset_id = path.name
    where = {"org": org, "docset_id": docset_id}
    documents: list[Document] = []
    xml_files: list[str] = []
    for item in sorted(path.iterdir()):
        if item.is_symlink() or not item.is_file():
            continue
        if item.name.endswith(XML_SUFFIX):
            xml_files.append(item.relative_to(root).as_posix())
        elif item.suffix.lower() in SOURCE_SUFFIXES:
            xml = path / f"{item.stem}{XML_SUFFIX}"
            documents.append(
                Document(
                    name=item.name,
                    path=item.relative_to(root).as_posix(),
                    org=org,
                    docset_id=docset_id,
                    file_id=index.get((docset_id, item.name)),
                    size_bytes=item.stat().st_size,
                    xml_path=xml.relative_to(root).as_posix() if xml.is_file() else None,
                )
            )

    def ref(suffix: str) -> tuple[Path, dict[str, Any] | None]:
        file = path / ref_filename(docset_id, org, suffix)
        raw = _read_json(file, out, **where) if file.is_file() else None
        return file, raw if isinstance(raw, dict) else None

    display = None
    if (name_file := path / "docset_name.json").is_file():
        raw = _read_json(name_file, out, **where)
        if isinstance(raw, dict):
            display = str(raw.get(docset_id) or next(iter(raw.values()), "")) or None
    (_, flat), (_, typed), (cplx_path, cplx) = (ref(suffix) for suffix in REF_SUFFIXES)
    shape = shapes.try_get(docset_id)
    return Docset(
        docset_id=docset_id,
        org=org,
        display_name=display or (shape.display_name if shape else None),
        path=path.relative_to(root).as_posix(),
        shape=shape.shape if shape else None,
        shape_basis=shape.basis if shape else None,
        documents=tuple(documents),
        xml_files=tuple(xml_files),
        flat_ref=_flat(flat, docset_id, org) if flat is not None else None,
        typed_ref=_typed(typed, docset_id, org) if typed is not None else None,
        complex_ref=(_complex(cplx, docset_id, org, cplx_path, out) if cplx is not None else None),
    )


def _selected(docset: Docset, selector: CorpusSelector) -> bool:
    # Matching is on the docset id; the org was already narrowed by `selector.org_ids`.
    chooser = selector.docsets
    if docset.docset_id in {item.rsplit("/", 1)[-1] for item in chooser.exclude}:
        return False
    if selector.shapes and docset.shape not in selector.shapes:
        return False
    if chooser.all_with_refs:
        return docset.has_gold
    return docset.docset_id in {item.rsplit("/", 1)[-1] for item in chooser.include}


def _narrow(docset: Docset, selector: CorpusSelector) -> Docset:
    """Apply ``suffixes``, then (fixed sampling only) ``max_files_per_docset``. Under random
    sampling every document is kept: each draw picks its own from the whole docset."""
    if not set(selector.suffixes) >= SOURCE_SUFFIXES:
        kept = tuple(d for d in docset.documents if d.suffix in selector.suffixes)
        docset = docset.model_copy(update={"documents": kept})
    if selector.sampling is SamplingMode.RANDOM:
        return docset
    return fixed_selection(docset, selector.max_files_per_docset)


def load_corpus(
    root: Path | str,
    selector: CorpusSelector,
    *,
    shapes: ShapeMap | None = None,
    check_text_layer: bool = False,
) -> tuple[Corpus, IntegrityReport]:
    """The selected slice of the corpus, plus everything odd about it."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise CorpusError(f"corpus root is not a directory: {base}", code="corpus_missing")
    out = Collector()
    shape_map = shapes if shapes is not None else load_shape_map()
    wanted = selector.org_ids
    orgs: list[Org] = []
    for mapping_path in sorted(base.glob(f"*{MAPPING_SUFFIX}")):
        org_id = mapping_path.name[: -len(MAPPING_SUFFIX)]
        org_dir = base / org_id
        if (wanted and org_id not in wanted) or org_dir.is_symlink() or not org_dir.is_dir():
            continue
        raw = _read_json(mapping_path, out, org=org_id)
        records: list[MappingRecord] = []
        if not isinstance(raw, list):
            out.error(
                "mapping_missing", f"{mapping_path} is not a list of file records", org=org_id
            )
        else:
            for item in raw:
                try:
                    records.append(MappingRecord.from_raw(item))
                except (KeyError, TypeError, ValueError) as exc:
                    out.error(
                        "unreadable_json", f"{mapping_path}: bad record {item!r}: {exc}", org=org_id
                    )
        index = {(r.docset_id, r.name): r.file_id for r in records}
        docsets = []
        for child in sorted(org_dir.iterdir()):
            if child.is_symlink() or not child.is_dir() or child.name in SKIP_DIRECTORIES:
                continue
            if not shape_map.is_docset(child.name):
                continue
            docset = _load_docset(child, base, org_id, index, shape_map, out)
            if _selected(docset, selector):
                docsets.append(_narrow(docset, selector))
        orgs.append(Org(org_id=org_id, docsets=tuple(docsets), mapping=tuple(records)))
    corpus = Corpus(root=str(base), orgs=tuple(orgs))
    audit(corpus, out)
    if check_text_layer:
        audit_text_layers(corpus, base, out)
    return corpus, out.report(base)


def load_checked_corpus(spec: ExperimentSpec, settings: Settings) -> Corpus:
    """The spec's slice of the corpus; error-level integrity findings refuse to spend money."""
    corpus, report = load_corpus(settings.require("corpus_root"), spec.corpus)
    if errors := report.errors:
        raise ConfigError(
            f"the corpus has {len(errors)} error-class finding(s); run `dgc corpus check` and "
            "fix them before spending money",
            code="corpus_invalid",
            findings=[finding.code for finding in errors],
        )
    return corpus

