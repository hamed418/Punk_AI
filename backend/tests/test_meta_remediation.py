"""``meta_remediation`` — matching Meta's refusals onto steps a human can take.

Three failure modes are worth a test each, because each one is worse than saying
nothing:

  * a WRONG match tells the user to go do something irrelevant, which costs them a
    trip through Business Manager and teaches them to ignore the card;
  * a half-substituted deep link ("…?business_id={business_id}") sends them to a
    page that does not exist;
  * a plan-asset check that fires on an UNREADABLE field blocks a campaign that
    would have published perfectly well — the three-state rule ``list_meta_pages``
    exists to preserve.

Nothing here talks to Meta. ``MetaAdsError`` is constructed directly, the same way
the transport builds it from a Graph payload.
"""
import pytest

from app.services import meta_remediation as rem
from app.services.meta_ads import MetaAdsError


def _err(message: str = "GraphAPIError: something", **kwargs) -> MetaAdsError:
    return MetaAdsError(message, **kwargs)


# ── matching ─────────────────────────────────────────────────────────────────


def test_subcode_wins_over_everything():
    """1870050 means one thing and only one thing, whatever the prose says."""
    exc = _err("OAuthException: Business Account Needed", code=200, subcode=1870050)

    assert rem.resolve(exc, step="custom_audience").key == "audience_needs_business"


def test_subcode_matches_even_out_of_scope():
    """A subcode is precise enough that the step it arrived at cannot contradict it."""
    exc = _err("whatever", code=100, subcode=1870034)

    assert rem.resolve(exc, scope="publish").key == "custom_audience_tos"


def test_phrase_match_reads_metas_user_message():
    """``error_user_msg`` is where Meta names the real problem — search it too."""
    exc = _err(
        "GraphAPIError: Invalid parameter",
        code=100,
        user_msg="You must accept the Custom Audience Terms of Service.",
    )

    assert rem.resolve(exc, step="custom_audience").key == "custom_audience_tos"


def test_scope_separates_two_meanings_of_one_code():
    """190 at publish means reconnect; 190 on a CAPI feed means system user token.

    The generic permission entry deliberately does not claim the tracking scope,
    because telling someone to reconnect fixes a feed for sixty days and then
    breaks it again.
    """
    exc = _err("OAuthException: Session has expired", code=190)

    assert rem.resolve(exc, scope="publish").key == "app_missing_ads_management"
    assert rem.resolve(exc, scope="tracking").key == "tracking_token_expired"


def test_app_access_level_is_not_a_reconnect_problem():
    """Code 3 is the APP lacking the capability, not the user's token.

    It shared a card with 200/10/190, whose only advice is "reconnect Meta" — which
    mints the same grant and fails the same way, forever. It gets its own card,
    with no deep link, because nothing the advertiser does in Meta clears it.
    """
    exc = _err("OAuthException: (#3) Application does not have the capability", code=3)

    fix = rem.resolve(exc, scope="publish")
    assert fix.key == "app_access_level"
    assert not any(step.startswith("Reconnect") for step in fix.steps)
    assert not fix.url
    # …and the neighbouring permission codes still get the reconnect advice.
    assert rem.resolve(_err("no permission", code=200), scope="publish").key == (
        "app_missing_ads_management"
    )


def test_bare_code_does_not_match_without_a_scope():
    """A code alone covers thousands of unrelated failures — it needs narrowing."""
    assert rem.resolve(_err("GraphAPIError: nope", code=200)) is None


def test_unknown_rejection_returns_none():
    """The common answer. Callers keep their existing generic wording for it."""
    exc = _err("GraphAPIError: the ad set name is too long", code=100, subcode=1234567)

    assert rem.resolve(exc, step="adset") is None


def test_throttle_code_matches_across_publish_scopes():
    """An exhausted-retry rate limit used to surface as a raw Graph string —
    nothing in the catalog claimed codes 4/17/32/613/80004 at all."""
    for code in (4, 17, 32, 613, 80004):
        exc = _err("OAuthException: (#{}) Application request limit reached".format(code), code=code)
        assert rem.resolve(exc, scope="publish").key == "meta_rate_limited"
        assert rem.resolve(exc, scope="audience").key == "meta_rate_limited"
        assert rem.resolve(exc, scope="tracking").key == "meta_rate_limited"


