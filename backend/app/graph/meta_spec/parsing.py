"""
graph/meta_spec/parsing.py
──────────────────────────
Budget and date parsing for the campaign spec.

Both of these existed twice before, with different behaviour:

* ``parse_budget_to_cents`` lived in ``builder/executors/campaign.py`` **and**
  ``services/meta_ads.py`` with different regexes — so the budget shown in the
  plan and the budget sent to Meta could disagree on the same input string.

* ``meta_ads.parse_campaign_date`` tried five formats and then **silently fell
  back to ``now()``**. An unparseable date meant a campaign that started
  immediately instead of when the user asked, with no error anywhere.

One implementation each, and dates raise instead of guessing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",       # 2026-05-01
    "%B %d, %Y",      # May 1, 2026
    "%b %d, %Y",      # May 1, 2026 (abbreviated)
    "%B %d %Y",       # May 1 2026
    "%m/%d/%Y",       # 05/01/2026
    "%d/%m/%Y",       # 01/05/2026
)

_MONEY_RE = re.compile(r"[\d,]+(?:\.\d+)?")

# Budget labels arrive as widget text, not numbers: "Recommended: $55/day",
# "$1,650 total", "$55 - $80/day". Everything before the first ": " is a label.
_LABEL_SPLIT = ": "


# Meta sends and receives every amount in the ad account currency's MINOR unit,
# and for most currencies that is 1/100. These eleven have no minor unit at all —
# Meta documents them with a "currency offset" of 1, meaning a budget of 1 is one
# whole yen/won/forint, not a hundredth of one.
#
# It has to be a static table: ``currency_offset`` is not an AdAccount field in
# v25 (``meta_ads.fetch_ad_account_currency`` records what happened when we asked
# for it). Taken from Meta's own list, which is NOT the ISO minor-unit list —
# HUF and TWD are two decimals in ISO and offset 1 here.
# https://developers.facebook.com/docs/marketing-api/currencies/
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset({
    "CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND",
})


# Symbols for the currencies this product actually sells into (see the US/CA/BD
# target markets); anything else falls back to the ISO code, which is never wrong,
# only longer. Lives here beside ``minor_units`` because both answer the same
# question — how to write an amount in the ad account's own money — and both the
# intake form and the plan card need the answer.
CURRENCY_PREFIX: dict[str, str] = {
    "USD": "$", "CAD": "CA$", "BDT": "৳", "EUR": "€", "GBP": "£", "AUD": "A$",
}


def minor_units(currency: str | None) -> int:
    """How many minor units make one whole unit of ``currency``.

    100 for USD / CAD / BDT and everything else; 1 for the zero-decimal
    currencies above. Use this instead of a literal ``100`` anywhere an amount
    crosses between a number a human typed and a number Meta stores — on a JPY
    account the two are the same number, and dividing by 100 there publishes a
    budget a hundred times what the user chose.
    """
    return 1 if str(currency or "").upper() in ZERO_DECIMAL_CURRENCIES else 100


class BudgetParseError(ValueError):
    """The budget string carries no number."""


class DateParseError(ValueError):
    """The date string matched none of the accepted formats."""


def parse_budget_to_cents(raw: str | int | float | None, currency: str | None = None) -> int:
    """``'$55/day'`` / ``'Recommended: $55/day'`` / ``'1,650'`` / ``50`` → the ad
    account's MINOR units (cents on a USD/CAD/BDT account, whole yen on a JPY one).

    ``currency`` is the ad account's code (``user_info['ad_account_currency']``).
    Omitting it assumes a two-decimal currency — right for the three target
    markets, and the reason every pre-existing caller keeps working — but pass it
    on any path that reaches Meta, or a JPY advertiser is billed 100×.

    Raises ``BudgetParseError`` when there is no number to find. The old
    implementations returned 5000 ($50) in that case — a silent default that
    spent real money at a rate nobody chose.
    """
    scale = minor_units(currency)
    if raw is None:
        raise BudgetParseError("no budget provided")
    if isinstance(raw, (int, float)):
        if raw <= 0:
            raise BudgetParseError(f"budget must be positive, got {raw!r}")
        return int(round(raw * scale))

    text = str(raw)
    # Drop a leading label ("Recommended: $55/day") so its digits can't win.
    if _LABEL_SPLIT in text:
        text = text.split(_LABEL_SPLIT, 1)[-1]

    match = _MONEY_RE.search(text.replace(",", ""))
    if not match:
        raise BudgetParseError(f"no number found in budget {raw!r}")

    amount = float(match.group())
    if amount <= 0:
        raise BudgetParseError(f"budget must be positive, got {raw!r}")
    return int(round(amount * scale))


def parse_campaign_date(raw: str | datetime | None) -> datetime:
    """Parse a user-supplied campaign date into an aware UTC datetime.

    Raises ``DateParseError`` on anything unrecognized rather than defaulting to
    now(), which is what silently shifted campaign start dates before.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise DateParseError("no date provided")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)

    text = str(raw).strip()

    # ISO first — it is what our own round-trips emit.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("+0000", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise DateParseError(f"unrecognized date format: {raw!r}")


def resolve_flight(
    start_raw: str | datetime | None,
    end_raw: str | datetime | None,
    *,
    is_lifetime: bool,
    default_flight_days: int = 30,
) -> tuple[datetime, datetime | None]:
    """Campaign start/end as datetimes.

    An absent start means "begin now" — that is a real user intent ("run it
    today"), unlike an unparseable one. An absent end is open-ended for a daily
    budget; a lifetime budget requires one, so it gets a default window rather
    than failing the whole plan over a field the user was never asked for.
    """
    try:
        start = parse_campaign_date(start_raw)
    except DateParseError:
        if start_raw:
            raise
        start = datetime.now(timezone.utc)

    end: datetime | None = None
    if end_raw and str(end_raw).strip().lower() not in _OPEN_ENDED:
        end = parse_campaign_date(end_raw)

    if is_lifetime and end is None:
        end = start + timedelta(days=default_flight_days)

    return start, end


_OPEN_ENDED: frozenset[str] = frozenset({
    "ongoing", "no end", "none", "open ended", "open-ended", "indefinite", "",
})
