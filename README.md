# Punk AI — AI-Powered Meta Ads Consultant
It is a product of Devs on Steroids LLC Company.     
company link: https://www.devsonsteroids.com/
and I am a proud member of this amazing company.
An AI advertising consultant that combines a conversational chatbot with an interactive map for geofence and POI-based audience targeting. The backend is a LangGraph agent that guides users through collecting business details, geo targets, and MAID (Mobile Advertising ID) audience data, then generates and publishes a complete Meta Ads campaign.

---

## Repo Structure
   <!-- // "backend": "cd backend && .venv\\Scripts\\python.exe -m uvicorn main:app --reload",
    "frontend": "cd frontend && npm run dev",
    "start": "concurrently \"npm run backend\" \"npm run frontend\"",
    "build:frontend": "cd frontend && npm run build",
    // "build:backend": "cd backend && .venv\\Scripts\\python.exe -m compileall .",
    "build": "npm run build:backend && npm run build:frontend",
    "test": "echo \"Error: no test specified\" && exit 1",
    "git-sync": "git add . && git commit -m \"update\"  && git fetch origin && git pull origin main &&   git push origin main",
    "prepare": "husky" -->
```
emptyad-v2/
├── backend/
│   ├── main.py                  FastAPI application entry point
│   ├── requirements.txt
│   ├── alembic/                 Database migrations
│   ├── scripts/                 Operational scripts (MAID measurement, retention sweep, chat autopilot)
│   ├── tests/
│   └── app/
│       ├── worker.py            arq worker — scheduled retention sweeps
│       ├── api/                 API Router entrypoint
│       │   └── router.py        Main APIRouter combining module routes
│       ├── core/
│       │   ├── config.py        Settings (Pydantic BaseSettings)
│       │   ├── security.py      JWT encode/decode, password hashing
│       │   ├── dependencies.py  FastAPI dependency injectors
│       │   └── logging.py       Structlog configuration
│       ├── db/
│       │   ├── seed/            Database seed data scripts
│       │   ├── models.py        Base SQLAlchemy ORM models
│       │   ├── model_registry.py Model registry for Alembic/SQLAlchemy
│       │   ├── schemas.py       Pydantic v2 request/response schemas
│       │   └── database.py      Async SQLAlchemy engine + session
│       ├── graph/               LangGraph agent
│       │   ├── graph.py         StateGraph definition + get_graph()
│       │   ├── nodes.py         All node implementations
│       │   ├── state.py         AgentState TypedDict
│       │   ├── tools.py         Geocoding, Places, search tools
│       │   ├── maid_query.py    Audience seam + visit clustering / POI attribution
│       │   ├── unacast_query.py Unacast audience querier (the only MAID source)
│       │   └── wizards/         Interactive subgraph wizards
│       │       ├── geo_wizard.py
│       │       ├── maid_wizard.py
│       │       ├── campaign_wizard.py
│       │       └── media_wizard.py
│       ├── modules/             Domain-driven feature modules (Domain, Router, Service, Schema, Models)
│       │   ├── ads/             Meta Ads OAuth + account linking
│       │   ├── analytics/       Admin dashboard analytics and statistics
│       │   ├── auditLogs/       System auditing and logging
│       │   ├── auth/            Register, login, refresh, me
│       │   ├── campaigns/       Campaign CRUD
│       │   ├── chat/            Streaming AI chat (SSE)
│       │   ├── map/             Geospatial processing and data
│       │   ├── media/           Media file upload
│       │   ├── payment/         Stripe subscription management
│       │   └── waitlist/        Waitlist capture and management
│       └── shared/
│           ├── enums.py         Shared enumerations
│           └── pagination.py    Pagination utilities
├── frontend/
│   ├── public/                  Static assets
│   ├── src/
│   │   ├── api/                 API integration and clients
│   │   ├── components/          Reusable UI components
│   │   ├── constant/            Constants and configuration
│   │   ├── contexts/            React contexts
│   │   ├── fonts/               Local fonts
│   │   ├── hooks/               Custom React hooks
│   │   ├── layouts/             Layout components
│   │   ├── lib/                 Utility functions
│   │   ├── providers/           React providers
│   │   ├── routes/              TanStack Router route definitions
│   │   ├── types/               TypeScript type definitions
│   │   ├── App.tsx              Root App component
│   │   ├── main.tsx             React entry point
│   │   ├── routeTree.gen.ts     Generated route tree
│   │   └── index.css            Global styles
│   ├── eslint.config.js         ESLint configuration
│   ├── package.json             NPM dependencies and scripts
│   └── vite.config.ts           Vite configuration
├── .env.example
└── README.md
```

