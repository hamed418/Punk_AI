"""
Unit tests for builder/executors/poi_selection.py — the NL POI-trim resolver
("just the top 10", "drop everything in Laval"). Pure functions, no DB, no
network, no LLM.
"""
from app.graph.builder.executors.poi_selection import (
    allocate_top_n,
    parse_trim_instruction,
    resolve_drop_predicate,
)


def _poi(name, angle="category", ptype="gym", label="Montreal", lat=45.5, lng=-73.5, types=None):
    return {
        "name": name, "source_angle": angle, "parent_poi_type": ptype,
        "parent_label": label, "lat": lat, "lng": lng,
        "types": types if types is not None else [ptype],
    }


# ── parse_trim_instruction ──────────────────────────────────────────────────

def test_parse_top_n_variants():
    assert parse_trim_instruction("just the top 10") == ("top_n", 10)
    assert parse_trim_instruction("keep 5") == ("top_n", 5)
    assert parse_trim_instruction("limit it to 20") == ("top_n", 20)
    assert parse_trim_instruction("cap it at 3") == ("top_n", 3)
    assert parse_trim_instruction("show me 8") == ("top_n", 8)


def test_parse_drop_fallback():
    assert parse_trim_instruction("drop everything in Laval") == ("drop", None)
    assert parse_trim_instruction("remove the Tim Hortons ones") == ("drop", None)
    assert parse_trim_instruction("exclude the downtown ones") == ("drop", None)


def test_parse_unrecognized_instruction_is_unknown_not_a_silent_drop():
    """Regression: this used to fail OPEN to ("drop", None) — "suggest me some
    POIs" was silently read as "remove the spots named 'suggest me some
    pois'", matched nothing, and reported a false success. It must now be
    reported as unrecognized so the caller can say so instead of pretending
    it acted."""
    assert parse_trim_instruction("") == ("unknown", None)
    assert parse_trim_instruction("suggest me some POIs") == ("unknown", None)
    assert parse_trim_instruction("what places should I target") == ("unknown", None)


# ── allocate_top_n: allocator ───────────────────────────────────────────────

def test_allocate_top_n_keeps_every_source_angle():
    pois = (
        [_poi(f"gym{i}", angle="category", ptype="gym") for i in range(6)]
        + [_poi(f"trade{i}", angle="category", ptype="trade show") for i in range(6)]
    )
    kept, dropped = allocate_top_n(pois, 6)
    kept_types = {p["parent_poi_type"] for p in kept}
    assert kept_types == {"gym", "trade show"}, "both discovered buckets must survive a trim"
    assert len(kept) == 6
    assert len(dropped) == 6


def test_allocate_top_n_never_trims_named_arms():
    named = [_poi("Boustan", angle="competitor_brand"), _poi("Sparta", angle="named_places")]
    discovered = [_poi(f"gym{i}") for i in range(20)]
    kept, dropped = allocate_top_n(named + discovered, 5)
    kept_names = {p["name"] for p in kept}
    assert "Boustan" in kept_names and "Sparta" in kept_names, "named arms must never be trimmed"
    assert all(p.get("source_angle") == "category" for p in dropped), "only discovered POIs may be dropped"
    assert len([p for p in kept if p.get("source_angle") == "category"]) == 5


def test_allocate_top_n_splits_fairly_across_four_buckets():
    pois = []
    for bucket in ("gym", "cafe", "trade show", "event_venue"):
        pois += [_poi(f"{bucket}-{i}", ptype=bucket) for i in range(5)]
    kept, dropped = allocate_top_n(pois, 10)
    from collections import Counter
    counts = Counter(p["parent_poi_type"] for p in kept)
    # Round-robin over 4 equal buckets draining to 10 -> 3/3/2/2 (order-dependent
    # which two get 3), never one bucket getting starved to 0.
    assert sorted(counts.values()) == [2, 2, 3, 3]
    assert set(counts) == {"gym", "cafe", "trade show", "event_venue"}


