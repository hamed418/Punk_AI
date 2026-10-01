"""
Generates a 100-example SYNTHETIC input set for the eval harness, used only
because DB-backed sampling (sampling.py) is blocked on the missing
eval_readonly Postgres role — see that module's docstring.

Stratification mirrors the audit's intent (cover all three known
checkpoint_ns flows, over-sample confirmation turns) but the exact 50/30/20
split and per-template counts below are an authored approximation, not
derived from the real production distribution — that distribution is only
knowable once real sampling is unblocked.

Deterministic (seeded) so re-running reproduces the same 100 examples.
"""
from __future__ import annotations

import itertools
import json
import random

from tests.eval.config import SAMPLE_INPUTS_PATH

random.seed(42)

BUSINESSES = [
    ("coffee shop", "coffee shops"), ("yoga studio", "yoga studios"),
    ("used bookstore", "bookstores"), ("craft brewery", "breweries"),
    ("pet grooming salon", "pet groomers"), ("boutique gym", "gyms"),
    ("vegan bakery", "bakeries"), ("auto detailing shop", "auto shops"),
    ("dental clinic", "dental clinics"), ("indoor climbing gym", "climbing gyms"),
    ("record store", "record stores"), ("nail salon", "nail salons"),
    ("food truck", "food trucks"), ("co-working space", "co-working spaces"),
    ("children's dance studio", "dance studios"),
]
CITIES = [
    "Toronto", "Vancouver", "Austin", "Denver", "Portland", "Chicago",
    "Miami", "Brooklyn", "Seattle", "Montreal", "Nashville", "Phoenix",
]
AUDIENCE_ANGLES = [
    "people who've visited {comp} in the last 30 days",
    "residents within 5km of my store",
    "people interested in {topic}",
    "a lookalike audience based on my current customers",
    "commuters near downtown",
]
TOPICS = ["fitness", "sustainable living", "craft beer", "pet care", "local music", "wellness"]


def _build_campaign_builder_prompts(n: int) -> list[dict]:
    out = []
    combos = list(itertools.product(BUSINESSES, CITIES, AUDIENCE_ANGLES))
    random.shuffle(combos)
    for i, ((biz, comp_plural), city, angle) in enumerate(combos[:n]):
        angle_text = angle.format(comp=random.choice(comp_plural.split()), topic=random.choice(TOPICS))
        content = (
            f"I run a {biz} in {city} and want to run Meta ads targeting {angle_text}. "
            f"Budget is around ${random.choice([20, 50, 75, 100, 150])}/day, not sure yet how long to run it."
        )
        out.append({"id": f"synth-cb-{i:03d}", "content": content, "checkpoint_ns_prefix": "campaign_builder", "is_confirmation_turn": False})
    return out


def _campaign_builder_confirmations(n: int) -> list[dict]:
    templates = [
        "Yes, that budget looks good, go ahead and confirm it.",
        "Actually can we lower it to ${amt}/day instead before confirming?",
        "That audience size seems too small, can you widen the radius before I confirm?",
        "Looks right, confirm the locations and let's move to the next step.",
        "No, don't use that radius, use 10km instead, then I'll confirm.",
        "Perfect, publish it.",
        "Wait, I don't think that's the right target audience, let me reconsider.",
        "Confirmed, that's exactly the plan I wanted.",
    ]
    out = []
    for i in range(n):
        t = random.choice(templates).format(amt=random.choice([30, 60, 90]))
        out.append({"id": f"synth-cbc-{i:03d}", "content": t, "checkpoint_ns_prefix": "campaign_builder", "is_confirmation_turn": True})
    return out


def _campaign_manager_prompts(n: int) -> list[dict]:
    templates = [
        "How is my current campaign performing this week?",
        "Should I increase the daily budget on my {biz} campaign?",
        "Why did my impressions drop yesterday?",
        "Can you pause the campaign that's spending the most?",
        "What's my cost per click looking like compared to last week?",
        "Give me a breakdown of which ad set is performing best.",
        "Is my campaign profitable right now?",
        "What would happen if I doubled my budget?",
    ]
    out = []
    for i in range(n):
        t = random.choice(templates).format(biz=random.choice(BUSINESSES)[0])
        out.append({"id": f"synth-cm-{i:03d}", "content": t, "checkpoint_ns_prefix": "punk_agent", "is_confirmation_turn": False})
    return out


def _campaign_manager_confirmations(n: int) -> list[dict]:
    templates = [
        "Yes, go ahead and increase the budget.",
        "No, cancel that, I don't want to change anything.",
        "Actually pause it instead of increasing the budget.",
        "Confirmed, apply that change.",
        "Wait, undo that, I changed my mind.",
    ]
    out = []
    for i in range(n):
        out.append({"id": f"synth-cmc-{i:03d}", "content": random.choice(templates), "checkpoint_ns_prefix": "punk_agent", "is_confirmation_turn": True})
    return out


def _root_prompts(n: int) -> list[dict]:
    templates = [
        "What's the difference between a lookalike audience and interest-based targeting?",
        "How much should a small business typically spend on Meta ads per month?",
        "What's a good click-through rate for a local service business?",
        "Do you support TikTok ads too, or just Meta?",
        "Can you write me a joke about marketing budgets?",
        "What's the weather like today?",
        "How does the pixel actually work?",
        "I'm not sure what I want to advertise yet, what do you suggest for a new business?",
        "What's a lookback window and why does it matter?",
        "Can I target people by age and gender only, without any location?",
    ]
    out = []
    for i in range(n):
        out.append({"id": f"synth-root-{i:03d}", "content": random.choice(templates), "checkpoint_ns_prefix": "root", "is_confirmation_turn": False})
    return out


def main() -> None:
    examples = (
        _build_campaign_builder_prompts(35)
        + _campaign_builder_confirmations(15)
        + _campaign_manager_prompts(20)
        + _campaign_manager_confirmations(10)
        + _root_prompts(20)
    )
    for ex in examples:
        ex["pii_flags"] = []
        ex["_note"] = "SYNTHETIC — authored, not sampled from production (eval_readonly role not yet created)."

    random.shuffle(examples)
    assert len(examples) == 100, len(examples)

    with open(SAMPLE_INPUTS_PATH.replace("sample_inputs.json", "sample_inputs_100.json"), "w") as f:
        json.dump(examples, f, indent=2)
    print(f"Wrote {len(examples)} synthetic examples.")


if __name__ == "__main__":
    main()
