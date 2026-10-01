"""
graph/narrator/post_process.py
──────────────────────────────
Deterministic jargon guardrail for narrator + chatbot output.

No LLM calls — a pure string transform, safe to run in replay-sensitive paths.
"""

from __future__ import annotations

import re

# Banned-jargon scrubber. Best-effort guardrail: if the LLM slips a banned term
# despite the system prompt + forbidden_terms, swap it for the plain-words
# equivalent before emit. Order matters — longer multi-word phrases first.
# Ported verbatim from wizard_helpers so behaviour is identical, then shared.
#
# Trimmed to TRULY-INTERNAL jargon only. The previous list also rewrote valid
# marketing copy ("ad creative", "impressions", "CPM", "custom audience"),
# which flattened legitimate, user-friendly language. Those are kept as-is now;
# only Punk-internal plumbing terms users would never recognise are swapped.
_JARGON_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdeterministic targeting\b", re.I), "real-visitor targeting"),
    (re.compile(r"\bprogrammatic targeting\b", re.I), "broad reach"),
    (re.compile(r"\bpoint[s]? of interest\b", re.I), "spots"),
    (re.compile(r"\bPOIs?\b"), "spots"),
    (re.compile(r"\bmobile ad ID[s]?\b", re.I), "real visitors"),
    (re.compile(r"\bMAIDs?\b"), "real visitors"),
    (re.compile(r"\bgeofence[sd]?\b", re.I), "ring around the place"),
    (re.compile(r"\blookback window\b", re.I), "how recent the visit was"),
]


def scrub_jargon(text: str) -> str:
    """Swap any banned jargon term for its plain-words equivalent."""
    out = text or ""
    for pat, repl in _JARGON_REPLACEMENTS:
        out = pat.sub(repl, out)
    return out


__all__ = ["scrub_jargon"]
