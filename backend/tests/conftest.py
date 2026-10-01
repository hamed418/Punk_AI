"""
tests/conftest.py
─────────────────
Pin deployment switches that would otherwise let a developer's ``.env`` change
what the tests mean.

``META_PUBLISH_ACTIVATE`` is the one that matters: it is set to ``false`` on any
environment where publishing must never go live (demo MAID audiences, staging),
and with it off the publish path skips activation entirely — so three activation
tests silently passed-by-not-running against a real regression. Tests exercise
the real path; the one test that covers the switch turns it off itself.

``UNACAST_ID_SOURCE`` defaults to ``"areas_devices"`` in prod right now (see
app/graph/unacast_devices.py's module docstring — TEMPORARY, while the
observations entitlement returns registration IDs instead of advertising
IDs). It controls ONLY the silent ID swap at Meta-upload time
(executors/media.py._load_maids) — every stat, filter and map dot is always
built from real observations, unaffected by this flag. Pinned to
``"observations"`` here so existing publish tests keep uploading the plain
filtered MAID list unless they explicitly opt into the swap; only
tests/test_unacast_devices.py and the publish-substitution tests in
tests/test_meta_maid_upload.py set it back to ``"areas_devices"``.
"""
from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _publish_activation_on(monkeypatch):
    monkeypatch.setattr(settings, "META_PUBLISH_ACTIVATE", True)


@pytest.fixture(autouse=True)
def _maid_backend_is_observations_by_default(monkeypatch):
    monkeypatch.setattr(settings, "UNACAST_ID_SOURCE", "observations", raising=False)


@pytest.fixture(autouse=True)
def _reset_narrator_buffers():
    """Beats, history and the change ledger are process-local and keyed on the first
    HumanMessage id, falling back to ONE shared bucket when a test's state has no
    messages. Without this a `heard` entry recorded by one test surfaces as
    `heard_not_applied` in whichever test drains next."""
    from app.graph.narrator import beats

    beats.clear()
    yield
    beats.clear()
