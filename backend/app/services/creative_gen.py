"""
app/services/creative_gen.py
────────────────────────────
FUTURE WORK (Post-Version 1):
Ad creative image generation via Gemini Developer API (gemini-2.5-flash-image)
is disconnected for Version 1 and scheduled for a future release.

In Version 1, users supply ad creatives by uploading media assets directly or
by selecting existing posts from their connected Facebook Pages / Instagram accounts.

---
Original Architecture (Preserved for Future Work):
One round renders SEVERAL variants (default 3) concurrently, each pinned to a
different concept archetype, so the user chooses between genuinely distinct takes
on their business. Each variant runs the same three passes:
  1. Art Director (LLM) — reasons over the generated campaign plan + business
     identity and invents ONE cinematic, product-forward CONCEPT.
  2. Prompt Writer (LLM) — turns that concept into one vivid text-to-image prompt.
  3. Image render — the Gemini image model (``gemini-2.5-flash-image``) renders it
     at a Meta-compliant aspect ratio (default 1:1) and high resolution (2K).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class CreativeGenError(RuntimeError):
    """Generation failed — surfaced to the job row as ``status="failed"``."""


# Pass 1 — the art creative director / cinematographer. Invents the CONCEPT.
_ART_DIRECTOR_SYSTEM = (
    "You are an award-winning advertising art director and cinematographer. Given a "
    "business and its campaign plan, invent ONE cinematic photographic concept for a "
    "high-performing Meta ad. Hard rules:\n"
    "- BRAND-UNMISTAKABLE: the business's actual product, service, or world is "
    "instantly recognizable as THIS business — never a generic or abstract stock "
    "image. Whether the product is a centred hero, a styled detail, or set within a "
    "scene is decided by the ART-DIRECTION BRIEF below, not defaulted.\n"
    "- SUBJECT VARIETY: do NOT default to a single centred human model. Follow the "
    "ART-DIRECTION BRIEF for how many people (if any) appear — many strong concepts "
    "have no people at all (product still-life, macro detail, environment). People "
    "are optional.\n"
    "- CINEMATIC: filmic lighting, intentional composition, shallow depth of field, "
    "a real photographic look (not illustration, not 3D render unless the business is that).\n"
    "- The audience persona informs the MOOD, styling, and context of the shot — it "
    "need NOT be rendered as a literal single person.\n"
    "- LOCATION-TRUE: when the plan carries a target_market or target_places (the "
    "city/venues the ads target), SET the shot there — make the environment read "
    "unmistakably as that place and the audience's context (e.g. beachgoers at the "
    "beach), never a neutral studio backdrop.\n"
    "- NO text, words, letters, or logos anywhere in the image (ad copy is overlaid "
    "separately).\n"
    "Honour the ART-DIRECTION BRIEF supplied with the plan — it sets the composition "
    "and subject approach for THIS render.\n"
    "Respond with STRICT JSON only (no prose, no code fences) matching:\n"
    "{\n"
    '  "hero": "the concrete focal subject of the shot, per the art-direction brief",\n'
    '  "scene": "what is happening in the shot",\n'
    '  "setting": "location / environment",\n'
    '  "mood": "emotional tone matching the strategic insight",\n'
    '  "lighting": "cinematic lighting description",\n'
    '  "lens": "focal length / depth of field",\n'
    '  "composition": "framing / angle",\n'
    '  "color_palette": "on-brand palette",\n'
    '  "why_it_fits_business": "one sentence tying it to THIS business and audience"\n'
    "}"
)

# Pass 2 — turns the concept into the final render prompt.
_PROMPT_WRITER_SYSTEM = (
    "You are a prompt engineer for a text-to-image ad-creative model. Turn the given "
    "creative concept (JSON) into ONE vivid prompt. Output a single paragraph — no "
    "preamble, no quotes, no lists. LEAD with the hero subject, then fold in the setting, "
    "mood, lighting, lens/depth-of-field, composition and colour palette. Make it "
    "photorealistic, cinematic and ad-campaign quality. Do NOT render any text, words, "
    "letters, or logos in the visual (ad copy is overlaid separately)."
)


# Concept archetypes — a DISTINCT one per variant in a round (and a fresh sample
# per regeneration) so the images diverge instead of converging on the "single
# model wearing the product" cliché. Each varies the subject count and
# composition; the LLM adapts the archetype to the real product.
_CONCEPT_ARCHETYPES: list[tuple[str, str]] = [
    (
        "product_hero",
        "PRODUCT STILL-LIFE / FLAT-LAY — the product itself is the sole hero, "
        "styled as a hero object with NO people in frame. Think tabletop / flat-lay "
        "with tasteful props that signal the brand world.",
    ),
    (
        "detail_macro",
        "MACRO DETAIL — an extreme close-up of the product's texture, print, "
        "material or craftsmanship. At most a hand interacting with it; no full "
        "human figure. Sensory and tactile.",
    ),
    (
        "environmental",
        "ENVIRONMENTAL / SENSE-OF-PLACE — the target location or scene is the hero; "
        "the product appears naturally within it, not dominating the frame. People "
        "are incidental or absent. Wide, atmospheric.",
    ),
    (
        "lifestyle_candid",
        "LIFESTYLE CANDID — ONE real person authentically using or wearing the "
        "product in the target context, caught candid and unposed (not staring at "
        "camera). Natural, documentary feel.",
    ),
    (
        "social_scene",
        "SOCIAL SCENE — a small group of 2–3 people sharing the moment together, "
        "the product worn/used across them. Warm social energy, connection, motion.",
    ),
    (
        "editorial_bold",
        "BOLD EDITORIAL — high-fashion editorial treatment: dramatic angle, graphic "
        "composition, bold colour-blocking, the product as a confident style "
        "statement. Striking and stylised (still photographic, not illustration).",
    ),
]


# A user reference image pins the product identity, so those renders stay in the
# faithful product-forward lane rather than a no-product / sense-of-place archetype.
_REFERENCE_SAFE_ARCHETYPES = {
    "lifestyle_candid", "product_hero", "detail_macro", "editorial_bold",
}


def _pick_archetypes(count: int, has_reference: bool) -> list[tuple[str, str]]:
    """``count`` DISTINCT concept archetypes for one generation round.

    Distinct (``random.sample``, not repeated ``choice``) so the three variants a
    user picks between are genuinely different takes rather than three near-copies;
    still random per round so a regeneration lands on a fresh set.
    """
    pool = [
        a for a in _CONCEPT_ARCHETYPES
        if not has_reference or a[0] in _REFERENCE_SAFE_ARCHETYPES
    ]
    return random.sample(pool, min(count, len(pool)))


def _client() -> Any:
    """Lazy ``google-genai`` client.

    Built here (not at import) so a missing SDK or credential only errors when
    generation is actually attempted — app startup stays clean when
    ``CREATIVE_GEN_ENABLED`` is off. Uses the same auth as the LLM
    (``settings.genai_auth``): Vertex ADC, or the AI Studio key.
    """
    if not settings.CREATIVE_GEN_ENABLED:
        raise CreativeGenError(
            "Creative image generation is disabled in Version 1 (future work). "
            "Please upload media assets or select existing Page posts."
        )
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - dep guard
        raise CreativeGenError("google-genai SDK not installed.") from exc
    return genai.Client(**settings.genai_auth)


def _strip_json_fences(text: str) -> str:
    """Drop ```json / ``` fences an LLM sometimes wraps a JSON answer in."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
    return t.strip().removeprefix("json").strip()


