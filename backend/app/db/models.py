"""
app/db/models.py
SQLAlchemy ORM models for all database tables.
All primary keys use UUID for multi-tenant safety.
"""
import uuid 
from sqlalchemy import (
    Column, String, Text, DateTime, Date, ForeignKey,
    Numeric, JSON, Boolean, Integer, Enum as SAEnum, Float,   Identity,ForeignKey,BigInteger,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID,TIMESTAMP,JSONB
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
# from app.modules.user.models import User
from app.shared.enums import AdPlatform, CampaignStatus, UserRole
import enum

class Base(DeclarativeBase):
    pass
 

class MaidExtraction(Base):
    """
    Stores MAID extraction results outside LangGraph state to avoid bloating checkpoint state.
    LangGraph state holds only maid_extraction_id (UUID ref).
    """
    __tablename__ = "maid_extractions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Bumped on every store_maid_extraction/update_maid_extraction write — the
    # "still being worked on" signal the abandoned-row sweep keys on. An active
    # editing session keeps re-touching this row; an abandoned one stops.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    maid_count = Column(Integer, nullable=False)
    maids = Column(JSON, nullable=False)             # list[str] — unique device IDs
    observations = Column(JSON, nullable=False)      # list[{lat, lng, maid, count}] — all sightings (count = per-dot sighting frequency), uncapped
    pois = Column(JSON, nullable=False)              # list[POI] — for reconnect map rebuild
    center = Column(JSON, nullable=True)             # {latitude, longitude, ...}
    search_radius_km = Column(Float, nullable=True)
    lookback_days = Column(Integer, nullable=True)
    event_date_ranges = Column(JSON, nullable=True)  # list[str]

    # Audience-layering: `maids`/`observations` above are the UNFILTERED
    # superset (everything bought for this extraction's POIs and window).
    # `audience_filter` is the active AudienceFilter spec (maid_store.py) and
    # `filtered_maid_count` is its result count — both null when no layering
    # has been applied (i.e. the audience IS the full superset).
    audience_filter = Column(JSON, nullable=True)
    filtered_maid_count = Column(Integer, nullable=True)

    # Set the moment `maids`/`observations` are cleared — on a successful
    # publish (the identifiers are in Meta by then, Punk has no further use for
    # them) or by the abandoned-row sweep. NULL means the raw superset below is
    # still intact. Everything else on the row (counts, pois, center, the
    # filter spec) survives a purge: reporting and campaign-template reuse need
    # them, only the raw device IDs are the retention-sensitive part.
    purged_at = Column(DateTime(timezone=True), nullable=True)


class SuppressedMaid(Base):
    """Advertising IDs never to upload to a Meta audience — an opt-out or
    take-down request against the licensed data.

    Empty today: this is the seam maid_store.suppress() checks before every
    upload, built ahead of the supplier's opt-out/deletion feed rather than
    after, so the compliance-critical call site exists and is tested before
    there is real data to feed it. Wiring the real feed later is an ingester
    writing rows here, nothing about the upload path changes.
    """
    __tablename__ = "suppressed_maids"

    maid = Column(String(64), primary_key=True)
    # Where this suppression came from — "manual", or the supplier feed's name
    # once one exists. Free text on purpose: the source is not yet known.
    source = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Unacast integration ─────────────────────────────────────────────────────
# See docs/maid_unacast_integration_plan.md (architecture) and
# docs/maid_unacast_implementation_tasks.md (the concrete plan these three
# tables come from).


class UnacastRawObservation(Base):
    """One raw ping fetched from Unacast, cached independently of any one
    campaign/session — this is deliberately NOT the same store as
    MaidExtraction.observations (a per-session JSON blob that gets purged on
    publish). A later campaign against the same POI reads straight from here
    instead of re-spending the shared monthly budget. See
    UnacastFetchCoverage for the watermark that decides what still needs
    fetching, and purge_maid_extraction (maid_store.py) for why this table is
    never touched by that function — its retention is independent, on
    purpose (see the implementation-tasks doc §5).
    """
    __tablename__ = "unacast_raw_observations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    poi_key = Column(String(64), nullable=False, index=True)
    # registrationID or advertiserID, verbatim, whichever the API populated —
    # see unacast_query.py's _extract_maid. Treated as the MAID either way.
    maid = Column(String(64), nullable=False, index=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    forensic_flags = Column(BigInteger, nullable=True)
    hot = Column(Boolean, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    # The ring CENTRE alone, no radius (unacast_query.center_key). Pings are read
    # back by centre + distance, so a ring bought at 500 m serves a later 100 m
    # request at the same place. NULL on rows written before that existed.
    center_key = Column(String(32), nullable=True)
    # Where this row came from. NULL = a real ping from observations/geo/search.
    # "devices" = a synthetic (device, feature) presence row from the temporary
    # /areas/devices path (unacast_devices.py) — no position/flags evidence, so
    # it must be excluded from density math and the accuracy gate. Deleted in
    # bulk when the observations entitlement gets real advertising IDs.
    src = Column(String(8), nullable=True)

    __table_args__ = (
        Index("idx_unacast_raw_poi_ts", "poi_key", "observed_at"),
        Index("idx_unacast_raw_center_ts", "center_key", "observed_at"),
        # One ping per device-second per centre, whichever radius bought it: a
        # 100 m purchase and a later 500 m one return the same pings twice.
        Index(
            "uq_unacast_raw_center_maid_ts",
            "center_key", "maid", "observed_at",
            unique=True, postgresql_where=center_key.isnot(None),
        ),
        # Defence in depth behind persist_rows' coverage upsert. Two sessions
        # extracting the same POI-day at once used to both fetch and both
        # insert, double-counting every ping — which inflates visit counts and
        # makes `min_visits` fire on devices that did not qualify.
        Index(
            "uq_unacast_raw_poi_maid_ts",
            "poi_key", "maid", "observed_at",
            unique=True,
        ),
    )


class UnacastFetchCoverage(Base):
    """The watermark: one row per (poi_key, date) that has already been
    fetched from Unacast and persisted into UnacastRawObservation. Existence
    alone is the signal — before firing a call, subtract already-covered
    days from the requested range and query only the true gap."""
    __tablename__ = "unacast_fetch_coverage"

    poi_key = Column(String(64), primary_key=True)
    date = Column(Date, primary_key=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    # The vendor caps a DIRECT response at 100k observations PER FEATURE and
    # sets observationLimitHit when it truncates — so this POI-day's pings are a
    # partial, non-random sample and its frequency counts are FLOORS, not
    # measurements. Durable because the disclosure has to outlive the process
    # that fetched it: unacast_query._TRUNCATED_FEATURES is in-memory, so a
    # cache-only re-run (no API call, the common case once warm) previously
    # reported nothing truncated and the user was told a sampled audience was
    # complete. Nullable: rows written before this column existed genuinely do
    # not know, and that is not the same as False.
    truncated = Column(Boolean, nullable=True)
    # What this day was bought AT (unacast_query.covered_days_bulk): the centre
    # and clamped ring radius — a day covered at R serves any r <= R at the same
    # centre — and the length of the feature window it was bought inside, which
    # decides whether a truncated day can be repaired by a narrower window.
    # NULL on rows written before these existed; those are not reused.
    center_key = Column(String(32), nullable=True)
    radius_m = Column(Integer, nullable=True)
    window_days = Column(Integer, nullable=True)
    # See UnacastRawObservation.src — same meaning, so a device-list day and a
    # real observations day never satisfy each other's watermark check.
    src = Column(String(8), nullable=True)

    __table_args__ = (
        Index("idx_unacast_coverage_center_date", "center_key", "date"),
    )


class UnacastUsageLedger(Base):
    """One row per calendar month (period = 'YYYY-MM').

    calls_made is the metered quantity: the vendor's monthly quota counts API
    CALLS (settings.UNACAST_MONTHLY_CALL_BUDGET), one shared key, platform-wide,
    first-come-first-served, no per-customer sub-quota. A call costs the same
    whether it returns three observations or a truncated maximum.

    observations_used is telemetry only — what those calls actually returned. It
    is recorded for capacity planning and for the per-feature truncation
    question; it never gates admission. (An earlier revision metered on it, on
    an unconfirmed assumption about the quota's unit; that was wrong.)

    provisional_reserved holds calls that are admitted but not yet made. It
    closes a real race: up to UNACAST_MAX_CONCURRENT_CALLS calls can be in
    flight at once, each taking up to ~130s, and without a reservation several
    concurrent admission checks could each see "budget available" before any of
    them commits. See unacast_query.py's reserve_call/reconcile_call.

    requests_made is the count of real HTTP requests, which is >= calls_made
    because UnacastClient retries a 429/5xx internally. The two are different
    limits and must not be conflated: the MONTHLY quota counts calls, while the
    vendor also enforces a DAILY request limit per API key (429, resets 00:00
    UTC). Counting only batches made the ledger read low against that daily
    limit, so we believed we had headroom we did not.
    """
    __tablename__ = "unacast_usage_ledger"

    period = Column(String(7), primary_key=True)
    observations_used = Column(Integer, nullable=False, default=0)
    requests_made = Column(Integer, nullable=False, default=0, server_default="0")
    provisional_reserved = Column(Integer, nullable=False, default=0)
    calls_made = Column(Integer, nullable=False, default=0)


class UnacastCallLog(Base):
    """One row per Unacast call that actually reached the vendor — the
    per-thread / per-user / global ATTRIBUTION half of Unacast accounting.

    ``unacast_usage_ledger`` above stays exactly as it is: it is the
    platform-wide BUDGET GUARD, one locked row per month, and it is what
    ``reserve_call`` contends on. Adding user columns there would break the
    ``with_for_update()`` serialization the whole concurrency design depends
    on, so attribution lives here instead.

    Written inside the SAME transaction as the ledger increment
    (``unacast_query.reconcile_call``), so ``SUM(calls) GROUP BY period`` and
    ``unacast_usage_ledger.calls_made`` can never disagree. That is what makes
    per-user and per-thread totals reconcile against the global one.

    Attribution is recorded when the CALL happens, not when the turn is billed.
    The billing path (``chat/service.py::_bill_usage``) cannot carry this: it
    skips its state write while a subgraph interrupt is pending, and a MAID
    extraction almost always ends at the maid_confirm interrupt — so a
    per-thread counter fed from there would be wrong for exactly the turns that
    spend Unacast budget.

    ``user_id``/``thread_id`` are NULL for a call made outside a chat turn (a
    script, the autopilot, a manual run). Those rows are the reconciling
    remainder: the difference between "what every user spent" and "what the
    month actually cost" is then queryable rather than silently missing.

    ``ondelete="SET NULL"`` and not CASCADE: deleting a user must not erase what
    was already spent on their behalf, or the ledger stops reconciling.

    No device IDs and no coordinates — nothing here is personal data, so it
    carries no retention obligation and the MAID sweeps do not touch it. At the
    contract ceiling this grows by at most UNACAST_MONTHLY_CALL_BUDGET rows a
    month.
    """
    __tablename__ = "unacast_call_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    # 'YYYY-MM' — the same period key the ledger uses, so the two join directly.
    period = Column(String(7), nullable=False, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    thread_id = Column(String(255), nullable=True, index=True)   # = chat session_id
    # Two quantities, deliberately not one — see the ledger's docstring: `calls`
    # is the MONTHLY quota unit (one per batch), `requests` the vendor's DAILY
    # per-key limit unit (real HTTP requests, retries included, so >= calls).
    calls = Column(Integer, nullable=False, default=1)
    requests = Column(Integer, nullable=False, default=1)
    observations = Column(Integer, nullable=False, default=0)
    # NULL = the observations/geo/search path; 'devices' = the Meta-upload path
    # (unacast_devices.py). Mirrors UnacastRawObservation.src.
    src = Column(String(32), nullable=True)


class UnacastCircuit(Base):
    """Circuit-breaker state for the Unacast vendor, shared across workers.

    One row, ``id = 'unacast'``. The breaker exists because a call is committed
    to the ledger before the request returns (correct — reaching the vendor
    consumes quota), so during an outage every extraction reserves, fires, fails
    and pays, draining a shared FCFS monthly budget while returning nothing.

    It lived in module globals, which stops only the acute single-worker case:
    Cloud Run runs this service at ``maxScale=5``, so an open breaker in one
    worker did nothing about the other four still spending. State has to be
    where every worker can see it, which is here.

    ``opened_at`` NULL means closed. Guarded by the same ``pg_advisory_xact_lock``
    pattern ``unacast_query.acquire_concurrency_slot`` uses for the concurrency
    gate, on its own key.
    """
    __tablename__ = "unacast_circuit"

    id = Column(String(32), primary_key=True, default="unacast")
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")
    opened_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UnacastConcurrencyLease(Base):
    """One row per in-flight Unacast call. Acquiring/releasing a slot is
    serialized with a Postgres advisory lock (pg_advisory_xact_lock) around
    "count current leases, insert if under the limit" — see
    unacast_query.py's acquire_concurrency_slot. A lease older than
    settings.UNACAST_LEASE_STALE_AFTER_S is reaped as abandoned (a crashed
    request that never released) rather than permanently holding a slot.
    First-come-first-served, no per-session reservation — the whole point is
    a single shared pool across the platform, matching the shared API key.
    """
    __tablename__ = "unacast_concurrency_leases"

    lease_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    acquired_at = Column(DateTime(timezone=True), server_default=func.now())


class UnacastDensityCell(Base):
    """UNUSED. Was a learned foot-traffic density atlas (observations per
    square metre per day, per ~1 km cell) that pre-sized a request before it
    was sent — and, from the same guess, refused a search estimated too big.
    The guess was built from pre-truncation response totals (up to ~14x what a
    request could ever return) and produced real false refusals; removed in
    favour of legality-only packing (unacast_query.plan_requests) plus
    deterministic splitting on an actual vendor timeout
    (unacast_query._split_request) — see that module's docstring.

    Table (and its rows) left in place rather than dropped: this backend's
    local .env points at the production database, so no migration is run from
    here. Safe to drop in a future migration once nothing else expects it.
    """
    __tablename__ = "unacast_density_cells"

    cell = Column(String(24), primary_key=True)
    obs_per_m2_day = Column(Float, nullable=False)
    samples = Column(Integer, nullable=False, default=0, server_default="0")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CreativeGenerationJob(Base):
    """Async job tracking a Punk-generated ad creative (Gemini image).

    The background runner renders the image and, on completion, ``media_id`` points
    at a persisted ``MediaFile`` row — the SAME table an upload produces — so the graph's
    ``collect_creatives`` interrupt consumes a generated asset exactly like an
    uploaded one (a UUID handed to ``parse_creative_media_id``). The generation
    flow never touches the LangGraph turn; it is a side-channel REST job.
    """
    __tablename__ = "creative_generation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Chat session/thread the campaign lives in — used to load campaign context
    # for the prompt. Plain string (== LangGraph thread_id), not an FK.
    thread_id = Column(String(255), nullable=True, index=True)

    media_type = Column(String(10), nullable=False)   # "image"
    status = Column(String(20), nullable=False, default="running")  # running | ready | failed
    prompt = Column(Text, nullable=True)              # composed visual prompt (audit/debug)
    error = Column(Text, nullable=True)               # failure reason when status == "failed"

    media_id = Column(UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True)
    # Every variant of the round (list[str] of MediaFile UUIDs, ``media_id`` first).
    # A round renders several concepts and the user picks one or more, so the job
    # has to remember the whole set — ``media_id`` alone can only name the first.
    media_ids = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    media = relationship("MediaFile")


class UsageEvent(Base):
    """One row per (turn, vendor-surface) — the SQL-queryable record of what a
    turn actually cost, independent of whether it was billable.

    Why this exists outside the checkpoint: per-thread totals otherwise live
    only in the LangGraph checkpoint (``AgentState.total_tokens`` /
    ``token_cost_usd`` / ``google_api_calls``), which is not SQL-queryable, and
    ``ChatService._bill_usage`` cannot write it while a subgraph interrupt is
    pending (see ``ChatService._graph_is_interrupted``'s docstring) — which is
    how a MAID extraction almost always ends.

    Why this exists outside ``token_transactions``: that row is only written
    when the user HAD balance. A 402 from ``TokenService.deduct_tokens`` means
    real Gemini spend with nothing recorded there.

    Written unconditionally from ``ChatService._commit_turn`` via
    ``app.graph.usage.flush_usage_events``, on its own session, never raising.
    This is telemetry, not billing: it does not gate anything and must never be
    able to fail a turn.

    Unacast is deliberately NOT written here. ``unacast_call_log`` already
    carries period/user/thread in the SAME transaction as the budget-ledger
    increment (``unacast_query.reconcile_call``); duplicating it would add a
    second writer inside that transaction and a reconciliation invariant with
    no reader. Admin rollups UNION the two tables at read time instead.

    INVARIANT: ``quantity`` is TOKENS when ``kind == 'llm_tokens'`` and
    REQUESTS for every other kind. Never SUM across kinds — filter by kind
    first (SQL ``FILTER (WHERE kind = ...)``).

    ``user_id`` is NULL for map-widget rows — ``/map/*`` routes are
    unauthenticated. Resolve it at read time via ``conversations.thread_id``
    (unique-indexed), not by touching those routes' auth.

    A rewound thread's discarded turn keeps its rows here even though
    ``AgentState`` drops them (rewind clears ``pending_usage``) — that is
    correct, the money was really spent, so this table can legitimately exceed
    ``AgentState.total_tokens`` on a thread that was edited/rewound.
    """
    __tablename__ = "usage_events"

    # Monotonic, not UUIDv4: highest-insert table in the schema — a random PK
    # fragments the b-tree on every insert. Same idiom as ChatMessage.auto_id.
    id = Column(BigInteger, Identity(), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # 'YYYY-MM' — same key as unacast_usage_ledger / unacast_call_log, so all
    # three join directly, and retention (if ever needed) is one predicate.
    period = Column(String(7), nullable=False, index=True)
    # SET NULL, not CASCADE: deleting a user must not erase what was spent.
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    thread_id = Column(String(255), nullable=True, index=True)
    # 'llm_tokens' | 'google_maps' | 'grounding' — see INVARIANT above.
    kind = Column(String(32), nullable=False)
    # Model name for llm_tokens rows, the record_api_call() key otherwise.
    api = Column(String(64), nullable=False)
    quantity = Column(Integer, nullable=False)
    # Tokens only, for now — call rows carry no invented rate.
    cost_usd = Column(Numeric(12, 8), nullable=True)
    # 'chat' | 'rewind' | 'map_widget'
    source = Column(String(32), nullable=True)
    # {"in", "out", "think"} on llm_tokens rows only — unbackfillable once the
    # turn ends, the only reason this speculative column earns its place.
    detail = Column(JSONB, nullable=True)