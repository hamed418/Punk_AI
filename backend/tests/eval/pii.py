"""
Best-effort PII scrubber for text pulled from production (chat_messages.content)
before it is sent to any judge model.

This is deliberately conservative: anything the regexes can't confidently
classify is NOT silently passed through — it's flagged in the returned
ScrubResult.unconfident list so a human can review before the text is used.
This is a simple regex pass, not NER — per the task spec, that's acceptable,
but it will miss context-dependent PII (e.g. a business name that doesn't
look like an address). Treat scrubbed text as reduced-risk, not zero-risk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
# Long digit runs that look like account/pixel/card numbers, not phone numbers.
_LONG_DIGIT_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
# Capitalized 2-3 word sequences ("John Smith", "Acme Coffee Co") — very rough
# proper-noun heuristic. High false-positive rate on purpose: flag, don't drop.
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")

_COMMON_WORDS_TO_IGNORE = {
    "I Want", "I Need", "I Am", "Meta Ads", "Facebook Ads", "Google Ads",
    "United States", "New York", "Los Angeles", "San Francisco",
}


@dataclass
class ScrubResult:
    scrubbed_text: str
    redacted_counts: dict[str, int] = field(default_factory=dict)
    unconfident_spans: list[str] = field(default_factory=list)

    @property
    def has_unconfident(self) -> bool:
        return len(self.unconfident_spans) > 0


def scrub(text: str) -> ScrubResult:
    if not text:
        return ScrubResult(scrubbed_text=text or "")

    counts: dict[str, int] = {}
    out = text

    out, n = _EMAIL_RE.subn("[EMAIL_REDACTED]", out)
    if n:
        counts["email"] = n

    out, n = _PHONE_RE.subn("[PHONE_REDACTED]", out)
    if n:
        counts["phone"] = n

    out, n = _LONG_DIGIT_RE.subn("[ID_REDACTED]", out)
    if n:
        counts["long_digit_id"] = n

    unconfident: list[str] = []
    for m in _PROPER_NOUN_RE.finditer(out):
        span = m.group(1)
        if span in _COMMON_WORDS_TO_IGNORE:
            continue
        # Flag rather than auto-redact: over-redacting proper nouns destroys
        # the semantic content a judge needs (e.g. "Toronto" as a target
        # location is meaningful, not PII). Human/second-pass decides.
        unconfident.append(span)

    return ScrubResult(scrubbed_text=out, redacted_counts=counts, unconfident_spans=unconfident)


def scrub_batch(texts: list[str]) -> list[ScrubResult]:
    return [scrub(t) for t in texts]
