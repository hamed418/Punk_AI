"""
tests/_geo_run_helper.py
─────────────────────────
Shared test driver for geo._execute_deterministic across every test module
that calls it directly (bypassing builder_act's own dispatch/retry loop).

_GeoStepPaused (see geo.py's docstring on it) ends the call the instant ANY
embedded confirm/disambiguation interrupt resolves — a run needing one no
longer completes in a single call, exactly like production's builder_act,
which catches it and re-dispatches geo_discover fresh next tick (see
builder_node.py's geo_discover branch). Direct-call tests need the same
retry-until-done loop, plus the one resync builder_act also does between
calls (`_sync_confirm_edits`, called from both the paused and finished
branches): an edit typed at the confirm step updates `location_names` only as
a LOCAL variable inside that one call (stashed onto ws["_locations_synced"]
for the caller to pick up) — production re-derives its `location_names`
argument from the synced value before the next dispatch, so a retry here
does the same or it would silently re-ask against the stale original list.
"""
from __future__ import annotations

import asyncio

from app.graph.builder.executors import geo


def run_det(*args, **kwargs) -> None:
    """asyncio.run(geo._execute_deterministic(...)), driven to completion."""
    args = list(args)
    ws = args[6] if len(args) > 6 else kwargs.get("ws")

    async def _drive() -> None:
        for _ in range(10):
            try:
                await geo._execute_deterministic(*args, **kwargs)
                return
            except geo._GeoStepPaused:
                synced = ws.get("_locations_synced") if isinstance(ws, dict) else None
                if synced and len(args) > 2:
                    args[2] = list(synced)
                continue
        raise RuntimeError("geo._execute_deterministic did not settle after 10 calls")

    asyncio.run(_drive())
