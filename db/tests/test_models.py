"""Tests for the Incident model's table/index definition."""

from db.models import Incident


def test_incident_tablename() -> None:
    assert Incident.__tablename__ == "incidents"


def test_incident_columns() -> None:
    columns = {c.name for c in Incident.__table__.columns}
    assert columns == {"id", "fingerprint", "alertname", "labels", "status", "created_at"}


def test_incident_has_partial_unique_index_on_fingerprint() -> None:
    indexes = Incident.__table__.indexes  # type: ignore[attr-defined]
    fingerprint_indexes = [ix for ix in indexes if "fingerprint" in [c.name for c in ix.columns]]
    assert len(fingerprint_indexes) == 1
    index = fingerprint_indexes[0]
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None