def test_allocate_top_n_noop_when_already_under_n():
    pois = [_poi(f"gym{i}") for i in range(3)]
    kept, dropped = allocate_top_n(pois, 10)
    assert kept == pois
    assert dropped == []


def test_allocate_top_n_type_match_beats_off_category_within_bucket():
    # Same bucket (angle/type/label) — an off-category result (Places
    # returned it but its own `types` doesn't include what was searched)
    # should rank behind an exact match, not ahead of it.
    off_category = _poi("Nail Salon", types=["beauty_salon"])
    matches = [_poi(f"gym{i}") for i in range(3)]
    pois = [off_category] + matches
    kept, dropped = allocate_top_n(pois, 3)
    kept_names = {p["name"] for p in kept}
    assert "Nail Salon" not in kept_names
    assert dropped[0]["name"] == "Nail Salon" or off_category in dropped


def test_allocate_top_n_arrival_order_preserved_among_ties():
    # All same type-match score (all exact matches) -> stable sort keeps
    # the original (Places relevance) arrival order within the bucket.
    pois = [_poi(f"gym{i}") for i in range(5)]
    kept, dropped = allocate_top_n(pois, 3)
    assert [p["name"] for p in kept] == ["gym0", "gym1", "gym2"]


# ── resolve_drop_predicate ───────────────────────────────────────────────────

def test_resolve_drop_predicate_matches_by_label():
    pois = [_poi("Gym A", label="Laval"), _poi("Gym B", label="Montreal")]
    hits = resolve_drop_predicate(pois, "drop everything in Laval")
    assert [p["name"] for p in hits] == ["Gym A"]


def test_resolve_drop_predicate_matches_by_name_accent_case_folded():
    pois = [_poi("Café Île"), _poi("Gym B")]
    hits = resolve_drop_predicate(pois, "remove the cafe ile ones")
    assert [p["name"] for p in hits] == ["Café Île"]


def test_resolve_drop_predicate_no_match_drops_nothing():
    pois = [_poi("Gym A"), _poi("Gym B")]
    hits = resolve_drop_predicate(pois, "drop everything in Timbuktu")
    assert hits == []


def test_resolve_drop_predicate_tolerates_plural_of_a_singular_category():
    # Regression: "pet stores" said, "pet store" is what's stored — the live
    # bug (thread b1e1fd10) that made "there are no pet stores to remove"
    # a lie while a Pet Store tab was still on the map.
    pois = [_poi("PetSmart", ptype="pet store"), _poi("Gym B")]
    hits = resolve_drop_predicate(pois, "remove pet stores")
    assert [p["name"] for p in hits] == ["PetSmart"]


def test_resolve_drop_predicate_still_matches_the_literal_singular():
    pois = [_poi("PetSmart", ptype="pet store")]
    hits = resolve_drop_predicate(pois, "remove pet store")
    assert [p["name"] for p in hits] == ["PetSmart"]


def test_resolve_drop_predicate_length_guard_blocks_short_word_stripping():
    # A short "plural-shaped" word ("bus") must NOT be chewed down to "bu" —
    # which would over-match "Burger" — so the length guard (needle > 3
    # chars) keeps the fallback from firing here at all.
    pois = [_poi("Burger Place", ptype="burger joint")]
    hits = resolve_drop_predicate(pois, "remove bus")
    assert hits == []


def test_resolve_drop_predicate_matches_one_specific_poi_by_name():
    pois = [_poi("Denver Animal Hospital"), _poi("Denver Cat Hospital")]
    hits = resolve_drop_predicate(pois, "remove Denver Animal Hospital")
    assert [p["name"] for p in hits] == ["Denver Animal Hospital"]


# ── shortlist wording (no explicit number) ──────────────────────────────────

def test_parse_shortlist_and_best_default_to_top_n():
    assert parse_trim_instruction("shortlist these") == ("top_n", 15)
    assert parse_trim_instruction("just show me the best ones") == ("top_n", 15)
    assert parse_trim_instruction("top rated please") == ("top_n", 15)


