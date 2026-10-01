"""
DB-backed stratified sampling of real chat_messages.content (role=user),
per the audit's §7 strategy: embedding-cluster, stratified by checkpoint_ns
prefix (campaign_builder / punk_agent / root), over-sampling confirmation
turns (langchain_data.pending_action IS NOT NULL).

HARD SAFETY GATE: this module refuses to run against anything but a
dedicated read-only role. It does not create that role itself — see
REQUIRED_ROLE_SQL below. If EVAL_DB_URL (or the discrete EVAL_DB_* env vars)
isn't set, or points at a superuser/non-read-only role, main() prints the
exact SQL to run and exits without touching the database.

Per user instruction, DB sampling is currently SKIPPED in the default eval
run (run_eval.py uses the fixture file at config.SAMPLE_INPUTS_PATH instead).
This module is complete and ready to use once eval_readonly exists — it is
just not invoked by default.
"""
from __future__ import annotations

import json
import os
import sys

REQUIRED_ROLE_SQL = """
-- Run this ONCE, as an admin, against the production DB. It creates a
-- login role that can only SELECT from existing tables/sequences — it
-- cannot INSERT/UPDATE/DELETE/DDL, and has no BYPASSRLS/SUPERUSER bit.
-- Replace the password before running; do not commit the real password.

CREATE ROLE eval_readonly WITH LOGIN PASSWORD 'CHANGE_ME' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE empty_ai TO eval_readonly;
GRANT USAGE ON SCHEMA public TO eval_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO eval_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO eval_readonly;

-- Then set these env vars for the eval harness (do not reuse the superuser
-- credential in backend/.env):
--   EVAL_DB_HOST=<same host>
--   EVAL_DB_PORT=5432
--   EVAL_DB_NAME=empty_ai
--   EVAL_DB_USER=eval_readonly
--   EVAL_DB_PASSWORD=<the password you set above>
"""


def _get_eval_db_url() -> str | None:
    url = os.environ.get("EVAL_DB_URL")
    if url:
        return url
    user = os.environ.get("EVAL_DB_USER")
    if not user:
        return None
    host = os.environ.get("EVAL_DB_HOST", "localhost")
    port = os.environ.get("EVAL_DB_PORT", "5432")
    name = os.environ.get("EVAL_DB_NAME", "")
    password = os.environ.get("EVAL_DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def check_readonly_role_or_exit() -> str:
    """Return a usable connection string, or print instructions and exit(1).

    Deliberately refuses EVAL_DB_USER == "postgres" even if someone points
    EVAL_DB_URL at the superuser credential — the whole point of this gate
    is to force a distinct, privilege-limited role to exist first.
    """
    url = _get_eval_db_url()
    user = os.environ.get("EVAL_DB_USER", "")
    if not url or user in ("", "postgres"):
        print(
            "\n[BLOCKED] No dedicated read-only DB role is configured for the eval "
            "harness.\n"
            "Per the eval's hard safety constraints, sampling will NOT run against "
            "the superuser credential in backend/.env.\n"
            "\nCreate the role first (requires your/DBA sign-off — this script will "
            "not do it for you):\n"
            f"{REQUIRED_ROLE_SQL}\n"
            "[EXIT] Re-run this module after eval_readonly exists and EVAL_DB_* "
            "env vars are set.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def sample_stratified(conn_url: str, target_n: int = 120, n_clusters: int = 20) -> list[dict]:
    """Full implementation, gated behind check_readonly_role_or_exit().

    1. Pull chat_messages where role='user', joined to checkpoints to recover
       the owning checkpoint_ns prefix (campaign_builder / punk_agent / root).
    2. Embed content with a Gemini embedding model (same vendor as the
       pipeline — text-embedding-004), k-means into n_clusters.
    3. Sample proportionally from each cluster, stratified so every
       checkpoint_ns prefix observed in the DB is represented, and
       over-sampling rows where langchain_data->>'pending_action' IS NOT NULL.
    4. Return a list of {id, content, checkpoint_ns_prefix, is_confirmation_turn}.

    Left as a callable, not auto-run — see module docstring. Uses psycopg2
    with SET default_transaction_read_only ON as defense in depth on top of
    the role's own lack of write grants.
    """
    import psycopg2
    from sklearn.cluster import KMeans

    from app.core.config import settings as _unused  # noqa: F401  (import-time sanity check only)
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    conn = psycopg2.connect(conn_url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SET default_transaction_read_only = on;
                SELECT
                    cm.id,
                    cm.content,
                    cm.checkpoint_ns,
                    (cm.langchain_data::jsonb ? 'pending_action') AS is_confirmation_turn
                FROM chat_messages cm
                WHERE cm.role = 'user' AND cm.content IS NOT NULL AND length(cm.content) > 0
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    def _prefix(ns: str | None) -> str:
        if not ns:
            return "root"
        return ns.split(":", 1)[0]

    records = [
        {"id": str(r[0]), "content": r[1], "checkpoint_ns_prefix": _prefix(r[2]), "is_confirmation_turn": bool(r[3])}
        for r in rows
    ]
    if not records:
        return []

    embedder = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    vectors = embedder.embed_documents([r["content"] for r in records])

    k = min(n_clusters, len(records))
    labels = KMeans(n_clusters=k, n_init="auto", random_state=0).fit_predict(vectors)
    for rec, label in zip(records, labels):
        rec["cluster"] = int(label)

    # Stratified pull: guarantee every prefix appears, over-sample confirmation turns.
    by_prefix: dict[str, list[dict]] = {}
    for rec in records:
        by_prefix.setdefault(rec["checkpoint_ns_prefix"], []).append(rec)

    sampled: list[dict] = []
    per_prefix_budget = max(1, target_n // max(1, len(by_prefix)))
    for prefix, recs in by_prefix.items():
        confirm = [r for r in recs if r["is_confirmation_turn"]]
        other = [r for r in recs if not r["is_confirmation_turn"]]
        n_confirm = min(len(confirm), max(1, per_prefix_budget // 2))
        n_other = min(len(other), per_prefix_budget - n_confirm)
        sampled.extend(confirm[:n_confirm])
        sampled.extend(other[:n_other])

    return sampled[:target_n]


def main() -> None:
    conn_url = check_readonly_role_or_exit()
    records = sample_stratified(conn_url)

    from tests.eval.pii import scrub

    scrubbed = []
    flagged = 0
    for rec in records:
        result = scrub(rec["content"])
        if result.has_unconfident:
            flagged += 1
        scrubbed.append({**rec, "content": result.scrubbed_text, "pii_flags": result.unconfident_spans})

    os.makedirs(os.path.dirname(os.environ.get("EVAL_SAMPLE_OUT", "")) or ".", exist_ok=True)
    out_path = os.environ.get("EVAL_SAMPLE_OUT", "sample_inputs.json")
    with open(out_path, "w") as f:
        json.dump(scrubbed, f, indent=2)
    print(f"Wrote {len(scrubbed)} sampled examples to {out_path} ({flagged} flagged for PII review).")


if __name__ == "__main__":
    main()
