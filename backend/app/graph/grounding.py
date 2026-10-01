"""Gemini Search/Maps grounding — live web answers via the google-genai SDK.

Moved out of tools.py (a geo-focused module) so builder executors and other
non-geo callers (enrich_website, competitor discovery, knowledge retrieval,
campaign_manager) can import grounding without pulling in the geo module or
risking an import cycle.

Grounding is a Gemini MODEL feature (not the agent platform), reached via the
google-genai SDK with the same auth as the LLM (settings.genai_auth) — NOT reachable through
ChatGoogleGenerativeAI / bind_tools, so every caller is this one out-of-band
raw-SDK call. Gated by settings.GROUNDING_ENABLED; never raises — callers
always get a str (possibly "") and degrade accordingly.
"""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.graph.usage import record_api_call, record_grounding_usage

logger = logging.getLogger(__name__)

# A grounded call runs a live search AND a generation, so it is slower than a
# bare LLM call — but it still needs a ceiling: without one a hung request stalls
# the caller indefinitely (every other network path in this codebase caps at
# 10-15s). On timeout the call degrades like any other failure.
_GROUNDING_TIMEOUT_MS = 30_000


@lru_cache(maxsize=1)
def _grounding_client():
    """Reused google-genai client. Rebuilding it per call redid client setup on
    every name × location of the resolve loop. Auth comes from settings.genai_auth
    (Vertex ADC or the AI Studio key); ADC refreshes its own token, so there is no
    rotated-credential case to key the cache on."""
    from google import genai
    from google.genai import types

    return genai.Client(
        **settings.genai_auth,
        http_options=types.HttpOptions(timeout=_GROUNDING_TIMEOUT_MS),
    )


async def grounded_text(
    prompt: str,
    *,
    use_maps: bool = False,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    with_sources: bool = False,
    with_metadata: bool = False,
    max_sources: int = 3,
) -> str | tuple[str, List[str]] | tuple[str, List[str], float]:
    """Query Gemini with Google Search (or Maps) grounding; return its text.

    Replaces the weak Tavily/web tails in ``search_events`` and
    ``resolve_named_target``'s novel-name fallback. Never raises — returns ""
    (or ("", []) with with_sources=True) so callers degrade to their legacy path.

    ``use_maps`` attempts Google Maps grounding first (better for place→coord) and
    falls back to Search grounding when Maps is unavailable OR returns nothing.
    ``latitude``/``longitude`` anchor Maps grounding to the search area — without
    them a bare name resolves against the whole planet.

    ``with_sources=True`` also returns up to ``max_sources`` grounding source URLs
    (from ``grounding_metadata``), so a caller that shows its answer to a user
    (e.g. knowledge retrieval) can cite them instead of asserting web-sourced
    facts with no attribution.

    ``with_metadata=True`` returns ``(text, sources, supported_ratio)``: the share
    (0-1) of the answer that ``grounding_supports`` ties to a retrieved source. A
    low ratio means the model answered mostly from memory while looking grounded.

    Every call carries today's date as a system instruction, so relative phrases
    ("last month", "currently") resolve against the real date, not the model's.
    """
    empty: Any = ("", [], 0.0) if with_metadata else (("", []) if with_sources else "")
    if not settings.GROUNDING_ENABLED:
        return empty
    try:
        from google import genai  # noqa: F401  (import guard for the SDK)
        from google.genai import types
    except ImportError:
        logger.warning("grounding: google-genai SDK not installed")
        return empty

    client = _grounding_client()

    def _config(tools: list, *, anchor: bool) -> Any:
        kwargs: Dict[str, Any] = {
            "tools": tools,
            "temperature": 0.0,
            "system_instruction": f"Today's date is {date.today().isoformat()}.",
        }
        # The lat/lng anchor rides on retrieval_config, which is a Maps-grounding
        # input — Search grounding has no use for it, so it is opt-in per arm.
        if anchor and latitude is not None and longitude is not None:
            kwargs["tool_config"] = types.ToolConfig(
                retrieval_config=types.RetrievalConfig(
                    lat_lng=types.LatLng(latitude=latitude, longitude=longitude),
                )
            )
        return types.GenerateContentConfig(**kwargs)

    def _metadata(resp: Any) -> Any:
        try:
            return resp.candidates[0].grounding_metadata
        except (AttributeError, IndexError, TypeError):
            return None

    def _extract_sources(resp: Any) -> List[str]:
        if not (with_sources or with_metadata):
            return []
        chunks = getattr(_metadata(resp), "grounding_chunks", None) or []
        urls: List[str] = []
        for chunk in chunks:
            uri = getattr(getattr(chunk, "web", None), "uri", None)
            if uri and uri not in urls:
                urls.append(uri)
            if len(urls) >= max_sources:
                break
        return urls

    def _supported_ratio(resp: Any, text: str) -> float:
        """Share of the answer's bytes covered by any grounding support segment.
        Segment indices are byte offsets into the response text."""
        if not with_metadata or not text:
            return 0.0
        n = len(text.encode("utf-8"))
        covered = bytearray(n)
        for sup in getattr(_metadata(resp), "grounding_supports", None) or []:
            seg = getattr(sup, "segment", None)
            start = int(getattr(seg, "start_index", 0) or 0)
            end = min(int(getattr(seg, "end_index", 0) or 0), n)
            if end > start:
                covered[start:end] = b"\x01" * (end - start)
        return sum(covered) / n

    _model = settings.GROUNDING_MODEL or settings.GEMINI_MODEL

    async def _run(
        tools: list, *, anchor: bool = False, api_label: str = "grounding_search",
    ) -> tuple[str, List[str], float]:
        resp = await client.aio.models.generate_content(
            model=_model,
            contents=prompt,
            config=_config(tools, anchor=anchor),
        )
        # Recorded per ARM, not per call: a Maps miss that falls through to Search
        # is two billed requests and must count as two. Raw-SDK calls are invisible
        # to LangChain's usage callback, so without this they reach AgentState as 0.
        record_grounding_usage(_model, getattr(resp, "usage_metadata", None))
        record_api_call(api_label)
        text = (getattr(resp, "text", "") or "").strip()
        ratio = _supported_ratio(resp, text)
        if with_metadata:
            logger.info("grounding: %d source(s), %.0f%% of answer supported", len(_extract_sources(resp)), ratio * 100)
        return text, _extract_sources(resp), ratio

    def _finish(text: str, sources: List[str], ratio: float) -> Any:
        if with_metadata:
            return text, sources, ratio
        return (text, sources) if with_sources else text

    if use_maps:
        # Empty is the COMMON Maps miss (a 200 with no usable text), not an
        # exception — so falling through only on a raise meant Search grounding
        # never ran in the case it exists for.
        try:
            text, sources, ratio = await _run(
                [types.Tool(google_maps=types.GoogleMaps())], anchor=True, api_label="grounding_maps",
            )
            if text:
                return _finish(text, sources, ratio)
            logger.info("grounding: Maps grounding returned nothing — using Search")
        except Exception as exc:
            logger.info("grounding: Maps grounding unavailable (%s) — using Search", exc)
    try:
        text, sources, ratio = await _run([types.Tool(google_search=types.GoogleSearch())])
        return _finish(text, sources, ratio)
    except Exception as exc:
        logger.warning("grounding: Search grounding failed: %s", exc)
        return empty
