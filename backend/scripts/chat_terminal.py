"""
Punk AI — Terminal Chatbot

Run from repo root:
    python -m backend.scripts.chat_terminal
    python -m backend.scripts.chat_terminal --url http://localhost:8000
    python -m backend.scripts.chat_terminal --email me@ex.com --password secret

Credentials fall back to env vars TEST_EMAIL / TEST_PASSWORD.
Press Ctrl+C to quit.

Lives in scripts/, not tests/: it is an interactive client, not a test. Named
``test_chat_terminal.py`` it was collected by pytest, and the stdout rebinding
below runs at import — which detached pytest's capture and crashed the whole
run with "I/O operation on closed file" before a single test executed.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from typing import Optional

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import httpx
except ImportError:
    print("httpx not installed.  pip install httpx")
    sys.exit(1)


DEFAULT_URL      = "http://localhost:8000"
DEFAULT_EMAIL    = os.getenv("TEST_EMAIL",    "user@example.com")
DEFAULT_PASSWORD = os.getenv("TEST_PASSWORD", "PunkAI02")


# ── Colours ────────────────────────────────────────────────────────────────────

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    MAGENTA = "\033[95m"
    RED     = "\033[91m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + C.RESET


# ── Streaming text ─────────────────────────────────────────────────────────────

def _stream_print(text: str, indent: str = "           ", delay: float = 0.022) -> None:
    """Print word-by-word to simulate token streaming. Handles embedded newlines."""
    tokens = text.split(" ")
    for i, token in enumerate(tokens):
        if "\n" in token:
            parts = token.split("\n")
            for j, part in enumerate(parts):
                print(part, end="", flush=True)
                if j < len(parts) - 1:
                    print()
                    print(indent, end="", flush=True)
        else:
            print(token, end="", flush=True)
        if i < len(tokens) - 1:
            print(" ", end="", flush=True)
        time.sleep(delay)
    print()


# ── SSE parser ─────────────────────────────────────────────────────────────────

def _iter_sse(response: httpx.Response):
    for line in response.iter_lines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    pass


# ── Auth ───────────────────────────────────────────────────────────────────────

def _get_token(client: httpx.Client, base: str, email: str, password: str) -> str:
    r = client.post(f"{base}/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["access_token"]

    reg = client.post(f"{base}/auth/register", json={
        "email": email, "password": password, "full_name": "Dev Tester",
    })
    if reg.status_code not in (200, 201, 400):
        print(_c(f"Auth failed: {reg.status_code} {reg.text}", C.RED))
        sys.exit(1)

    r2 = client.post(f"{base}/auth/login", json={"email": email, "password": password})
    if r2.status_code != 200:
        print(_c(f"Login failed: {r2.status_code} {r2.text}", C.RED))
        sys.exit(1)
    return r2.json()["access_token"]


# ── Event renderers ────────────────────────────────────────────────────────────

_BOX_W = 48  # inner width for info boxes


def _print_map(content: dict) -> None:
    if not isinstance(content, dict):
        return
    print()
    print(_c("\n  ┌─ MAP DATA ────────────────────────────────┐", C.BLUE))
    print(json.dumps(content, indent=2))
    print(_c("  └────────────────────────────────────────────┘\n", C.BLUE))


def _print_plan(content: dict) -> None:
    sep = "─" * _BOX_W
    print()
    print(_c(f"  ┌─ CAMPAIGN PLAN {sep[16:]}", C.MAGENTA))
    if isinstance(content, dict):
        keys = ("campaign_name", "objective", "budget_usd", "targeting_summary",
                "audience_size", "ad_format")
        for key in keys:
            if key in content:
                label = key.replace("_", " ").title()
                val   = str(content[key])[:38]
                print(_c(f"  │  {label:<18}: {val}", C.MAGENTA))
    print(_c(f"  └{sep}", C.MAGENTA))


# ── Pending action (interrupt prompt) ─────────────────────────────────────────

def _ask(action: dict) -> str:
    atype   = action.get("action_type", "text_input")
    prompt  = action.get("prompt", "Input:")
    options = action.get("options", [])
    prefill = action.get("prefill")
    field   = action.get("field", "input")

    # Display full action structure as JSON
    print()
    print(_c("\n  ┌─ PENDING ACTION ──────────────────────────┐", C.YELLOW))
    print(json.dumps(action, indent=2))
    print(_c("  └────────────────────────────────────────────┘\n", C.YELLOW))

    # Handle input based on action type
    if atype == "option_selection" and options:
        for i, opt in enumerate(options, 1):
            print(_c(f"  {i}. {opt}", C.YELLOW))
        print()
        while True:
            raw = input(_c("  ›  ", C.CYAN)).strip()
            if not raw and prefill:
                return prefill
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            if raw in options:
                return raw
            print(_c("  Enter valid number or text.", C.RED))

    elif atype == "permission":
        raw = input(_c("  yes / no  ›  ", C.CYAN)).strip().lower()
        return raw if raw in ("yes", "no") else "yes"

    elif atype == "map_interaction":
        print(_c("  (lat,lng or Enter to skip)", C.DIM))
        return input(_c("  ›  ", C.CYAN)).strip() or "skip"

    elif atype == "file_upload":
        print(_c("  (path or Enter to skip)", C.DIM))
        return input(_c("  ›  ", C.CYAN)).strip() or "skip"

    elif atype == "oauth_connect":
        input(_c("  Press Enter after connecting  ›  ", C.CYAN))
        return "connected"

    else:  # text_input
        if prefill:
            print(_c(f"  (pre-filled: {prefill}  — Enter to accept)", C.DIM))
        raw = input(_c("  ›  ", C.CYAN)).strip()
        return raw if raw else (prefill or "")


# ── One streaming round ────────────────────────────────────────────────────────

_AI_PREFIX    = _c("  AI  ›  ", C.GREEN, C.BOLD)
_AI_INDENT    = "           "   # same width as prefix for wrapped lines


def _stream_round(
    client: httpx.Client,
    base: str,
    session_id: Optional[str],
    body: dict,
    is_resume: bool = False,
) -> tuple[str, Optional[dict]]:
    """
    Stream one agent round. Returns (session_id, pending_action | None).
    Renders assistant message, map data, pending actions, and marketing plan.
    """
    url     = f"{base}/chat/{session_id}/resume" if is_resume else f"{base}/chat"
    sid     = session_id or ""
    pending: Optional[dict] = None
    ai_open = False

    with client.stream("POST", url, json=body, timeout=180) as resp:
        if resp.status_code != 200:
            body_text = resp.read().decode()[:300]
            print(_c(f"\n  HTTP {resp.status_code}: {body_text}", C.RED))
            return sid, None

        for event in _iter_sse(resp):
            etype   = event.get("type")
            content = event.get("content", "")

            if etype == "session_id":
                sid = content

            elif etype == "assistant_message":
                if not ai_open:
                    print()
                    print(_AI_PREFIX, end="", flush=True)
                    ai_open = True
                _stream_print(str(content), indent=_AI_INDENT, delay=0.022)
                ai_open = False

            elif etype == "map_data":
                _print_map(content)

            elif etype == "marketing_plan":
                _print_plan(content)

            elif etype == "pending_action":
                pending = content

            elif etype == "error":
                print(_c(f"\n  ✗  {content}", C.RED))

            # skip: thinking, done

    return sid, pending


# ── Main chat loop ─────────────────────────────────────────────────────────────

def _chat_loop(client: httpx.Client, base: str) -> None:
    print()
    print(_c("  ╔══════════════════════════════════════════╗", C.CYAN))
    print(_c("  ║        PUNK AI  ·  Terminal Chat         ║", C.CYAN))
    print(_c("  ╚══════════════════════════════════════════╝", C.CYAN))
    print()
    print(_c("  Type a message and press Enter. Ctrl+C to quit.", C.DIM))

    session_id: Optional[str] = None

    while True:
        try:
            print()
            user_msg = input(_c("  You  ›  ", C.WHITE, C.BOLD)).strip()
            if not user_msg:
                continue
        except (KeyboardInterrupt, EOFError):
            print(_c("\n  Bye.\n", C.DIM))
            break

        body: dict = {"message": user_msg}
        if session_id:
            body["session_id"] = session_id

        try:
            sid, pending = _stream_round(client, base, session_id, body)
            session_id = sid

            # Drain all sequential interrupts before returning to the user
            while pending is not None:
                answer = _ask(pending)
                sid, pending = _stream_round(
                    client, base, session_id,
                    {"value": answer}, is_resume=True,
                )
                session_id = sid

        except KeyboardInterrupt:
            print(_c("\n  Bye.\n", C.DIM))
            break
        except Exception as exc:
            print(_c(f"\n  [client error] {exc}", C.RED))


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Punk AI terminal chatbot")
    parser.add_argument("--url",      default=DEFAULT_URL,      help="API base URL  (default: %(default)s)")
    parser.add_argument("--email",    default=DEFAULT_EMAIL,    help="Login email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Login password")
    args = parser.parse_args()

    with httpx.Client(timeout=180) as client:
        token = _get_token(client, args.url.rstrip("/"), args.email, args.password)
        client.headers["Authorization"] = f"Bearer {token}"
        _chat_loop(client, args.url.rstrip("/"))


if __name__ == "__main__":
    main()
