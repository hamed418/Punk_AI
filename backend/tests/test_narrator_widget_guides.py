"""Widget guides: the narrator tells the user what each map/plan widget can do —
the full list on first sight, a one-clause reminder afterwards, never on a screen
that has no such widget, and never in words the jargon scrub would rewrite."""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.graph.narrator import beats
from app.graph.narrator import composer
from app.graph.narrator.prompts import base
from app.graph.narrator.prompts.composer import beat_hint_block
from app.graph.narrator.widget_guides import WIDGET_GUIDES, attach_widget_guides


def _state(mid: str = "g1", *, publish_mode: str | None = None) -> dict:
    st: dict = {"messages": [HumanMessage(content="hi", id=mid)]}
    if publish_mode:
        st["campaign_builder_state"] = {"filled": {"publish_mode": publish_mode}}
    return st


def _framing(stage_key: str, **extra) -> beats.Beat:
    facts = {("step" if stage_key.startswith(("maid_", "campaign_", "media_", "geo_collect")) else "stage"): stage_key}
    facts.update(extra)
    return beats.Beat(kind="framing", facts=facts, fallback="Targeting **Montreal**.")


@pytest.fixture(autouse=True)
def _clean():
    beats.clear()
    yield
    beats.clear()


@pytest.mark.asyncio
async def test_first_sight_attaches_full_guide_and_fallback():
    st, b = _state(), _framing("geo_location_confirm")
    await attach_widget_guides(st, [b], turn=1)
    can_do = b.facts["widget_guide"]["can_do"]
    assert "drag a circle to move it" in can_do
    assert can_do[-1].startswith("or just tell me in chat")
    assert b.fallback.startswith("Targeting **Montreal**.")
    assert "drag a circle" in b.fallback


@pytest.mark.asyncio
async def test_later_turn_gets_only_the_reminder():
    st = _state()
    await attach_widget_guides(st, [_framing("geo_location_confirm")], turn=1)
    b = _framing("geo_location_confirm")
    await attach_widget_guides(st, [b], turn=2)
    assert list(b.facts["widget_guide"]) == ["reminder"]
    assert b.fallback == "Targeting **Montreal**."  # no second guide sentence


@pytest.mark.asyncio
async def test_same_turn_replay_reproduces_the_full_guide():
    st = _state()
    first, replay = _framing("geo_location_confirm"), _framing("geo_location_confirm")
    await attach_widget_guides(st, [first], turn=1)
    await attach_widget_guides(st, [replay], turn=1)
    assert replay.facts == first.facts and replay.fallback == first.fallback


@pytest.mark.asyncio
async def test_only_first_matching_beat_per_turn_is_guided():
    st = _state()
    a, b = _framing("campaign_plan_confirm"), _framing("campaign_plan_confirm")
    await attach_widget_guides(st, [a, b], turn=1)
    assert "widget_guide" in a.facts and "widget_guide" not in b.facts


@pytest.mark.asyncio
async def test_audience_guide_skipped_on_the_retry_menu():
    st = _state()
    retry = _framing("maid_confirm_results", action_type="option_selection")
    await attach_widget_guides(st, [retry], turn=1)
    assert "widget_guide" not in retry.facts
    ok = _framing("maid_confirm_results", action_type="permission")
    await attach_widget_guides(st, [ok], turn=1)
    assert "widget_guide" in ok.facts


@pytest.mark.asyncio
async def test_store_confirm_with_no_geocoded_store_has_no_map_to_guide():
    b = _framing("geo_store_confirm", store_count=0)
    await attach_widget_guides(_state(), [b], turn=1)
    assert "widget_guide" not in b.facts


@pytest.mark.asyncio
async def test_non_framing_and_unknown_beats_untouched():
    reveal = beats.Beat(kind="reveal", facts={"stage": "geo_location_confirm"})
    other = _framing("geo_collect_det_type")
    await attach_widget_guides(_state(), [reveal, other], turn=1)
    assert "widget_guide" not in reveal.facts and "widget_guide" not in other.facts


@pytest.mark.asyncio
async def test_express_plan_editor_lists_the_locked_sections():
    ex, guide = _framing("campaign_plan_confirm"), _framing("campaign_plan_confirm")
    await attach_widget_guides(_state("e1", publish_mode="express"), [ex], turn=1)
    await attach_widget_guides(_state("e2", publish_mode="guide"), [guide], turn=1)
    joined = " ".join(ex.facts["widget_guide"]["can_do"])
    assert "Unlock and View" in joined
    assert "Unlock and View" not in " ".join(guide.facts["widget_guide"]["can_do"])
    assert ex.facts["widget_guide"]["can_do"][-1].startswith("or just tell me")


def test_framing_hint_teaches_the_widget_guide():
    assert "widget_guide.can_do" in beat_hint_block(["framing"])


def test_max_chars_makes_room_for_a_guide_even_for_a_terse_user():
    st = _state()
    st["user_turn"] = {"engagement": "terse"}
    plain = beats.Beat(kind="framing", facts={"stage": "x"})
    guided = beats.Beat(kind="framing", facts={"widget_guide": {"can_do": ["a"] * 7}})
    assert composer._max_chars(st, [guided]) >= composer._max_chars(_state(), [plain]) + 7 * composer._GUIDE_CHARS_PER_ACTION
    assert composer._max_chars(st, [guided]) > composer._max_chars(st, [plain])


def test_guides_use_no_banned_jargon():
    banned = [t.lower() for t in base.GLOBAL_FORBIDDEN_TERMS]
    for key, g in WIDGET_GUIDES.items():
        text = " ".join([*g["can_do"], *g.get("express_extra", []), g["reminder"], g["fallback"]]).lower()
        # "poi"/"maid" are short: single-word terms match whole words only.
        words = set(text.replace("—", " ").replace(",", " ").replace(".", " ").split())
        for term in banned:
            hit = (term in text) if " " in term else (term in words)
            assert not hit, f"{key}: {term}"


class _FakePipe:
    def __init__(self, store):
        self.store, self.ops = store, []

    def hsetnx(self, k, f, v):
        self.ops.append(lambda: self.store.setdefault(k, {}).setdefault(f, str(v)))

    def expire(self, *_):
        pass

    async def execute(self):
        for op in self.ops:
            op()


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, dict[str, str]] = {}

    def pipeline(self):
        return _FakePipe(self.store)

    async def hgetall(self, k):
        return dict(self.store.get(k, {}))


@pytest.mark.asyncio
async def test_guided_ledger_crosses_instances(monkeypatch):
    from app.core import redis as _redis

    r = _FakeRedis()
    monkeypatch.setattr(_redis, "redis_enabled", lambda: True)
    monkeypatch.setattr(_redis, "get_client", lambda: r)
    st = _state("x1")
    await attach_widget_guides(st, [_framing("geo_location_confirm")], turn=1)
    beats.clear()  # a different instance: cold process ledger
    assert beats.guided_turn(st, "geo_location_confirm") is None
    await beats.load_guided(st)
    b = _framing("geo_location_confirm")
    await attach_widget_guides(st, [b], turn=2)
    assert list(b.facts["widget_guide"]) == ["reminder"]
