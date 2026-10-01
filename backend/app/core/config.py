"""
app/core/config.py
Central configuration using pydantic-settings.
All values are loaded from environment variables or .env file.
"""
from functools import lru_cache
from operator import truediv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator
from typing import List, Union


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "PunkAI"
    APP_VERSION: str = "0.2.0"
    APP_PORT: int = 8000
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # ── Security ─────────────────────────────────────────────────────────
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    GOOGLE_CLIENT_ID: str = "176573531597-lkt69if4vktjh9p465f3pufbjr8io1ge.apps.googleusercontent.com"
    APPLE_CLIENT_ID: str = ""
    DEFAULT_FREE_TOKENS: int = 10000

    # ── Database (PostgreSQL) ─────────────────────────────────────────────
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "emptyad" 

    # ── Redis ─────────────────────────────────────────────────────────────
    # Shared state across Cloud Run instances. The service runs maxScale=5 with
    # sessionAffinity=false, so anything held in a process-local dict is invisible
    # to the other four instances — which is why the chat run registry
    # (modules/chat/runs.py) loses a turn on refresh, and why the rate limiter's
    # effective ceiling is 5x what it says.
    #
    # These were already in .env and silently DROPPED: nothing declared them and
    # model_config sets extra="ignore". Declaring them is what turns Redis on.
    #
    # Empty host = disabled, and every consumer must fall back to its existing
    # in-process behaviour rather than failing. Local dev and CI therefore need no
    # Redis at all.
    REDIS_HOST: str = ""
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        """redis:// URL, or "" when Redis is not configured.

        Password is quoted because a Redis password with @ or / in it would
        otherwise break the URL — the same trap CHECKPOINT_DB_URL uses
        make_conninfo to avoid.
        """
        if not self.REDIS_HOST:
            return ""
        from urllib.parse import quote

        auth = f":{quote(self.REDIS_PASSWORD, safe='')}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def REDIS_KEY_PREFIX(self) -> str:
        """Namespace for every key this process writes.

        One Redis instance is shared, and a developer's .env points at the same
        host as a deployment. Without a prefix a local run and production would
        read and write each other's chat replay buffers — so the environment name
        is baked into every key.
        """
        return f"punk:{(self.ENVIRONMENT or 'development').strip().lower()}:"

    # ── Email / SMTP ──────────────────────────────────────────────────────
    EMAIL_SERVER_HOST: str = "smtp.office365.com"
    EMAIL_SERVER_PORT: int = 587
    SMTP_USER: str = "smtp-user@example.com"
    SMTP_PASS: str = "Theclubhouse@empty"
    EMAILS_FROM_NAME: str = "Punk AI"
    EMAIL_LOGO_URL: str = ""  # Public URL to the Punk AI logo image (e.g. hosted on S3/CDN)


    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous URL for Alembic command-line tools."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def CHECKPOINT_DB_URL(self) -> str:
        """psycopg3 conninfo for the LangGraph Postgres checkpointer.

        Built via make_conninfo so passwords with special chars (@ ! # …) are
        escaped correctly — a hand-built URL string would break on those.
        psycopg3 rejects the SQLAlchemy ``+asyncpg`` dialect suffix, so this is
        a plain conninfo, distinct from DATABASE_URL.
        """
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            dbname=self.POSTGRES_DB,
        )

    # ── LLM (Gemini on Vertex — Gemini Enterprise Agent Platform) ─────────
    # Authenticates with Application Default Credentials: the Cloud Run service
    # account in prod (roles/aiplatform.user), `gcloud auth application-default
    # login` locally. There is no API key. The project is defaulted rather than
    # required so the migrate step and the arq worker — which import settings but
    # never call an LLM — need no extra env.
    GCP_PROJECT_ID: str = "<GCP_PROJECT>"
    VERTEX_LOCATION: str = "global"
    # Cheap/fast tier — classifiers, routers, tool-internal calls.
    # gemini-2.5-* is DISCONTINUED 2026-10-20. 3.5-flash-lite is Google's named
    # replacement and prices the same as 2.5-flash ($0.30/$2.50 per 1M); on the
    # tests/evals corpus it beat 2.5 (7 vs 13 failing of 104) and 3.1-flash-lite
    # (14) lost. gemini-3.5-flash scored 3 failing but costs 5x/3.6x — set
    # GEMINI_MODEL=gemini-3.5-flash if accuracy is worth that.
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    # Smart tier — brain nodes (chatbot, intent extraction, campaign brief/JSON,
    # campaign-manager ReAct). Used by every _make_thinking_llm factory.
    # Google's replacement for 2.5-pro; $1.50/$9.00 vs $1.25/$10.00.
    # Also runs the ExtractedUserInfo calls in nodes.py: flash-lite dropped
    # location, the angle and business_description on thread a90cc17c's turn 1.
    GEMINI_MODEL_PRO: str = "gemini-3.5-flash"
    GEMINI_TEMPERATURE: float = 0.7

    @property
    def llm_auth(self) -> dict:
        """Auth kwargs for ChatGoogleGenerativeAI — the only place that knows how
        the LLM is authenticated. Explicit project/location beat any
        GOOGLE_API_KEY that is still in the environment (google-genai
        _api_client), which matters while the old prod service still carries one."""
        return {"vertexai": True, "project": self.GCP_PROJECT_ID, "location": self.VERTEX_LOCATION}

    @property
    def genai_auth(self) -> dict:
        """Auth kwargs for google.genai.Client (grounding, creative gen)."""
        return self.llm_auth

    # ── Campaign-manager deep-agent ──────────────────────────────────────
    # Planning tool (write_todos): forces the post-publish ReAct loop to lay
    # out and track an explicit plan before acting. Surfaced via the existing
    # `thinking` stream. Kill-switch — false reverts to plain ReAct.
    CAMPAIGN_MANAGER_PLANNING_ENABLED: bool = True

    # Meta Ads MCP (pipeboard meta-ads-mcp) for post-publish campaign manager.
    # Uses the user's Punk OAuth token — no separate MCP auth flow.
    META_MCP_ENABLED: bool = True
    META_MCP_CONNECT_TIMEOUT_S: float = 45.0

    # ── Resume router: edit lane ─────────────────────────────────────────
    # Floor on the classifier's self-reported confidence before a mid-build edit
    # is COMMITTED (which invalidates downstream work and re-runs it — a POI
    # search, a warehouse query, minutes of latency). Below the floor the edit
    # is reframed ("I didn't catch that") instead, which costs a genuine edit
    # nothing but stops a mis-read reply from burning a rebuild.
    #
    # This exists because the 2026-06 resume-router had NO confidence gate: any
    # `is_append` on a list field silently rewound the whole conversation, which
    # is what got that design removed. Set to 0.0 for unconditional auto-rebuild.
    RESUME_EDIT_MIN_CONFIDENCE: float = 0.7

    # Phase 3 rollout flag — routes wizard_interrupt's classifier call to the
    # tool-calling backend (resume_router.classify_resume_intent_tools)
    # instead of the lane-JSON one (classify_resume_intent). Both return the
    # SAME ResumeIntent shape, so wizard_helpers's dispatch block is
    # unchanged either way — flipping this only changes HOW the reply gets
    # classified, never how a classification is acted on. On since the
    # registry-generated schema (builder/knobs.py) passed the live parity eval
    # at or above the lane-JSON backend on every category (2026-09-25). The
    # lane-JSON classifier stays as the crash fallback until one release has
    # run on this; then its hand-written field catalog is deleted.
    RESUME_ROUTER_TOOLCALLING: bool = True

    # One interrupt() per task: any reply that doesn't answer the step on screen
    # (an edit, a question, a reject) ends the task and the planner re-dispatches
    # it, instead of looping in place. Pinned per build in
    # campaign_builder_state["_single_interrupt"] the first time builder_plan
    # sees it, so a build never switches semantics halfway through — builds
    # already in progress when this shipped keep the old in-place loop. On for
    # new builds since the real builder subgraph passed end-to-end resume tests
    # (tests/test_single_interrupt_e2e.py) and the full suite in both modes.
    # Rollback lever: BUILDER_SINGLE_INTERRUPT=false (affects NEW builds only).
    BUILDER_SINGLE_INTERRUPT: bool = True

    # /rewind on a builder step: restore that step's saved state on the thread head and
    # start the builder fresh, so the step is genuinely re-asked and an edit resumes
    # from that point (modules/chat/rewind_restore.py). The old way — fork the step's
    # checkpoint and replay — swallows the thread's last resume value and walks past
    # the step. Rollback lever: REWIND_RESTART_ENABLED=false restores the old fork.
    REWIND_RESTART_ENABLED: bool = True

    # ── Wizard milestone narrator (T2 response tier) ─────────────────────
    WIZARD_NARRATOR_ENABLED: bool = True       # kill-switch — false disables LLM narration
    WIZARD_NARRATOR_MAX_CHARS: int = 600       # hard truncate cap on emitted text
    # Per-attempt ceiling on one composer stream (narrator/composer.py). On expiry
    # with nothing streamed it retries once, then the beats' fallback text runs.
    WIZARD_NARRATOR_TIMEOUT_S: float = 45.0
    # Reveal moments (milestone result reveals + between-stage handoffs) get a
    # larger budget so they can show a compact, scannable breakdown rather than
    # being squeezed into the one-line step-framing cap above.
    NARRATOR_REVEAL_MAX_CHARS: int = 800

    # ── Narrator v3 ("one mind per screen" composer) ─────────────────────
    # The narrator buffers per-moment beats and composes ONE message per screen
    # (see app/graph/narrator/composer.py). WIZARD_NARRATOR_ENABLED above stays
    # the hard kill-switch (false ⇒ no narrated message at all; widgets still render).
    # Every screen runs on GEMINI_MODEL_PRO; only the thinking LEVEL varies
    # (minimal | low | medium | high — Gemini 3's replacement for thinking_budget).
    # 1.0 = Google's guidance for Gemini 3+ (the SDK warns that < 1.0 can loop or
    # degrade). Eval at 0.7 vs 1.0 was a statistical tie, so the vendor default wins.
    NARRATOR_COMPOSER_TEMP: float = 1.0
    # Rich turns: reveal / handoff / failure / budget framing / a mid-step answer.
    NARRATOR_COMPOSER_THINKING_LEVEL: str = "medium"
    # Simple turns (framing / edit / auto_fill / reframe): light, so the first
    # streamed token lands fast on the common collection screens.
    NARRATOR_COMPOSER_THINKING_LEVEL_FAST: str = "low"
    # Chatbot (nodes.chatbot_node) sampling temperature. Same reasoning as above;
    # it was 0.55 to curb number/name drift; the eval showed no more of it at 1.0
    # (number-grounding hard check: same rate at both settings).
    CHATBOT_TEMP: float = 1.0

    # ── Campaign budget ───────────────────────────────────────────────────
    # Hard floor for recommended/custom budgets. Meta's API rejects daily
    # budgets below ~$1/day; this is the last-resort clamp so an LLM lowball
    # (the seed-anchoring bug produced "$2.68/day") can never ship something
    # Meta would reject. Lifetime floor = this × flight days. Realism is the
    # prompt's job; this is only the safety net.
    CAMPAIGN_MIN_DAILY_BUDGET_USD: int = 1

    # ── Maps & Places ─────────────────────────────────────────────────────
    GOOGLE_MAPS_API_KEY: str
    GEO_AREA_TILE_THRESHOLD_KM: int = 0    # bbox diagonal above which we tile; 0 = tile every bounded area (uniform density across scopes). Raise to restore single-search for small areas / cut Google API cost.
    GEO_METRO_UNFILTERED_KM: int = 60      # bbox diagonal above which the locality string-filter is skipped (multi-borough metros: NYC/LA — trust the hard bounds; ordinary cities like Montreal stay filtered)
    GEO_MAX_TILES: int = 9                 # base tiles per area (3x3). _tile_bbox floors to an
                                            # n x n grid (n = isqrt), so keep this a PERFECT
                                            # SQUARE — 12 silently produced this same 9.
    GEO_TILE_SPLIT_DEPTH: int = 0          # levels a saturated tile (full page of raw results)
                                            # may subdivide into 4 quadrants; 0 = OFF (flat grid,
                                            # baseline cost). Raise to trade Google API cost for
                                            # POI depth in dense areas.
    GEO_MAX_TILE_SEARCHES: int = 40        # hard ceiling on Places calls per query x location
    # TEST/OPS KNOB — OFF (0) IN PRODUCTION, AND IT MUST STAY THAT WAY.
    #
    # When >0, keeps only the N best-rated places in EACH category/brand/event
    # group before the POI-confirm gate (per category, not overall: a global cap
    # on a search returning 20 Sephora and 3 Ulta would drop Ulta entirely and
    # silently answer a different question than the user asked).
    #
    # A real campaign wants EVERY location in its category — 50 outlets under one
    # brand is 50 geofences the advertiser is entitled to, and quietly targeting
    # the best-rated 10 hands them a smaller audience than they asked for with no
    # way to tell. The quota counts API calls, not POIs, so the long tail is
    # nearly free: 50 features is 5 requests. Set this only to keep a manual test
    # run small; never as a production default.
    GEO_MAX_POIS_PER_CATEGORY: int = 0
    # A 5.0 from 3 reviews is noise, not a busy store: places at or above this
    # review count outrank every thin-sample place regardless of star rating.
    GEO_POI_RATING_MIN_SAMPLE: int = 50
                                            # (base tiles + adaptive splits). Cost bound.
    GEO_POI_MAX_PAGES: int = 1             # nextPageToken pages per query (20/page)
    GEO_REGION_POLYGON_FILTER: bool = True # fetch a region's real OSM polygon and drop POIs inside its bbox but outside its true shape (Manhattan inside Long Island's box). Kill switch → False = bbox-only (legacy).
    GEO_POLYGON_SIMPLIFY_M: int = 100      # Douglas–Peucker tolerance (metres) for the region polygon; ~100 m preserves fine coastal boundaries (East River) while collapsing straight runs.
    GEO_POLYGON_MAX_VERTS: int = 20000     # safety cap on simplified polygon vertices; tolerance escalates until under this (guards continent-scale shapes).
    GEO_NOMINATIM_MIN_INTERVAL_S: float = 1.0  # min spacing between Nominatim polygon calls (public policy ~1 req/s; lower if self-hosting Nominatim).
    GEO_POLYGON_CACHE_SIZE: int = 512      # process-level polygon cache cap (place-stable; FIFO-trimmed).
    NAMED_PLACE_MATCH_MIN: float = 0.5     # min fraction of a query name's significant tokens that must appear in a place's display name for the named_places angle (looser than competitor_brand's all-token gate: "McGrill Bar" → "McGrill" = 0.5 passes).
    NAMED_PLACE_PER_NAME_LIMIT: int = 5    # max matches kept per named-place query (specific-venue intent, not a category sweep).
    NAMED_CHAIN_MIN_OUTLETS: int = 3       # ≥ this many EXACT-name Places results ⇒ the query name is a recurring brand → keep all outlets (grounded brand-vs-venue classification).
    NAMED_BRAND_MAX: int = 25              # cap on outlets kept for a name classified as a brand/chain.
    NAMED_DEDUP_DISTANCE_KM: float = 0.15  # POIs sharing a normalized name AND within this distance are treated as the same place (drops repeats; keeps distinct same-name outlets that are far apart).
    # Pin+radius confirm (city/town/metro scope, and the standalone "drop a
    # pin" flow): shared clamp for both the default-radius derivation
    # (executors/geo.py) and the frontend's radius stepper, and the same
    # bound meta_ads.py's custom_locations.radius fallback already enforces —
    # one source of truth so the search-time ring and the publish-time
    # fallback ring can never drift apart.
    GEO_PIN_RADIUS_MIN_KM: float = 1.0
    GEO_PIN_RADIUS_MAX_KM: float = 80.0
    GEO_PIN_RADIUS_FALLBACK_KM: float = 10.0  # no bounds to derive from (street address / manual pin) — flat default.

    # ── Ad Platforms ──────────────────────────────────────────────────────
    META_APP_ID: str
    META_APP_SECRET: str
    # The app created 2026-09 was created after Graph v26.0 shipped (29 Jul 2026)
    # and has never called v25.0 — Meta's rule is an app can only call versions
    # that existed at its creation or that it has already called, no rollback
    # lane. v25.0 would 100% fail on this app. Do not move this back.
    META_API_VERSION: str = "v26.0"
    META_REDIRECT_URI: str = "http://localhost:8000/ads/callback/meta"
    # Facebook Login for Business configuration id (App Dashboard → Facebook
    # Login for Business → Configurations). Required: the classic consumer-login
    # code path is gone, so there is no flow left that runs without this.
    META_LOGIN_CONFIG_ID: str = ""
    # Kill-switch for the final activation pass. Every object Punk creates is
    # PAUSED by default (CampaignSpec/AdSetSpec/AdSpec status, and create_ad pins
    # it), so this one flag is the only thing standing between a published
    # campaign and live spend. Set false to publish end-to-end without anything
    # going live — the only safe way to test against a real ad account when the
    # MAID audience is demo data.
    META_PUBLISH_ACTIVATE: bool = True
    # Conversions API — the server-side half of event tracking. Off turns
    # /tracking/events into a no-op that still returns 200, so a customer's site
    # keeps working while the feature is disabled.
    #
    # There is deliberately no dataset id or Meta credential beside this: Punk is
    # multi-tenant, so every dataset lives in the connected user's own business and
    # every call uses their own token. A platform-wide dataset would put every
    # advertiser's conversions in one event store and take their history with us
    # when they leave.
    CAPI_ENABLED: bool = True
    # Public base URL the customer's site or CRM POSTs conversions to. Only used to
    # print the endpoint in the install snippet — which is why it has to be https
    # anywhere but a dev box: the requests it invites carry raw email, phone and
    # address, and the validator below refuses to boot rather than print a
    # plaintext endpoint into somebody's checkout.
    BACKEND_PUBLIC_URL: str = "https://api.usepunk.ai"
    # Echoed back to Meta once, when it verifies POST /tracking/webhook. Any value,
    # as long as it matches what is typed into the app's Webhooks settings. Empty
    # disables verification entirely, which is the right default for a deployment
    # that has not set the webhook up: an unconfigured endpoint should refuse the
    # handshake rather than accept any token offered to it.
    META_WEBHOOK_VERIFY_TOKEN: str = ""

    @field_validator("BACKEND_PUBLIC_URL")
    @classmethod
    def _ingest_endpoint_is_encrypted(cls, value: str) -> str:
        """Refuse a plaintext ingest endpoint anywhere but localhost.

        This URL is printed into the customer's site and CRM as the address to POST
        conversions to, and those requests carry raw email, phone and address. A
        deploy that got it wrong would hand every advertiser a plaintext endpoint,
        and the failure is invisible — the events arrive, tracking looks healthy,
        and the identifiers went over the wire in the clear.

        Failing at startup rather than in ``TrackingService.snippet`` is the whole
        point: by the time the snippet renders, the wrong URL is already pasted
        into somebody's WordPress and copied into their server config.
        """
        url = str(value or "").strip()
        if url.startswith("https://"):
            return url
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return url
        raise ValueError(
            f"BACKEND_PUBLIC_URL must be https:// outside local development, got "
            f"{url!r}. It is printed into customer sites as the conversion ingest "
            f"endpoint, and those requests carry raw personal data."
        )

    @property
    def META_GRAPH_URL(self) -> str: 
        """Graph API base, with trailing slash. Derived, never configured.

        This used to be an independent setting carrying its own hardcoded version,
        so bumping META_API_VERSION moved the publish path and silently left OAuth
        and the campaigns module on the old one.
        """
        return f"https://graph.facebook.com/{self.META_API_VERSION}/"

    # ── Uploads ─────────────────────────────────────────────────────────
    MEDIA_UPLOAD_DIR: str = "uploads"
    MAX_IMAGE_SIZE_MB: int = 10
    MAX_VIDEO_SIZE_MB: int = 100

    # ── Creative generation (Gemini Developer API: image) ────────────────
    # FUTURE WORK (Post-Version 1):
    # AI Image creative generation is disconnected for Version 1 and scheduled
    # for a future release. In Version 1, users upload their own media assets
    # or select existing Facebook Page / Instagram posts for ad creatives.
    CREATIVE_GEN_ENABLED: bool = False
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"
    # Meta-compliant defaults for generated creatives. 1:1 (1080-class square) is the
    # universal feed placement; 2K (~2048px) clears Meta's min and lifts quality
    # (falls back to default resolution if the model rejects image_size).
    CREATIVE_DEFAULT_ASPECT: str = "1:1"
    CREATIVE_IMAGE_SIZE: str = "2K"

    # ── LangSmith tracing ─────────────────────────────────────────────────
    # LangChain/LangGraph auto-trace when these land in os.environ. pydantic
    # only loads them into Settings, so _export_langsmith_env() below pushes
    # them to os.environ at import time. Toggle off with LANGSMITH_TRACING=false.
    # LANGSMITH_TRACING: bool = True
    # LANGSMITH_API_KEY: str = "PunkAI"
    # LANGSMITH_PROJECT: str = "PunkAI"
    # LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # ── Search ────────────────────────────────────────────────────────────
    TAVILY_API_KEY: str = ""
    # ONE kill-switch for the Gemini-grounding capability, across every surface
    # that asks the live web for facts:
    #   • geo discovery — search_events (Search grounding) and the novel-name
    #     fallback in resolve_named_target (Maps grounding, Search fallback)
    #   • the knowledge_based branch — retrieve_marketing_knowledge
    # Off ⇒ each caller degrades to its own legacy path (Tavily+geocode, no
    # fallback pin, or the static knowledge blurb). Was GEO_GROUNDING_ENABLED
    # when geo was the only consumer; the alias keeps a deployed .env working
    # (model_config sets extra="ignore", so the old key would otherwise be
    # dropped silently rather than error).
    GROUNDING_ENABLED: bool = Field(
        True,
        validation_alias=AliasChoices("GROUNDING_ENABLED", "GEO_GROUNDING_ENABLED"),
    )
    # Model for grounded calls only. Empty → GEMINI_MODEL. Lets grounding move to a
    # stronger model without changing every other LLM call.
    GROUNDING_MODEL: str = ""
    # Below this share of the answer backed by grounding_supports, a grounded answer
    # shown to the user as fact (knowledge retrieval) is treated as ungrounded.
    GROUNDING_MIN_SUPPORT: float = 0.3

    # ── Event targeting verification ──────────────────────────────────────
    # A single event longer than this is a season/series, not an event — its visitor
    # window would be a paid multi-week query. Rejected at verification.
    EVENT_MAX_SPAN_DAYS: int = 31
    # Places hit vs address geocode further apart than this ⇒ the venue is ambiguous.
    EVENT_VENUE_MAX_DRIFT_KM: float = 2.0

    # Max messages before summarizer triggers (approx tokens)
    SUMMARIZER_THRESHOLD: int = 50
    SUMMARIZER_KEEP_LAST: int = 10  # Keep most recent N messages after summarize

    # ── Cloudflare R2 ─────────────────────────────────────────────────────────
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_ENDPOINT_URL: str = ""  # https://<accountid>.r2.cloudflarestorage.com
    R2_PUBLIC_URL: str = ""    # https://pub-<hash>.r2.dev or custom domain

    # ── Unacast / Gravy Analytics API ─────────────────────────────────────
    # The ONLY audience data source (app/graph/unacast_query.py). There is no
    # second backend and no synthetic fallback: an unset token disables
    # extraction, and a failed query is reported as failed, never as an
    # invented audience.
    # DIRECT-only account (no EXPORT access) — see docs/maid_unacast_integration_plan.md.
    #
    # Egress note: the vendor allowlists source IPs. Calls must leave via the
    # static Cloud NAT address <NAT_IP> (unacast-nat-ip on Cloud Router
    # unacast-router, northamerica-northeast1). A 403 "Unauthorized IP address"
    # is an infrastructure fault — see UnacastIPNotAllowlisted.
    UNACAST_API_TOKEN: str = ""
    # Defaults to staging deliberately: a deploy that forgets this variable must
    # not silently spend the production contract's monthly quota. Production is
    # an explicit opt-in via .env.
    UNACAST_ENV: str = ""   # "staging" | "production"
    # Shared, platform-wide, first-come-first-served monthly cap on the number of
    # API CALLS. Confirmed with the vendor — this resolves the integration plan's
    # open question #1, which had assumed observations-returned. The two are not
    # interchangeable: a call costs one unit whether it returns 3 observations or
    # the per-feature maximum, so admission counts calls and nothing else.
    #
    # Do NOT confuse this with the 100,000-observations-PER-SEARCH-FEATURE cap the
    # DIRECT endpoint truncates responses at. Same number, unrelated meanings:
    # that one is a data-completeness concern (observationLimitHit), not a quota.
    UNACAST_MONTHLY_CALL_BUDGET: int = 100_000
    # Confirmed account limit — one shared key, platform-wide, FCFS (no per-
    # session reservation; see UnacastConcurrencyGate).
    UNACAST_MAX_CONCURRENT_CALLS: int = 8
    # The vendor errors a request out at 190s. Sit just above it so we receive
    # the server's own error (with its reason) instead of a client-side timeout
    # that discards it. Must stay BELOW UNACAST_LEASE_STALE_AFTER_S, or a call
    # still legitimately running would have its concurrency slot reaped.
    UNACAST_REQUEST_TIMEOUT_S: float = 195.0
    # A held concurrency lease older than this is presumed abandoned (a crashed
    # request that never released) and is reaped rather than permanently
    # blocking a slot.
    #
    # Must exceed UNACAST_REQUEST_TIMEOUT_S **plus the persist budget** — the
    # lease is held across parse_response and persist_rows, not just the HTTP
    # call. At 240 the margin over a 195s request was 45s, and persisting a
    # large response could eat it; the lease would then be reaped as abandoned
    # WHILE the call was still running and the gate would over-admit. Persisting
    # is bulk now, but the margin should be sized for the whole critical
    # section rather than the request alone.
    UNACAST_LEASE_STALE_AFTER_S: int = 420
    # Local-dev escape hatch for the IP allowlist above: a SOCKS/HTTP proxy that
    # egresses from the allowlisted NAT (e.g. socks5://127.0.0.1:1080 over an IAP
    # tunnel to <TUNNEL_VM>). Empty in every deployed environment — there the
    # Cloud NAT already provides the address. Scoped to UnacastClient on purpose;
    # a global HTTPS_PROXY would drag Gemini/Places/Meta through the tunnel too.
    UNACAST_PROXY_URL: str = ""
    # Circuit breaker. A call is committed to the ledger before the request
    # returns (correct — a request that reaches the vendor consumes quota), so
    # without a breaker a vendor outage drains the shared monthly budget while
    # returning nothing. After this many consecutive failures, calls are refused
    # BEFORE any reservation until the cooldown elapses; then one probe goes
    # through, and its result closes or re-opens the breaker.
    UNACAST_BREAKER_THRESHOLD: int = 5
    UNACAST_BREAKER_COOLDOWN_S: int = 300
    # How many of the shared concurrent-call slots ONE extraction may hold.
    # Batches within an extraction used to run strictly sequentially, so 50 POIs
    # meant five DIRECT calls back to back at 20-130s each while the 8-slot gate
    # sat idle. Below UNACAST_MAX_CONCURRENT_CALLS on purpose: the gate exists
    # for fairness across users, and one extraction must not starve the rest.
    UNACAST_MAX_CONCURRENT_PER_EXTRACTION: int = 4
    # No predicted-size sizing knob and no extraction ceiling here any more.
    # A request is packed by the vendor's own legality limits only
    # (unacast_query.plan_requests: MAX_FEATURES_PER_REQUEST, MAX_RANGE_DAYS)
    # and a search is never refused for being large — a request too big for
    # the vendor to answer times out and is split smaller by
    # unacast_query._split_request, recursively, rather than pre-judged from a
    # guess. Deriving a large audience is kept memory-safe by streaming the
    # cache read (unacast_query.iter_cached) into the fold as it arrives,
    # instead of materialising every ping first — see that module's docstring.
    #
    # ── TEMPORARY: Meta-upload ID substitution (app/graph/unacast_devices.py) ──
    # Our observations/geo/search entitlement currently returns Unacast's own
    # Pseudonymized Registration ID, not a real advertising ID (GAID/IDFA), so
    # the audience built from it cannot be matched by Meta's MADID upload.
    # POST /areas/devices returns advertising IDs on this same key today.
    # Does NOT change which querier powers stats/filtering/the map — that is
    # always observations (maid_query.get_maid_querier). "areas_devices" only
    # makes executors/media.py._load_maids silently swap the upload list, at
    # the moment of publish, for real advertising IDs bought for the same
    # places over the same window — see unacast_devices.py's module
    # docstring. Flip to "observations" the day the vendor confirms
    # advertiserID mode on the observations entitlement, then delete
    # unacast_devices.py per its checklist.
    UNACAST_ID_SOURCE: str = "areas_devices"   # "areas_devices" | "observations"
    # No pre-flight feature-count ceiling here either (removed alongside the
    # observations-path one above, same reasoning): this endpoint's own
    # 20-features-per-request chunking already scales to any location-day
    # count, and the shared monthly call budget / circuit breaker / concurrency
    # gate are the real backstops against a runaway spend, not a guess about
    # what's "too big".

    # ── MAID signal-quality gate (app/graph/maid_signal.py) ───────────────
    # Every observation carries a forensicFlags bitmask. These two knobs decide
    # which pings count as evidence that a device was inside a POI's ring.
    # Both are applied CLIENT-SIDE on stored pings, so retuning them re-derives
    # an existing extraction without re-buying any vendor call.
    #
    # Measured on 287k real pings (docs/maid_signal_quality_baseline.md):
    #   off        -> 39,023 devices  (counts 14.6% drive-by and 17.8% pings
    #                                  whose accuracy band is wider than the ring)
    #   permissive -> 33,156 devices  (-15%)   <- default
    #   strict     -> 27,544 devices  (-29%)   too aggressive for a default
    #   positional -> not yet measured: distance from the ring centre plus the
    #                 band's smallest error must still fit inside the ring
    MAID_ACCURACY_MODE: str = "permissive"   # "off" | "permissive" | "positional" | "strict"
    # Flags that disqualify a ping. Empty = the vendor's documented place-visit
    # preset (SPOOF_LOCATION, OVER_CAPACITY_DEVICE, LAT_GRID_LOCATION,
    # LIKELY_DRIVING). Accepts either an integer bitmask or a comma-separated
    # list of flag names from maid_signal.FLAG_BITS.
    MAID_EXCLUDE_FLAGS: str = ""
    # Minutes between pings at one place before they count as SEPARATE visits.
    #
    # This is not a minor tuning knob — it is the single biggest lever on visit
    # counts, and `min_visits` reads straight off it. Measured on 84,473 real
    # gated pings across 17,671 (device, POI) pairs:
    #
    #     gap   5 min -> 46,137 visits (31% with measurable dwell)
    #     gap  20 min -> 30,791 visits (44%)     <- default
    #     gap  60 min -> 24,009 visits (48%)
    #     gap 120 min -> 22,279 visits (49%)
    #
    # A 2x swing end to end. 20 is the measured baseline every published number
    # in docs/maid_signal_quality_baseline.md was produced with; changing it
    # moves every audience size.
    MAID_VISIT_GAP_MINUTES: int = 20
    # Per-category overrides, "category:minutes" comma-separated — e.g.
    # "gas station:10,shopping mall:45". A two-minute forecourt stop and an
    # afternoon at a mall are not the same shape, and one global constant has to
    # be wrong for one of them. Empty by default: the categories that need their
    # own value should be set from observed data, not guessed here.
    MAID_VISIT_GAP_BY_CATEGORY: str = ""

    # Plausibility ceiling for a role-inferred (owner/staff) audience: the max
    # share of a POI's raw visitors a role predicate may keep before the read
    # is downgraded to low confidence (never refused — see
    # maid_query.role_confidence). Default derived from the synthetic
    # archetype mix (tests/maid_fixtures.py's "owner" weight is 5% of
    # devices) with 3x headroom; overridable once a real per-category ceiling
    # is measured (scripts/measure_presence_signal.py ->
    # docs/maid_role_signal_baseline.md).
    MAID_ROLE_YIELD_CEILING_PCT: float = 15.0

    # ── Scheduled maintenance (app/core/maintenance.py) ───────────────────
    # Retention windows for the two sweeps the arq worker runs daily
    # (app/worker.py). The raw window is a privacy bound on advertiser IDs. It is
    # shorter than maid_history.MAX_HISTORY_DAYS (180) on purpose: days past it
    # are swept with their coverage rows and re-bought by a later trend/cadence
    # extraction that needs them.
    UNACAST_RAW_RETENTION_DAYS: int = 90
    MAID_EXTRACTION_RETENTION_DAYS: int = 7

    # ── Frontend ──────────────────────────────────────────────────────────
    VITE_API_URL: str = "http://localhost:8000"

    # ── Stripe ──────────────────────────────────────────────
    # No defaults: these were live (test-mode) keys committed to the repo, so
    # they are in git history and must be treated as leaked and rotated. Supply
    # them via .env — an empty default fails loudly at the Stripe call rather
    # than quietly charging against whatever account was baked into the source.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    DOMAIN: str = "http://localhost:8000"
    
    FRONTEND_URL: str = "http://localhost:3001"
    # ── CORS ─────────────────────────────────────────────────
    # Comma-separated origins, e.g. "https://chat.example.com,https://api.example.com"
    ALLOWED_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8080",
        "http://localhost:5173",
        "http://localhost:5174",
        "https://chat.devst.dev",
        "https://mptaiapi.devst.dev",
        "https://punkai.devst.dev",
        "https://punk-ai-landing.vercel.app",
        "https://demo001.usepunk.ai",
        "https://punkai-landing-v3.devst.dev"
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Union[List[str], str]) -> List[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # Shared secret for the API-key guard. Was a hardcoded literal in committed
    # source, i.e. public. Set it in .env; empty means the guard has nothing to
    # compare against and must reject rather than wave callers through.
    API_KEY: str = ""
def _export_langsmith_env(s: "Settings") -> None:
    """Bridge LangSmith settings into os.environ so LangChain/LangGraph pick
    them up. pydantic loads .env into Settings only; LangChain reads os.environ.
    No-op unless tracing is enabled and an API key is present."""
    import os

    # The LANGSMITH_* fields above can be commented out to disable tracing, and
    # extra="ignore" means .env cannot supply them either — so read defensively
    # rather than blowing up the whole import (and with it the server).
    if not (getattr(s, "LANGSMITH_TRACING", False) and getattr(s, "LANGSMITH_API_KEY", "")):
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", s.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGSMITH_PROJECT", s.LANGSMITH_PROJECT)
    os.environ.setdefault("LANGSMITH_ENDPOINT", s.LANGSMITH_ENDPOINT)


settings = Settings()

_export_langsmith_env(settings)