---

## Tech Stack

| Layer           | Technology                                                            |
| --------------- | --------------------------------------------------------------------- |
| Web framework   | FastAPI 0.115 + Uvicorn                                               |
| AI agent        | LangGraph 1.0 + LangChain Google Generative AI (Gemini)               |
| Checkpointing   | AsyncPostgresSaver (LangGraph checkpoint-postgres)                    |
| Database        | PostgreSQL 15 via SQLAlchemy 2 async + Asyncpg                        |
| Migrations      | Alembic                                                               |
| Auth            | JWT (python-jose) + bcrypt                                            |
| Payments        | Stripe                                                                |
| Ad platform     | Meta Ads Graph API                                                    |
| Geo / Maps      | Google Geocoding API + Google Places Text Search + Nominatim fallback |
| MAID data       | Unacast / Gravy Analytics API (DIRECT), cached in PostgreSQL          |
| Search          | Gemini Search grounding (google-genai) + Tavily (raw HTTP, no SDK)    |
| Background jobs | arq on a Cloud Run worker pool (scheduled retention)                  |
| Shared state    | Redis (chat run mirror, rate limits, arq queue) — optional locally    |

---

## Backend Quick Start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

cp ../.env.example ../.env      # fill in required keys (see below)

alembic upgrade head             # create DB tables

uvicorn main:app --reload --host 0.0.0.0 --port 8000

```

Interactive API docs available at `http://localhost:8000/docs` when `DEBUG=true`.

---

## Running Locally

Three PowerShell windows, each opened at the **repo root** (the folder that holds
`backend/`, `frontend/` and `.env`). The tunnel is only needed for audience
(Unacast) data; chat, geo and publishing work without it.

The root `npm start` does not work — `package.json` has no `backend` script.

| Window | Runs | Port | Needed for |
|---|---|---|---|
| Terminal 1 | backend (uvicorn) | `8000` | everything |
| Terminal 2 | frontend (Next.js) | `3000` | everything |
| Terminal 3 | Unacast tunnel (ssh over IAP) | `1080` | audience extraction |

**Terminal 1 — backend**:

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Keep `--reload` on Windows. Without it uvicorn runs on the Proactor event loop,
which the Postgres checkpointer cannot use, and it fails to connect. Ready when it
logs `Application startup complete.`

**Terminal 2 — frontend**:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:3000`. The frontend reaches the backend through
`NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env`.

**Terminal 3 — Unacast tunnel** (leave it open while testing):

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\unacast_tunnel.ps1
```

