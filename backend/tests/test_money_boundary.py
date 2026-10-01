"""
The money boundary — asserted once, structurally, so it stays true as new
tools/spec keys get added rather than by convention alone.

Only FOUR operations in this codebase move real money or start live ad
spend: apply_budget_change / apply_status_change / apply_bid_adjustment
(campaign_manager_tools.LEGACY_WRITE_TOOLS, gated behind campaign_manager_
node's permission round trip) and activating a published campaign (gated
behind builder_node's `go_live_confirm` interrupt). Everything built in this
session's read-enrichment / step-list work (interject_tools' handoff lane,
the POI selection spec, the audience filter spec) is deliberately ungated —
correct ONLY because none of it can reach those four operations. This test
is the tripwire for that staying true.
"""
from app.graph import campaign_manager_tools
from app.graph.builder import interject_tools


def test_handoff_tools_never_collide_with_the_gated_money_tool_names():
    """The exact hazard the HANDOFF_ prefix rename exists to prevent: a name
    shared between the gated money set and the ungated handoff set would let
    someone assume they share the protection. They must not overlap at all."""
    handoff_names = {t.name for t in interject_tools.HANDOFF_ALL_TOOLS}
    money_names = set(campaign_manager_tools.LEGACY_WRITE_TOOLS)
    assert handoff_names & money_names == set()


def test_handoff_tools_have_no_budget_status_bid_or_activation_verbs():
    """Belt-and-suspenders over the exact-name check above: nothing in the
    ungated set should even be NAMED like a money operation, so a reviewer
    scanning names alone can trust what they see."""
    money_verbs = ("budget", "status", "bid", "activate", "publish", "spend")
    for t in interject_tools.HANDOFF_ALL_TOOLS:
        low = t.name.lower()
        assert not any(v in low for v in money_verbs), (
            f"{t.name!r} in the ungated handoff set looks like a money operation"
        )


def test_poi_and_audience_spec_schemas_carry_no_money_fields():
    """The two spec grammars built this session (POI selection, audience
    filter) are pure narrowing/filtering over already-fetched data — neither
    should ever grow a field that could touch budget, status, bid, or
    activation. A key with one of those names appearing in either schema is
    exactly how a "let the spec do more" change could accidentally cross
    the boundary without anyone gating it."""
    from app.graph.builder.executors.poi_selection import _SPEC_KEYS

    money_words = ("budget", "status", "bid", "activate", "spend")
    for key in _SPEC_KEYS:
        assert not any(w in key.lower() for w in money_words), key

    from app.graph.nodes import AudienceFilterClause

    for key in AudienceFilterClause.model_fields:
        assert not any(w in key.lower() for w in money_words), key


def test_money_tools_require_the_permission_gate_by_membership():
    """Ground truth for what IS gated, so the two tests above are checking
    against the real set, not a copy-pasted guess."""
    assert campaign_manager_tools.LEGACY_WRITE_TOOLS == {
        "apply_budget_change", "apply_status_change", "apply_bid_adjustment",
    }
    gated_names = {t.name for t in campaign_manager_tools.LEGACY_TOOLS
                   if t.name in campaign_manager_tools.LEGACY_WRITE_TOOLS}
    assert gated_names == campaign_manager_tools.LEGACY_WRITE_TOOLS


def test_activation_stays_behind_its_own_interrupt_gate():
    """The fourth money operation — go-live — isn't a campaign_manager tool
    at all, it's an interrupt gate in the builder. Confirms the gate exists
    and still targets `activate`, so this test breaks (not silently drifts)
    if that mapping is ever weakened."""
    from app.graph.builder.builder_node import _OP_GATE

    assert _OP_GATE.get("activate") == "go_live_confirm"
