"""Punk's own product knowledge — facts about Punk itself, not Meta Ads.

Separate from grounding (app/graph/grounding.py), which answers public Meta
Ads questions from live web sources. Questions about Punk's own product are
answered from here instead: Google has no knowledge of Punk to ground against.
"""

from functools import lru_cache
from pathlib import Path

_KB_PATH = Path(__file__).parent / "punk_kb.md"


@lru_cache(maxsize=1)
def load_punk_kb() -> str:
    """Punk's product knowledge, read once and cached for the process lifetime."""
    return _KB_PATH.read_text(encoding="utf-8")
