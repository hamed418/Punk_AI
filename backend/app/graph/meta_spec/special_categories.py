"""
graph/meta_spec/special_categories.py
─────────────────────────────────────
Detect regulated ad verticals so the campaign declares them.

``meta_ads.create_campaign`` hardcoded ``special_ad_categories: []`` for every
campaign. For a housing, employment or financial-services advertiser (credit
included — Ads Manager folded it into financial services) that is a compliance
failure, not a cosmetic one: Meta rejects the ads, and repeat offences put the
ad account at risk.

Politics and gambling are **not** detected here. Both need an approval Punk
cannot obtain for the user (identity verification and advertiser authorization
for political ads; written permission from Meta for gambling), so suggesting the
category would only produce a campaign that fails review — see
``enums.SpecialAdCategory``.

Detection is a **suggestion**, never a silent decision. The result is surfaced
in the campaign form pre-selected, and the user confirms or clears it — they are
the ones making the legal declaration, and only they know their business.

Keyword rules only. This deliberately does not call an LLM: the function runs on
every plan build, needs to be deterministic across checkpoint replays, and a
false negative here is far more costly than an over-eager suggestion the user
can uncheck.
"""

from __future__ import annotations

import re

from app.graph.meta_spec.enums import SpecialAdCategory

# Ordered most- to least-specific, and FINANCIAL_PRODUCTS_SERVICES leads so
# "home loan" resolves to it rather than to HOUSING.
#
# The credit keywords are in that first tuple rather than a CREDIT one of their
# own: Ads Manager folded credit into Financial products and services, so CREDIT
# is no longer in the enum — see ``enums.SpecialAdCategory``.
_RULES: tuple[tuple[SpecialAdCategory, tuple[str, ...]], ...] = (
    (SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES, (
        # Credit
        "credit card", "credit score", "credit repair", "home loan", "auto loan",
        "student loan", "personal loan", "payday loan", "loan application",
        "mortgage rate", "refinanc", "debt consolidation", "line of credit",
        "financing available", "buy now pay later", "installment plan",
        # Everything else financial
        "investment advice", "financial advis", "wealth management", "brokerage",
        "mutual fund", "retirement plan", "insurance quote", "life insurance",
        "health insurance", "crypto", "trading platform", "stock market",
        "portfolio management", "tax preparation",
    )),
    (SpecialAdCategory.EMPLOYMENT, (
        "we are hiring", "we're hiring", "now hiring", "job opening", "job listing",
        "job board", "job vacancy", "career opportunit", "apply for a job",
        "full-time position", "part-time position", "recruitment agency",
        "staffing agency", "employment opportunit", "join our team",
    )),
    (SpecialAdCategory.HOUSING, (
        "real estate", "realtor", "homes for sale", "houses for sale",
        "apartments for rent", "apartment for rent", "property listing",
        "property for sale", "rental listing", "leasing office", "housing",
        "condo for sale", "mortgage broker", "home listing", "tenant",
    )),
)


def detect_special_ad_categories(
    business_desc: str | None = None,
    industry: str | None = None,
    product_offer: str | None = None,
) -> list[SpecialAdCategory]:
    """Suggest the special ad categories this advertiser probably falls under.

    Returns ``[]`` for the common case. Multiple categories are possible (a
    mortgage broker is plausibly both FINANCIAL_PRODUCTS_SERVICES and HOUSING)
    and Meta accepts a list, so no single-winner tie-break is applied.
    """
    haystack = " ".join(
        part.lower() for part in (business_desc, industry, product_offer) if part
    )
    if not haystack.strip():
        return []
    # Collapse whitespace and punctuation so "we're  hiring!" still matches.
    haystack = re.sub(r"\s+", " ", haystack)

    return [category for category, needles in _RULES if any(n in haystack for n in needles)]


def explain(categories: list[SpecialAdCategory]) -> str:
    """User-facing note for the form. Explains the targeting cost of declaring,
    so the choice is informed rather than a checkbox they click past."""
    if not categories:
        return (
            "No special ad category detected. If your ads relate to housing, "
            "employment, or credit and financial services, select the category — "
            "Meta requires it."
        )
    names = ", ".join(c.value.replace("_", " ").title() for c in categories)
    return (
        f"This looks like a regulated category ({names}). Meta requires the "
        "declaration, and it costs you most of the targeting: no ZIP codes (city "
        "level at best, with a 15-mile floor), no age or gender, no interest or "
        "behaviour targeting, and no lookalike audience. Clear it if it does not "
        "apply to your ads."
    )
