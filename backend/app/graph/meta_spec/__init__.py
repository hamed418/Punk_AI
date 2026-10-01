"""
graph/meta_spec
───────────────
Single source of truth for "what does Meta accept".

Everything that used to be guessed by an LLM or hardcoded at the call site lives
here: the enum vocabulary (sourced from the installed ``facebook_business`` SDK),
the per-objective field matrix, and strict Pydantic models that refuse a payload
Meta would reject.

The package is deliberately pure — no I/O, no LLM, no Graph API calls — so the
whole matrix is unit-testable without a network or an ad account.
"""

from app.graph.meta_spec.builder import (
    SpecBuildError,
    build_campaign_spec,
    build_campaign_tree,
    split_for_publish,
)
from app.graph.meta_spec.catalog import (
    build_editor_catalog,
    errors_to_form_keys,
)
from app.graph.meta_spec.enums import (
    AdFormat,
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
    SpecialAdCategory,
    meta_label,
    normalize_objective,
)
from app.graph.meta_spec.models import (
    AdSetSpec,
    AdSpec,
    CampaignSpec,
    CarouselCard,
    CreativeSpec,
    PromotedObject,
)
from app.graph.meta_spec.objective_matrix import (
    DEFAULT_PIXEL_EVENT,
    OBJECTIVE_MATRIX,
    DestinationRules,
    ObjectiveRules,
    matrix_for,
    rules_for,
)
from app.graph.meta_spec.parsing import (
    BudgetParseError,
    DateParseError,
    minor_units,
    parse_budget_to_cents,
    parse_campaign_date,
    resolve_flight,
)
from app.graph.meta_spec.special_categories import detect_special_ad_categories

__all__ = [
    "SpecBuildError",
    "build_campaign_spec",
    "build_campaign_tree",
    "split_for_publish",
    "build_editor_catalog",
    "errors_to_form_keys",
    "BudgetParseError",
    "DateParseError",
    "minor_units",
    "parse_budget_to_cents",
    "parse_campaign_date",
    "resolve_flight",
    "AdSetSpec",
    "AdSpec",
    "CampaignSpec",
    "CarouselCard",
    "CreativeSpec",
    "PromotedObject",
    "DEFAULT_PIXEL_EVENT",
    "detect_special_ad_categories",
    "AdFormat",
    "meta_label",
    "DestinationRules",
    "rules_for",
    "BidStrategy",
    "BillingEvent",
    "CallToAction",
    "DestinationType",
    "Objective",
    "OptimizationGoal",
    "SpecialAdCategory",
    "normalize_objective",
    "OBJECTIVE_MATRIX",
    "ObjectiveRules",
    "matrix_for",
]
