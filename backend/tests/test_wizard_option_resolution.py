"""Option round-trip: a widget answer must map back to the option the user
clicked, even when several options share a label and differ only after the
em dash (the named-place disambiguation ask)."""

from app.graph.wizard_helpers import resolve_option

# Real shape of a geo_disambiguate_named_place ask: same venue name, three
# different Google listings.
DUPES = [
    "Bashundhara City Shopping Complex — Q92P+M73, Panthapath, Dhaka 1205, Bangladesh",
    "Bashundhara City Shopping Complex — Bashundhara City Shopping Complex, Dhaka 1205, Bangladesh",
    "Bashundhara City Shopping Complex — 3 No, West Panthapath, Dhaka 1215, Bangladesh",
]


def test_exact_option_wins_over_earlier_label_match():
    for opt in DUPES:
        assert resolve_option(opt, DUPES) == opt


def test_exact_match_is_case_insensitive():
    assert resolve_option(DUPES[2].upper(), DUPES) == DUPES[2]


def test_ordinal_still_resolves():
    assert resolve_option("2", DUPES) == DUPES[1]


def test_bare_label_falls_back_to_first_match():
    # Genuinely ambiguous (a typed answer, not a click) — documented behaviour.
    assert resolve_option("Bashundhara City Shopping Complex", DUPES) == DUPES[0]


def test_unmatched_answer_passes_through():
    assert resolve_option("somewhere else", DUPES) == "somewhere else"