def test_domain_entry_does_not_swallow_unrelated_link_errors():
    """"domain" appears in link-format rejections that have nothing to do with
    verification; only the verification wording may match."""
    exc = _err("GraphAPIError: The domain of the link is malformed", code=100)

    assert rem.resolve(exc, scope="publish") is None


# ── rendering ────────────────────────────────────────────────────────────────


def test_render_fills_the_deep_link():
    out = rem.render(rem.CATALOG["custom_audience_tos"], ad_account_id="act_123")

    # The BARE account number, not the Graph API's act_ form. Meta's own
    # rejection message points at ".../tos/?act=116187595198313", and its
    # consoles 404 on the prefixed form — so the link this card exists to offer
    # was landing the user nowhere. Callers still pass act_123, because that is
    # what every Graph call takes; render normalizes it.
    assert out["url"].endswith("?act=123")
    assert out["severity"] == "degrades"
    assert out["steps"]


def test_render_drops_a_link_it_cannot_complete():
    """Half a URL is worse than none: the user clicks it and lands nowhere."""
    out = rem.render(rem.CATALOG["business_not_verified"])

    assert out["url"] == ""


def test_every_catalog_url_renders_or_empties():
    """No entry may ship a template whose placeholders we never supply."""
    ids = {
        "ad_account_id": "act_1",
        "business_id": "2",
        "page_id": "3",
        "dataset_id": "4",
    }
    for entry in rem.CATALOG.values():
        url = rem.render(entry, **ids)["url"]
        assert "{" not in url, f"{entry.key} left a placeholder in {url!r}"


def test_every_catalog_entry_is_actionable():
    for entry in rem.CATALOG.values():
        assert entry.steps, f"{entry.key} has no steps"
        assert entry.severity in ("blocks", "degrades", "warns"), entry.key


# ── the silent family ────────────────────────────────────────────────────────


_IG_PLAN = {"adsets": [{"targeting": {"publisher_platforms": ["facebook", "instagram"]}}]}


def test_instagram_placement_with_no_linked_account_is_reported():
    """The case Meta never errors on: the ad runs, as a placeholder profile."""
    found = rem.check_plan_assets(_IG_PLAN, page={"id": "1", "instagram": None})

    assert [r.key for r in found] == ["instagram_not_linked"]


def test_linked_instagram_is_silent():
    found = rem.check_plan_assets(_IG_PLAN, page={"id": "1", "instagram": {"id": "17"}})

    assert found == []


def test_automatic_placements_count_as_instagram():
    """An empty publisher_platforms is Advantage+ placements, which includes IG —
    not "no platforms"."""
    plan = {"adsets": [{"targeting": {}}]}

    assert [r.key for r in rem.check_plan_assets(plan, page={"instagram": None})] == [
        "instagram_not_linked"
    ]


def test_facebook_only_plan_does_not_ask_for_instagram():
    plan = {"adsets": [{"targeting": {"publisher_platforms": ["facebook"]}}]}

    assert rem.check_plan_assets(plan, page={"instagram": None}) == []


_WA_PLAN = {
    "adsets": [
        {
            "destination_type": "WHATSAPP",
            "targeting": {"publisher_platforms": ["facebook"]},
        }
    ]
}


def test_whatsapp_destination_with_no_number_is_reported():
    found = rem.check_plan_assets(_WA_PLAN, page={"id": "1", "whatsapp": None})

    assert [r.key for r in found] == ["page_whatsapp_missing"]


def test_unreadable_whatsapp_field_is_not_evidence_of_anything():
    """The three-state rule. A token without the scope answers the same as a Page
    with no number, and blocking on that refuses campaigns that publish fine —
    which is why list_meta_pages omits the key instead of writing None."""
    found = rem.check_plan_assets(_WA_PLAN, page={"id": "1"})

    assert found == []