def _business_facts(context: dict) -> dict:
    """Business identity + campaign-plan creative context for the art director.

    ``user_info`` is thin but authoritative on WHO the business is; the generated
    campaign brief carries the rich creative context (persona, insight, format,
    copy). Keys here match the REAL state keys (``business_description``,
    ``product_offer``, ``campaign_objective`` — not the shorthand the old composer
    guessed at, which silently resolved to None and starved the prompt).
    """
    brief = context.get("brief") or {}
    ui = context.get("user_info") or {}
    geo = context.get("geo") or {}

    # Location signal: the concrete market ("Miami") + a few real venue POIs
    # (beaches / surf shops / bars) so the scene is set where the ad TARGETS —
    # not the abstract ``targeting_type`` scope token, which is meaningless as
    # visual guidance and was the only geo field reaching the prompt before.
    locations = geo.get("locations") or []
    first_loc = locations[0] if locations else {}
    target_market = first_loc.get("location_name") or first_loc.get("formatted_address")
    target_places = [
        p.get("name") for p in (geo.get("targetable_pois") or [])[:6] if p.get("name")
    ] or None

    facts = {
        # Business identity anchor (authoritative on WHO)
        "business_name": ui.get("business_name"),
        "business_description": ui.get("business_description"),
        "industry": ui.get("industry"),
        "product_offer": ui.get("product_offer") or brief.get("product_offer"),
        "campaign_objective": ui.get("campaign_objective") or brief.get("objective"),
        # Generated campaign plan — the rich creative context (was being ignored)
        "campaign_name": brief.get("campaign_name"),
        "objective_label": brief.get("objective_label"),
        "strategic_insight": brief.get("strategic_insight"),
        "audience_persona": brief.get("audience_persona"),
        "audience_summary": brief.get("audience_summary"),
        "creative_format": brief.get("creative_format"),
        "headline": (brief.get("headline_suggestions") or [None])[0],
        "body_copy": (brief.get("body_copy_suggestions") or [None])[0],
        # WHERE the ad targets — drives the setting of the shot
        "target_market": target_market,
        "target_places": target_places,
        "targeting_hint": geo.get("targeting_type"),
    }
    return {k: v for k, v in facts.items() if v}


