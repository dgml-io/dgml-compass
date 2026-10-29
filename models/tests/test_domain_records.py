import pytest
from pydantic import ValidationError

from model_compass.domain import AXIS_KEYS, DocsetRef, ModelSlot
from model_compass.records import MetricRecord

from .helpers import GOLDEN


def test_axis_vocabulary_is_closed_and_complete():
    assert {s.value for s in ModelSlot} <= AXIS_KEYS
    assert "generation.thinking" in AXIS_KEYS
    assert "generation.labelmodel" not in AXIS_KEYS


def test_docset_ref_requires_a_qualified_reference():
    assert str(DocsetRef.parse("z4ervk9ic0oo/hcqfkilviuq3")) == "z4ervk9ic0oo/hcqfkilviuq3"
    with pytest.raises(ValueError):
        DocsetRef.parse("hcqfkilviuq3")
    with pytest.raises(ValidationError):
        DocsetRef(org=" ", docset_id="x")


def test_real_records_round_trip_byte_for_byte():
    """Real lines from a run's metrics/*.jsonl, one per family."""
    lines = (GOLDEN / "metric_records.jsonl").read_text().splitlines()
    assert len(lines) >= 4
    for line in lines:
        assert MetricRecord.model_validate_json(line).model_dump_json() == line


def test_absent_is_not_zero():
    record = MetricRecord(
        run_id="r",
        cell_id="c",
        org="o",
        docset="d",
        family="extraction",
        values={"a": 0.0, "b": 1.0},
        absent=("b",),
    )
    assert record.get("a") == 0.0
    assert record.get("b") is None
    assert record.get("missing") is None