def test_stored_instagram_id_satisfies_the_check_without_a_page():
    """media_ws carries the id after page selection; the Page dict may not be to hand."""
    found = rem.check_plan_assets(_IG_PLAN, instagram_user_id="17841400000000000")

    assert found == []


# ── the new-advertiser checklist ─────────────────────────────────────────────
# A new advertiser has almost nothing configured on Meta. Each prerequisite used to
# surface only when it blocked something, one publish at a time. ``readiness``
# assembles the whole list, in the order to work down it.


def test_readiness_orders_access_then_money_then_consent():
    found = [
        rem.CATALOG["ad_account_no_payment"],
        rem.CATALOG["audience_needs_business"],
    ]

    keys = [c["key"] for c in rem.readiness(found, ad_account_id="act_1")]

    assert keys == ["audience_needs_business", "ad_account_no_payment", "custom_audience_tos"]


def test_readiness_lists_what_meta_will_not_let_punk_read_as_unverified():
    """Custom Audience Terms are only ever learned about when a write is refused.
    Silence is what sends a new user through the same failure once per item, so the
    card is there — but marked, so the user is asked to confirm it rather than told
    it is missing."""
    cards = rem.readiness([], ad_account_id="act_1")

    assert [c["key"] for c in cards] == ["custom_audience_tos"]
    assert cards[0]["unverified"] is True
    # The bare account number, not act_1: Meta's console rejects the prefix.
    assert "act=1" in cards[0]["url"] and "act_1" not in cards[0]["url"]


def test_readiness_does_not_list_the_terms_twice():
    cards = rem.readiness([rem.CATALOG["custom_audience_tos"]], ad_account_id="act_1")

    assert [c["key"] for c in cards] == ["custom_audience_tos"]
    assert "unverified" not in cards[0]


def test_an_ordinary_card_keeps_its_exact_wire_shape():
    """``unverified`` is only present when true — every existing consumer of
    ``render`` sees the shape it always did."""
    assert "unverified" not in rem.render(rem.CATALOG["ad_account_no_payment"])


# ── after publish: Meta reviews every new ad ─────────────────────────────────


def test_a_rejected_ad_carries_metas_reason_and_wins_over_in_review():
    ads = [
        {"id": "1", "name": "Spring", "effective_status": "DISAPPROVED",
         "ad_review_feedback": {"global": {"ADULT": "Adult content", "X": "Adult content"}}},
        {"id": "2", "name": "Summer", "effective_status": "PENDING_REVIEW"},
    ]

    (card,) = rem.review_cards(ads)

    assert card["key"] == "ads_disapproved"
    assert card["severity"] == "blocks"
    # Named, reasoned once even though Meta repeated it.
    assert "Spring: Adult content" in card["cause"]
    assert card["cause"].count("Adult content") == 1


def test_ads_still_in_review_say_so_and_ask_nothing():
    (card,) = rem.review_cards([{"id": "1", "effective_status": "IN_PROCESS"}])

    assert card["key"] == "ads_in_review"
    assert card["severity"] == "warns"


def test_approved_or_paused_ads_have_nothing_to_say():
    ads = [{"id": "1", "effective_status": "ACTIVE"}, {"id": "2", "effective_status": "PAUSED"}]

    assert rem.review_cards(ads) == []
    assert rem.review_cards([]) == []


def test_a_rejection_with_no_reason_still_reports_it():
    (card,) = rem.review_cards([{"id": "9", "effective_status": "DISAPPROVED"}])

    assert "9: no reason given" in card["cause"]


def test_an_unexpected_feedback_shape_is_read_not_trusted():
    """The layout has not been read off a live payload; any string in it counts."""
    fb = {"placement_specific": {"facebook": {"a": ["Too much text"]}}, "global": None}

    (card,) = rem.review_cards([{"id": "1", "name": "A", "effective_status": "DISAPPROVED",
                                 "ad_review_feedback": fb}])

    assert "Too much text" in card["cause"]