def _fallback_concept(facts: dict) -> dict:
    """Deterministic product-forward concept so a Pass-1 failure never blocks."""
    biz = facts.get("business_name") or "the business"
    hero = facts.get("product_offer") or facts.get("business_description") or f"{biz}'s product"
    return {
        "hero": hero,
        "scene": f"{hero} presented as the centrepiece of a polished advertising shot",
        "setting": facts.get("industry") or "a clean, on-brand environment",
        "mood": "aspirational and inviting",
        "lighting": "soft cinematic natural light with gentle rim highlights",
        "lens": "50mm, shallow depth of field",
        "composition": "rule-of-thirds, hero in sharp focus, background softly blurred",
        "color_palette": "warm, on-brand tones",
        "why_it_fits_business": f"Puts {biz}'s offering front and centre.",
    }


async def _art_direct_concept(
    context: dict,
    media_type: str,
    variation_hint: Optional[str],
    has_reference: bool,
    archetype: Optional[tuple[str, str]] = None,
) -> dict:
    """Pass 1 — art director invents a cinematic, product-forward concept (JSON).

    Never raises: on LLM error or unparseable JSON, returns a deterministic
    product-forward concept built from the business facts.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.graph.wizard_helpers import _make_llm

    facts = _business_facts(context)
    archetype_name, archetype_brief = (
        archetype or _pick_archetypes(1, has_reference)[0]
    )
    # Visibility: an empty/thin facts set is the tell-tale of context not reaching
    # the prompt (e.g. subgraph state not read) → a generic, off-target creative.
    # The archetype is logged so the chosen variety is observable/reproducible.
    logger.info(
        "creative_gen: art-director facts keys=%s archetype=%s",
        sorted(facts.keys()), archetype_name,
    )
    parts = [
        "Business & campaign plan:\n" + json.dumps(facts, indent=2),
        "ART-DIRECTION BRIEF for THIS render (differs each time — commit to it):\n"
        + archetype_brief,
    ]
    if has_reference:
        parts.append(
            "A reference PRODUCT image is provided separately — make that exact product "
            "the hero of the concept; keep it faithful (shape, label, colours)."
        )
    if variation_hint:
        # The user's explicit art direction overrides the rotated archetype where
        # they conflict (they asked for something specific).
        parts.append(
            f"Extra art direction from the user (takes priority over the brief above): "
            f"{variation_hint}"
        )
    parts.append("Return the concept JSON now.")
    user = "\n\n".join(parts)

    try:
        llm = _make_llm(temperature=0.9, model=settings.GEMINI_MODEL_PRO)
        resp = await llm.ainvoke(
            [SystemMessage(content=_ART_DIRECTOR_SYSTEM), HumanMessage(content=user)]
        )
        concept = json.loads(_strip_json_fences(resp.content or ""))
        if isinstance(concept, dict) and concept.get("hero"):
            return concept
        logger.warning("creative_gen: art-director JSON missing 'hero' — using fallback")
    except Exception as exc:  # never block generation on the art director
        logger.warning("creative_gen: art-director pass failed, using fallback: %s", exc)
    return _fallback_concept(facts)


async def _concept_to_prompt(
    concept: dict,
    has_reference: bool,
    variation_hint: Optional[str],
) -> str:
    """Pass 2 — turn the concept JSON into one vivid render prompt.

    Never raises: on LLM error, deterministically stitches the concept fields.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.graph.wizard_helpers import _make_llm

    user = "Creative concept:\n" + json.dumps(concept, indent=2) + "\n\nWrite the image prompt now."
    text = ""
    try:
        llm = _make_llm(temperature=0.8, model=settings.GEMINI_MODEL_PRO)
        resp = await llm.ainvoke(
            [SystemMessage(content=_PROMPT_WRITER_SYSTEM), HumanMessage(content=user)]
        )
        text = (resp.content or "").strip()
    except Exception as exc:  # never block generation on the prompt writer
        logger.warning("creative_gen: prompt-writer pass failed, stitching concept: %s", exc)
    if not text:
        text = (
            f"{concept.get('hero', 'the product')} as the hero of "
            f"{concept.get('scene', 'a polished advertising shot')}, "
            f"{concept.get('setting', '')}, {concept.get('mood', '')} mood, "
            f"{concept.get('lighting', 'cinematic lighting')}, {concept.get('lens', '')}, "
            f"{concept.get('composition', '')}, {concept.get('color_palette', '')}. "
            "Photorealistic, cinematic, ad-campaign quality. No text, words, or logos."
        )
    if variation_hint:
        # Reinforce the user's art direction on the render prompt directly, so it
        # survives even when Pass 1 fell back to a deterministic concept (LLM hiccup).
        text += f" Additional art direction: {variation_hint}."
    if has_reference:
        # The reference is the concept's hero — keep the product itself faithful
        # while placing it into the cinematic scene above (never a plain reframe).
        text += (
            " Treat the provided reference image as the product to feature. Keep the "
            "product itself faithful (shape, label, colours), but place it into the "
            "cinematic advertising scene described above."
        )
    return text