def test_parse_explicit_number_beats_shortlist_wording():
    # "top 5" already matches _TOP_N_RE and must win over the bare-shortlist
    # default even though "top" also appears in the shortlist vocabulary.
    assert parse_trim_instruction("just the top 5, the best ones") == ("top_n", 5)


def test_parse_drop_verb_beats_shortlist_wording():
    # "drop ... best" should still read as a removal, not a keep-the-best-N
    # request — _DROP_VERB_RE is checked before _SHORTLIST_RE.
    assert parse_trim_instruction("drop the worst ones, keep the best") == ("drop", None)


# ── Bayesian rating rank (_rank_key / _pool_mean_rating) ────────────────────

from app.graph.builder.executors.poi_selection import _pool_mean_rating, _rank_key  # noqa: E402


def _rated_poi(name, rating, reviews, ptype="gym"):
    p = _poi(name, ptype=ptype)
    p["rating"] = rating
    p["user_ratings_total"] = reviews
    return p


def test_bayes_outranks_a_thin_five_star():
    """5.0 from 2 reviews must NOT beat 4.6 from 800 — the whole point of the
    prior. Same bucket, same type match, so rating alone decides.

    Needs a realistic pool (not just the two POIs being compared) — the pool
    mean C is what pulls Thin's raw 5.0 back down; with only Thin/Solid/Mid in
    the pool, C sits too close to their own ratings to separate them at all.
    Filler POIs establish a C distinctly below both.
    """
    filler = [_rated_poi(f"filler{i}", 4.0, 50) for i in range(10)]
    pois = filler + [
        _rated_poi("Thin", 5.0, 2),
        _rated_poi("Solid", 4.6, 800),
        _rated_poi("Mid", 4.2, 300),
    ]
    kept, _ = allocate_top_n(pois, 1)
    assert [p["name"] for p in kept] == ["Solid"]


def test_unrated_lands_mid_pack_not_last():
    """An unrated POI (n=0) scores exactly the pool mean, not zero — it must
    beat a below-average RATED poi, not be swept out by every top-N the
    instant anything else in the pool has stars."""
    pois = [_rated_poi("Bad", 3.0, 400), _poi("Unrated"), _rated_poi("Good", 4.8, 400)]
    kept, _ = allocate_top_n(pois, 2)
    assert {p["name"] for p in kept} == {"Good", "Unrated"}


def test_all_unrated_pool_is_todays_behaviour():
    """C=0.0 when nothing is rated -> every Bayesian score ties at 0.0 ->
    stable sort falls through to _type_match_score + arrival order, i.e.
    the exact pre-rating behaviour. This is the back-compat guarantee the
    whole existing corpus (test_poi_selection_corpus.py) relies on."""
    pois = [_poi(f"gym{i}") for i in range(5)]
    assert _pool_mean_rating(pois) == 0.0
    kept, _ = allocate_top_n(pois, 3)
    assert [p["name"] for p in kept] == ["gym0", "gym1", "gym2"]


def test_type_match_still_dominates_over_rating():
    """An off-category 5.0-star result must still lose to an on-category
    lower-rated one — type match is the PRIMARY key, rating only breaks ties
    within it."""
    off_category = _rated_poi("Nail Salon", 5.0, 900)
    off_category["types"] = ["beauty_salon"]
    on_category = _rated_poi("Gym A", 3.9, 50)
    kept, _ = allocate_top_n([off_category, on_category], 1)
    assert kept[0]["name"] == "Gym A"


def test_rank_key_reused_across_pool_is_one_mean():
    pool = [_rated_poi("A", 4.0, 100), _rated_poi("B", 5.0, 100)]
    key = _rank_key(pool)
    # Same closure, called on both POIs — must not recompute a different C.
    assert key(pool[0])[1] < key(pool[1])[1]
