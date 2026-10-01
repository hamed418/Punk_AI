"""'Keep only the locations that have visits' trims SPOTS by their visitor count."""
from app.graph.builder.builder_node import _resolve_visitor_floors
from app.graph.builder.executors.poi_selection import apply_specs, normalize_spec


def _p(name, lat, cnt, kind="dog park"):
    return {"name": name, "lat": lat, "lng": -105.0, "parent_poi_type": kind,
            "source_angle": "category", "audience_count": cnt}


def _det(*pois, extraction="x"):
    return {"targetable_pois": list(pois), "maid_extraction_id": extraction}


def test_normalize_keeps_min_visitors_and_rejects_junk():
    assert normalize_spec({"min_visitors": 1})["min_visitors"] == 1
    assert normalize_spec({"min_visitors": 0})["min_visitors"] is None
    assert normalize_spec({"min_visitors": True})["min_visitors"] is None


def test_drops_only_zero_visitor_spots():
    a, b, c = _p("A", 39.1, 5), _p("B", 39.2, 0), _p("C", 39.3, 0, "vet clinic")
    out, notes = _resolve_visitor_floors(_det(a, b, c), [{"min_visitors": 1}])
    assert not notes and out[0]["op"] == "drop" and len(out[0]["ids"]) == 2
    rep = apply_specs([a, b, c], out)
    assert [p["name"] for p in rep.kept] == ["A"]


def test_floor_above_one_and_match_scope():
    a, b, c = _p("A", 39.1, 5), _p("B", 39.2, 2), _p("C", 39.3, 1, "vet clinic")
    out, _ = _resolve_visitor_floors(_det(a, b, c), [{"min_visitors": 3, "match": "dog park"}])
    rep = apply_specs([a, b, c], out)
    assert {p["name"] for p in rep.kept} == {"A", "C"}  # vet clinic out of scope


def test_all_have_visitors_is_reported_not_silent():
    out, notes = _resolve_visitor_floors(_det(_p("A", 39.1, 4)), [{"min_visitors": 1}])
    assert out == [] and "already" in notes[0]


def test_nobody_has_visitors_keeps_all_and_says_so():
    out, notes = _resolve_visitor_floors(_det(_p("A", 39.1, 0), _p("B", 39.2, 0)), [{"min_visitors": 1}])
    assert out == [] and "kept them all" in notes[0]


def test_no_audience_yet_is_reported():
    out, notes = _resolve_visitor_floors(_det(_p("A", 39.1, 0), extraction=None), [{"min_visitors": 1}])
    assert out == [] and "audience" in notes[0]


def test_other_specs_pass_through_untouched():
    spec = {"op": "keep", "n": 5}
    out, notes = _resolve_visitor_floors(_det(_p("A", 39.1, 1)), [spec])
    assert out == [spec] and not notes