Ready when it prints `Tunnel up on 127.0.0.1:1080 - egress <NAT_IP> (allowlisted).`
See [Unacast tunnel](#unacast-tunnel-audience-data) for what it does and the one-time setup.

**Is everything up?** From any PowerShell window:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000,3000,1080 -ErrorAction SilentlyContinue |
  Select-Object LocalPort, @{n='Process';e={(Get-Process -Id $_.OwningProcess).ProcessName}}
```

Expect `8000 python`, `3000 node`, and `1080 ssh` when the tunnel is running.

**Testing audiences locally.** Start with a 7–14 day lookback and a handful of
places. A long window over many busy places means many vendor calls and minutes of
waiting. Audience progress and errors are in `backend/logs/app.log` — search for
`Unacast:` and `MAID`.

**Shutting down.** Ctrl+C in each window, then stop the VM — Ctrl+C only closes the
tunnel, and the VM keeps billing until it is stopped:

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\unacast_tunnel.ps1 -Stop
```

### Troubleshooting

| You see | Cause | Fix |
|---|---|---|
| `never reached Unacast … ConnectError: All connection attempts failed` | Nothing is listening on `127.0.0.1:1080` — the tunnel is not running | Start Terminal 3 and wait for `Tunnel up` |
| `403 … Unauthorized IP address` | The call did not leave from `<NAT_IP>` | Run the `curl.exe` egress check below; restart the tunnel |
| "the audience data provider has failed … times in a row … Retrying in Ns" | The circuit breaker opened after repeated failures (a dead tunnel counts) | Fix the cause above, wait out the cooldown (5 min), retry |
| `127.0.0.1:1080 is already in use` | A tunnel is already running (possibly another terminal or tool) | Use that one, or close it first |
| `db keepalive failed` / first message errors after the laptop slept | The backend's database connections went stale | Ctrl+C Terminal 1 and start it again |

Your local `.env` points at the shared database, so local failures are not
isolated: an opened breaker and spent vendor calls are shared with the deployed app.

### Unacast tunnel (audience data)

Unacast only accepts calls from the allowlisted Cloud NAT address `<NAT_IP>`.
A laptop is not that address, so local calls go through the `<TUNNEL_VM>` VM:
SSH over IAP with a SOCKS proxy on `127.0.0.1:1080`. Without the tunnel, audience
extraction fails; everything else still works.

In the root `.env`:

```
UNACAST_ENV=staging
UNACAST_PROXY_URL=socks5://127.0.0.1:1080
```

How a local call travels:

```
backend (httpx, UnacastClient only) → socks5://127.0.0.1:1080
  → ssh -D on your laptop → Google IAP (your gcloud login)
  → <TUNNEL_VM> (no public IP, default VPC)
  → Cloud NAT unacast-nat → source <NAT_IP> → Unacast
```

TLS runs end to end from your laptop to Unacast; the VM only relays bytes. Only the
Unacast client uses the proxy — Gemini, Maps and Meta calls go out directly.

The script starts the VM if it is stopped, checks the egress address, and
reconnects by itself if the IAP relay drops.

Check the tunnel any time — this must print `<NAT_IP>`:

```powershell
curl.exe -s --socks5-hostname 127.0.0.1:1080 https://api.ipify.org
```

One-time prerequisites:

- `gcloud` logged in with access to project `<GCP_PROJECT>` (IAP tunnel permission).
- Windows OpenSSH (built in) and an SSH key registered on the project. Running this
  once creates `~/.ssh/google_compute_engine` and adds your key:
  `gcloud compute ssh <TUNNEL_VM> --zone=<ZONE> --project=<GCP_PROJECT> --tunnel-through-iap`
- The script logs in as your Windows username; pass `-User <name>` if your gcloud
  SSH user differs, and `-Port <n>` to use another local port (then change
  `UNACAST_PROXY_URL` to match).

Run commands from a real PowerShell window. In the Claude Code `!` prompt (bash),
backslashes are stripped — use forward slashes there, and don't start the tunnel
from it (it runs until stopped).

**Deployed (GCP) — no tunnel.** Leave `UNACAST_PROXY_URL` unset there. The Cloud Run
service `punk-ai-backend` is attached to the Serverless VPC Access connector
`unacast-vpc` with egress `all-traffic`, so every outbound call enters the `default`
VPC and leaves through the same Cloud NAT as `<NAT_IP>`:

```
Cloud Run punk-ai-backend → VPC connector unacast-vpc (all-traffic)
  → Cloud NAT unacast-nat → source <NAT_IP> → Unacast
```

The connector is set on the service itself, not in `backend/cloudbuild.yaml`
(`gcloud run services update` keeps it). A recreated or renamed service, or one in
another region, must be deployed with `--vpc-connector=unacast-vpc
--vpc-egress=all-traffic`, or every Unacast call fails with `403 Unauthorized IP address`.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values below.

### Required

| Variable                                       | Description                                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `SECRET_KEY`                                   | JWT signing key — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GCP_PROJECT_ID` / `VERTEX_LOCATION`           | Gemini LLM on Vertex via Google credentials (ADC), no API key. Default `<GCP_PROJECT>` / `global` |
| `GOOGLE_MAPS_API_KEY`                          | Geocoding API + Places Text Search                                                          |
| `META_APP_ID` / `META_APP_SECRET`              | Meta Ads platform credentials                                                              |
| `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` | Stripe billing                                                                             |
| `POSTGRES_*`                                   | PostgreSQL connection settings                                                             |
| `UNACAST_API_TOKEN`                            | Unacast/Gravy Analytics key — audience extraction is disabled without it                   |

### Optional

| Variable                                         | Description                                    |
| ------------------------------------------------ | ---------------------------------------------- |
| `TAVILY_API_KEY`                                 | Supplements Gemini Search grounding for geo/event lookups; unset just skips it, no fallback |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`   | Shares chat run state and rate limits across instances; required by the arq worker |

Audience (MAID) data comes from the Unacast/Gravy Analytics API only — live per-POI
calls in DIRECT mode, with a shared monthly call budget and a shared concurrent-call
limit, both first-come-first-served across the platform. Egress must leave via the
allowlisted static NAT address. There is no fallback source: without
`UNACAST_API_TOKEN` extraction is disabled, and a failed query is reported as failed
rather than replaced with an invented audience. Retention runs as an arq worker —
see `docs/maid_retention_runbook.md`.

---

## API Reference

All protected endpoints require `Authorization: Bearer <access_token>`.

### Authentication — `/auth`

| Method  | Path                    | Description                                 |
| ------- | ----------------------- | ------------------------------------------- |
| `POST`  | `/auth/register`        | Create a new account                        |
| `POST`  | `/auth/login`           | Login, returns access + refresh tokens      |
| `GET`   | `/auth/me`              | Get current user profile                    |
| `PATCH` | `/auth/me`              | Update profile                              |
| `POST`  | `/auth/refresh`         | Exchange refresh token for new access token |
| `POST`  | `/auth/forgot-password` | Request a password reset token              |
| `POST`  | `/auth/reset-password`  | Reset password with token                   |

### Waitlist — `/waitlist`

| Method   | Path             | Description                            |
| -------- | ---------------- | -------------------------------------- |
| `GET`    | `/waitlist`      | Get paginated list of waitlist entries |
| `POST`   | `/waitlist`      | Create a new waitlist entry            |
| `GET`    | `/waitlist/{id}` | Get specific waitlist entry            |
| `PATCH`  | `/waitlist/{id}` | Update specific waitlist entry         |
| `DELETE` | `/waitlist/{id}` | Delete specific waitlist entry         |

### Analytics — `/analytics`

| Method | Path         | Description                                                                    |
| ------ | ------------ | ------------------------------------------------------------------------------ |
| `GET`  | `/analytics` | Get aggregated admin dashboard analytics (users, conversations, subscriptions) |

### Chat — `/chat`

Streaming endpoints using **Server-Sent Events (SSE)**. Requires authentication.

| Method   | Path                              | Description                                                                 |
| -------- | --------------------------------- | --------------------------------------------------------------------------- |
| `GET`    | `/chat/threads`                   | List all chat sessions for current user (paginated)                         |
| `GET`    | `/chat/history/{thread_id}`       | Get specific conversation history                                           |
| `POST`   | `/chat`                           | Send a message; start a new session or continue an existing one             |
| `POST`   | `/chat/{session_id}/resume`       | Resume after an agent interrupt (option selection, text input, file upload) |
| `DELETE` | `/chat/thread/{thread_id}`        | Delete a specific conversation                                              |
| `PUT`    | `/chat/thread/update/{thread_id}` | Update conversation details (e.g. title, starred)                           |

**Request — `POST /chat`**

```json
{
  "message": "I want to run ads for my coffee shop",
  "session_id": "optional-uuid-to-continue-session"
}
```

**SSE event stream format**

```
data: {"type": "session_id",        "content": "<uuid>"}
data: {"type": "thinking",          "content": "Reasoning..."}
data: {"type": "assistant_message", "content": "Hi! Tell me about your business."}
data: {"type": "map_data",          "content": { ... }}
data: {"type": "pending_action",    "content": {"action_type": "option_selection", "options": [...], "prompt": "..."}}
data: {"type": "marketing_plan",    "content": { ... }}
data: {"type": "done"}
data: {"type": "error",             "content": "..."}
```

**Request — `POST /chat/{session_id}/resume`**

```json
{ "value": "deterministic" }
```

Pass the user's answer to the current `pending_action` interrupt. For `file_upload` interrupts, pass the file path returned by `/media/upload`, or `"skip"` to skip.

### Campaigns — `/campaigns`

| Method  | Path                      | Description                                                    |
| ------- | ------------------------- | -------------------------------------------------------------- |
| `GET`   | `/campaigns`              | List user campaigns (paginated, filterable by status/platform) |
| `GET`   | `/campaigns/{id}`         | Get a single campaign                                          |
| `PATCH` | `/campaigns/{id}/approve` | Approve a campaign for publishing                              |

### Media — `/media`

| Method | Path            | Description                              |
| ------ | --------------- | ---------------------------------------- |
| `POST` | `/media/upload` | Upload an image or video for ad creative |

### Ads — `/ads`

| Method | Path                 | Description                          |
| ------ | -------------------- | ------------------------------------ |
| `GET`  | `/ads/meta/connect`  | Begin Meta Ads OAuth flow            |
| `GET`  | `/ads/meta/callback` | OAuth callback — stores access token |
| `GET`  | `/ads/status`        | Check connected ad account status    |

### Subscriptions — `/subscriptions`

| Method | Path                            | Description                        |
| ------ | ------------------------------- | ---------------------------------- |
| `POST` | `/subscriptions`                | Create a subscription plan (admin) |
| `GET`  | `/subscriptions`                | List available plans               |
| `POST` | `/subscriptions/{id}/subscribe` | Subscribe current user to a plan   |

### Webhooks

| Method | Path              | Description                                |
| ------ | ----------------- | ------------------------------------------ |
| `POST` | `/webhook/stripe` | Stripe event receiver (signature verified) |

---

## LangGraph Agent Architecture

```
START → guardrail → supervisor ──► intent_extraction | knowledge_based | campaign_manager
                              ──► geo_wizard | chatbot | END
geo_wizard → maid_wizard → campaign_wizard → media_wizard → data_aggregator
knowledge_based  ──────────────────────────────────────────► data_aggregator
campaign_manager ──────────────────────────────────────────► data_aggregator
data_aggregator → chatbot → supervisor (loop)
```

**Key design points:**

- `chatbot_node` is the sole producer of all user-visible text.
- `supervisor_node` uses `Send` for parallel fan-out; `data_aggregator_node` is the fan-in convergence point.
- All user input collection uses LangGraph `interrupt()` — the graph pauses and resumes via `Command(resume=value)` from the `/chat/{id}/resume` endpoint.
- `campaign_manager` is a post-publish ReAct agent — analytics, optimization suggestions, and change application with user approval.
- All state is persisted in PostgreSQL via `AsyncPostgresSaver` — each session is a separate thread keyed by `session_id`.

### Wizard Subgraphs

Each wizard is a self-contained subgraph with its own collect → execute phases:

| Wizard            | Purpose                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| `geo_wizard`      | Collect location scope, POI type, targeting method; geocode and search Places |
| `maid_wizard`     | Extract MAIDs from the Unacast API for deterministic targeting                |
| `campaign_wizard` | Collect website URL, Meta pixel, budget, dates, and confirm                   |
| `media_wizard`    | Collect ad creative files and publish to Meta Ads API                         |

### Audience (MAID) data

Unacast only. `app/graph/unacast_query.py` buys raw pings per POI (a Point plus a
radius, at most 10 features per request), caches them in PostgreSQL behind a
per-(POI, day) watermark, and `app/graph/maid_query.py` folds them into visits and
attributes them to POIs by the feature id the vendor returns them under.

---

## Running Tests

```bash
# All tests
cd backend && pytest

# Single test file
python -m backend.tests.test_geo_agent_interactive

# Preset scenario (interactive)
python -m backend.tests.test_geo_agent_interactive --scenario pet_shop

# Auto-answer all interrupts
python -m backend.tests.test_geo_agent_interactive --scenario pet_shop --quick

# Skip real API calls
python -m backend.tests.test_geo_agent_interactive --dry-run
```

All test commands must be run from the repo root (`emptyad-v2/`).

---

## Database Migrations

```bash
cd backend

# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# run seed
python -m app.db.seed.seed
# Rollback one step
alembic downgrade -1
```