async def compose_visual_prompt(
    context: dict,
    media_type: str,
    variation_hint: Optional[str] = None,
    has_reference: bool = False,
    archetype: Optional[tuple[str, str]] = None,
) -> str:
    """Two-pass art-director agent → a cinematic, business-grounded render prompt.

    Pass 1 (art director) invents a product-forward concept from the generated
    campaign plan; Pass 2 (prompt writer) renders that concept into one vivid
    text-to-image prompt. Both passes fall back gracefully so generation never
    blocks on an LLM hiccup (mirrors the narrator's never-raise convention).
    """
    concept = await _art_direct_concept(
        context, media_type, variation_hint, has_reference, archetype
    )
    return await _concept_to_prompt(concept, has_reference, variation_hint)


async def generate_creatives(
    media_type: str,
    context: dict,
    variation_hint: Optional[str] = None,
    reference_image: Optional[tuple[bytes, str]] = None,
    aspect_ratio: str = "1:1",
    count: int = 3,
) -> list[tuple[bytes, str, str, str]]:
    """Compose and render ``count`` DISTINCT image variants for one round.

    Each variant gets its own concept archetype (see ``_pick_archetypes``) and runs
    the full art-director → prompt-writer → render chain, all concurrently, so the
    user picks between genuinely different takes on their business rather than
    three near-copies at the wall-clock cost of one.

    ``reference_image`` = ``(bytes, mime_type)`` — an optional user-supplied guide
    image. When present, image gen routes to the Gemini image model (image+text →
    image) and archetype choice narrows to the product-faithful lane.

    ``aspect_ratio`` = a Meta-compliant ratio (default ``"1:1"`` — 1080-class square,
    universal feed placement).

    Returns a list of ``(bytes, content_type, filename, prompt)``. A partial round
    still gives the user a choice, so a failed leg is dropped rather than failing
    the job; ``CreativeGenError`` is raised only when EVERY leg fails.
    """
    if media_type != "image":
        raise CreativeGenError(f"Unsupported media_type: {media_type!r}")

    client = _client()
    has_reference = reference_image is not None
    archetypes = _pick_archetypes(count, has_reference)

    async def _one(index: int, archetype: tuple[str, str]) -> tuple[bytes, str, str, str]:
        prompt = await compose_visual_prompt(
            context, media_type, variation_hint, has_reference, archetype
        )
        data = await _generate_image(client, prompt, reference_image, aspect_ratio)
        return data, "image/png", f"punk_creative_{index + 1}.png", prompt

    results = await asyncio.gather(
        *(_one(i, a) for i, a in enumerate(archetypes)), return_exceptions=True
    )

    variants: list[tuple[bytes, str, str, str]] = []
    errors: list[str] = []
    for archetype, result in zip(archetypes, results):
        if isinstance(result, BaseException):
            logger.warning(
                "creative_gen: variant archetype=%s failed: %s", archetype[0], result
            )
            errors.append(str(result))
        else:
            variants.append(result)

    if not variants:
        raise CreativeGenError(
            "All creative variants failed: " + ("; ".join(errors) or "unknown error")
        )
    return variants


