"""
graph/narrator/prompts
──────────────────────
Prompt fragments for the Narrator v3 composer.

The LIVE composer builds its own messages in
:func:`app.graph.narrator.composer._build_messages` from just two modules here:

  • :mod:`base`     — shared PERSONA / PLAIN_WORDS_RULE / CONTINUITY_RULE / forbidden terms.
  • :mod:`composer` — COMPOSE_RULE + EXEMPLARS + OUTPUT_RULE + beat hints.

The former per-role prompt machinery (``build_messages`` + the ``roles/`` package)
belonged to the retired v2 "one message per role" design and was never called by
the v3 composer. It was removed so copy edits can't silently land on dead code —
put voice/exemplar changes in :mod:`composer` (the live prompt) instead.
"""

from __future__ import annotations
