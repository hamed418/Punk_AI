"""``maid_store.purge_maid_extraction`` — clearing raw MAID identifiers from a
stored extraction once they've served their purpose (a successful publish, or
the abandoned-row sweep). Everything but ``maids``/``observations`` survives.
"""
from unittest.mock import patch

import pytest

from app.services import maid_store


class _Row:
    def __init__(self, *, maids=None, observations=None, purged_at=None,
                 maid_count=500, pois=None, center=None):
        self.maids = maids if maids is not None else ["m1", "m2"]
        self.observations = observations if observations is not None else [{"maid": "m1"}]
        self.purged_at = purged_at
        self.maid_count = maid_count
        self.pois = pois if pois is not None else [{"name": "A"}]
        self.center = center if center is not None else {"lat": 1.0}
        self.search_radius_km = 0.06
        self.lookback_days = 30
        self.event_date_ranges = []
        self.audience_filter = None
        self.filtered_maid_count = None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row = row
        self.committed = False

    async def execute(self, _stmt):
        return _Result(self.row)

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_purge_clears_maids_and_observations_only():
    row = _Row()
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(row)):
        ok = await maid_store.purge_maid_extraction("id-1")

    assert ok is True
    assert row.maids == []
    assert row.observations == []
    assert row.purged_at is not None
    # Everything else on the row is untouched — reporting and template reuse
    # need it.
    assert row.maid_count == 500
    assert row.pois == [{"name": "A"}]
    assert row.center == {"lat": 1.0}


@pytest.mark.asyncio
async def test_purge_is_idempotent():
    """A row already purged is left alone, not double-stamped."""
    from datetime import datetime, timezone

    first_purge = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = _Row(maids=[], observations=[], purged_at=first_purge)
    db = _Db(row)
    with patch.object(maid_store, "AsyncSessionLocal", return_value=db):
        ok = await maid_store.purge_maid_extraction("id-1")

    assert ok is True
    assert row.purged_at == first_purge  # unchanged, not re-stamped
    assert db.committed is False  # nothing to write


@pytest.mark.asyncio
async def test_purge_of_a_missing_row_returns_false():
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(None)):
        ok = await maid_store.purge_maid_extraction("does-not-exist")
    assert ok is False


@pytest.mark.asyncio
async def test_fetch_maid_extraction_reports_purged_at():
    """Callers that only check maid_count need purged_at to tell a live
    extraction from a purged one with a real historical count."""
    from datetime import datetime, timezone

    purged = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = _Row(maids=[], observations=[], purged_at=purged)
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(row)):
        out = await maid_store.fetch_maid_extraction("id-1")

    assert out["purged_at"] == purged
    assert out["maid_count"] == 500  # historical count survives
    assert out["maids"] == []


@pytest.mark.asyncio
async def test_compute_audience_set_op_refuses_a_purged_extraction():
    """Computing a set op against an empty observations superset would
    silently report a 0-person result instead of an honest error."""
    from datetime import datetime, timezone

    row = _Row(maids=[], observations=[], purged_at=datetime.now(timezone.utc))
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(row)):
        out = await maid_store.compute_audience_set_op("id-1", ["category:gym"], "union")

    assert "error" in out
    assert "already published" in out["error"] or "cleared" in out["error"]
