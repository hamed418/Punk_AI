"""The audience-filter vocabulary lives in four places that must agree:

- ``maid_store._KNOWN_FILTER_KEYS``   what the evaluator has a producer for
- ``AudienceFilterClause`` fields     what the classifier's structured output may say
- ``maid_store.LAYER_BUILDER_KEYS``   the (narrower) panel surface
- the ``filter_audience`` tool doc    the only contract the tool-calling router sees

Nothing asserted this, so a key could be implemented but never advertised (as
``unsupported`` was) or advertised but never evaluated.
"""
import re

from app.graph.nodes import AudienceFilterClause
from app.graph.resume_router import filter_audience
from app.services import maid_store

# Consumed before folding (maid_store pops it), so it is a model field and a
# tool key but intentionally not an evaluator key.
_PRE_FOLD = {"unsupported"}

# Evaluator keys no producer can emit today (not in the model, not advertised).
# Listed so NEW drift fails this test rather than joining them silently.
_KNOWN_ORPHANS = {"dwell_bound", "exclude_flags"}


def _public_known() -> set[str]:
    # underscore keys are internal bookkeeping the fold writes back, not vocabulary
    return {k for k in maid_store._KNOWN_FILTER_KEYS if not k.startswith("_")}


def _model_keys() -> set[str]:
    return set(AudienceFilterClause.model_fields) | {"any_of"}


def test_every_model_field_is_evaluable_or_pre_fold():
    assert _model_keys() - _public_known() <= _PRE_FOLD


def test_panel_keys_are_all_evaluable():
    assert set(maid_store.LAYER_BUILDER_KEYS) <= _public_known()


def test_no_new_evaluator_key_without_a_producer():
    assert _public_known() - _model_keys() == _KNOWN_ORPHANS


def test_tool_doc_advertises_every_producible_key():
    doc = filter_audience.description
    advertised = {k for k in _public_known() | _model_keys() if re.search(rf"\b{k}\b", doc)}
    assert (_model_keys()) <= advertised, f"filter_audience omits {sorted(_model_keys() - advertised)}"


def test_tool_doc_advertises_nothing_the_evaluator_cannot_run():
    doc = filter_audience.description
    advertised = {k for k in _public_known() | _model_keys() | _KNOWN_ORPHANS if re.search(rf"\b{k}\b", doc)}
    assert advertised <= _public_known() | _PRE_FOLD | {"any_of"}