@pytest.mark.asyncio
async def test_the_review_read_asks_for_feedback_and_degrades_to_empty(monkeypatch):
    from app.services import meta_ads

    seen = {}

    async def _ok(method, path, token, json_data=None, **_):
        seen["path"], seen["fields"] = path, json_data["fields"]
        return {"data": [{"id": "1", "effective_status": "DISAPPROVED"}]}

    monkeypatch.setattr(meta_ads, "_request", _ok)
    assert await meta_ads.fetch_ad_review("c1", "tok") == [
        {"id": "1", "effective_status": "DISAPPROVED"}
    ]
    assert seen["path"] == "c1/ads" and "ad_review_feedback" in seen["fields"]

    async def _boom(*_a, **_k):
        raise MetaAdsError("nope", code=100)

    monkeypatch.setattr(meta_ads, "_request", _boom)
    # An unreadable status is "nothing to say", never a card.
    assert await meta_ads.fetch_ad_review("c1", "tok") == []


def test_a_card_put_in_front_of_a_user_is_logged_with_metas_trace(monkeypatch):
    """One greppable line per card decided, carrying the fbtrace id support quotes."""
    lines: list[str] = []
    monkeypatch.setattr(rem.logger, "info", lambda msg, *a, **k: lines.append(msg % a))

    exc = _err("OAuthException: (#200) x | fbtrace=AbC123", code=200)
    assert rem.resolve(exc, scope="publish").key == "app_missing_ads_management"
    rem.beat_facts(rem.CATALOG["no_ad_account"])

    assert any(
        "remediation_shown key=app_missing_ads_management" in ln
        and "source=error" in ln and "fbtrace=AbC123" in ln
        for ln in lines
    )
    assert any("key=no_ad_account" in ln and "source=beat" in ln for ln in lines)


def test_an_error_with_no_entry_logs_no_card():
    lines: list[str] = []
    import logging

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    handler = _Capture(level=logging.INFO)
    rem.logger.addHandler(handler)
    old = rem.logger.level
    rem.logger.setLevel(logging.INFO)
    try:
        assert rem.resolve(_err("nothing we know", code=100), scope="publish") is None
    finally:
        rem.logger.removeHandler(handler)
        rem.logger.setLevel(old)

    assert not any("remediation_shown" in ln for ln in lines)


def test_beat_facts_unverified_asks_instead_of_claiming():
    from app.services import meta_remediation as r

    facts = r.beat_facts(r.CATALOG["custom_audience_tos"], unverified=True, ad_account_id="act_1")
    assert "Confirm" in facts["constraint"] and "have not been" not in facts["constraint"]
    assert "ignore this" in facts["fix"]
    assert "act=1" in facts["url"]
    assert r.beat_facts(r.CATALOG["no_pixel"])["constraint"] == "No Pixel on this ad account"


def test_a_reached_spend_limit_sorts_with_the_money_cards_not_last():
    from app.services import meta_remediation as r

    keys = [c["key"] for c in r.readiness([r.CATALOG["ad_account_spend_limit"]], ad_account_id="act_1")]
    assert keys == ["ad_account_spend_limit", "custom_audience_tos"]


def test_readiness_stays_silent_about_terms_a_read_proved_accepted():
    from app.services import meta_remediation as r

    assert r.readiness([], tos_accepted=True, ad_account_id="act_1") == []


def test_readiness_states_terms_plainly_when_a_read_proved_them_missing():
    from app.services import meta_remediation as r

    (card,) = r.readiness([], tos_accepted=False, ad_account_id="act_1")

    assert card["key"] == "custom_audience_tos"
    assert "unverified" not in card


def test_a_role_card_blocks_and_sorts_ahead_of_billing():
    from app.services import meta_remediation as r

    keys = [c["key"] for c in r.readiness(
        [r.CATALOG["ad_account_no_payment"], r.CATALOG["ad_account_role_missing"]],
        tos_accepted=True, ad_account_id="act_1",
    )]
    assert keys == ["ad_account_role_missing", "ad_account_no_payment"]