def _extract_inline_image(resp: Any) -> Optional[bytes]:
    """Pull the first inline image bytes out of a Gemini generate_content response."""
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            if data:
                return data
    return None


async def _generate_image(
    client: Any,
    prompt: str,
    reference: Optional[tuple[bytes, str]] = None,
    aspect_ratio: str = "1:1",
) -> bytes:
    """Render one image via the Gemini image model (``gemini-2.5-flash-image``).

    One code path for both text→image and image+text→image: when a reference is
    supplied its bytes ride as a leading ``Part`` (subject/look conditioning),
    otherwise the prompt alone drives the render.

    ``image_config`` pins the Meta-compliant aspect ratio (default 1:1) and asks for
    a high-resolution (2K) render for quality. If the model/SDK rejects ``image_size``,
    we retry once without it (ratio still enforced) rather than failing the job.
    """
    from google.genai import types

    contents: list[Any] = []
    if reference is not None:
        ref_bytes, ref_mime = reference
        contents.append(
            types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime or "image/png")
        )
    contents.append(prompt)

    async def _render(image_size: Optional[str]) -> Any:
        image_config = types.ImageConfig(
            aspect_ratio=aspect_ratio,
            **({"image_size": image_size} if image_size else {}),
        )
        return await client.aio.models.generate_content(
            model=settings.GEMINI_IMAGE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=image_config,
            ),
        )

    try:
        try:
            resp = await _render(settings.CREATIVE_IMAGE_SIZE)
        except Exception as exc:  # 2K unsupported → retry at default resolution
            logger.warning(
                "creative_gen: image_size=%s rejected (%s) — retrying without it",
                settings.CREATIVE_IMAGE_SIZE, exc,
            )
            resp = await _render(None)
    except Exception as exc:
        raise CreativeGenError(f"Gemini image generation failed: {exc}") from exc

    data = _extract_inline_image(resp)
    if not data:
        raise CreativeGenError("Gemini image response carried no image bytes.")
    return data
