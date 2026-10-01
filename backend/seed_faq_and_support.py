#!/usr/bin/env python
import asyncio
import uuid
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

async def seed_data():
    import app.db.model_registry  # Force mapper registration
    from app.db.database import AsyncSessionLocal
    from app.modules.faq.models import FAQCategory, FAQ
    from app.modules.support.models import Support
    from app.shared.enums import FAQCategoryType, SupportStatus
    from sqlalchemy import select

    print("=== Seeding FAQ and Support Data ===")
    async with AsyncSessionLocal() as db:
        # 1. Categories
        categories_to_seed = [
            {
                "name": "Tokens & usage",
                "description": "Questions regarding AI token consumption, bundles, and monthly reset",
                "type": FAQCategoryType.both,
                "faqs": [
                    {
                        "question": "How do tokens work?",
                        "answer": "Tokens represent units of AI processing power. Every prompt, creative variation, image generation, and chat interaction consumes tokens based on the complexity and model used. Tokens reset monthly with your plan.",
                    },
                    {
                        "question": "What happens when I run out of tokens mid-month?",
                        "answer": "Conversations pause until you either buy a token bundle or your plan renews. Nothing is lost — your chat history stays intact and picks up exactly where it stopped once you have tokens again.",
                    },
                    {
                        "question": "Do I need a subscription to buy token bundles?",
                        "answer": "Yes, token add-on bundles are available to any active subscription tier (Basic, Standard, and Pro). Bundles never expire and roll over indefinitely.",
                    },
                ]
            },
            {
                "name": "Billing & plans",
                "description": "Invoicing, card charges, plan upgrades, and refund policy",
                "type": FAQCategoryType.both,
                "faqs": [
                    {
                        "question": "What does the Pro plan include?",
                        "answer": "The Pro plan includes unlimited AI ad variations, multi-channel automated budget pacing, priority conversion API synchronization (sub-second latency), 50 concurrent SSE streaming connections, and dedicated Slack/Teams support.",
                    },
                    {
                        "question": "I was charged twice — what should I do?",
                        "answer": "If you notice a duplicate charge on your card, it is usually an authorization hold from your bank during renewal. If both charges settle, submit an inquiry below or email billing@punkai.io and our team will issue an instant refund within 24 hours.",
                    },
                ]
            },
            {
                "name": "Troubleshooting",
                "description": "Technical connectivity, webhooks, and browser troubleshooting",
                "type": FAQCategoryType.both,
                "faqs": [
                    {
                        "question": "Punk AI stopped responding mid-answer.",
                        "answer": "This typically occurs if your browser lost WebSocket connectivity during a streaming generation. Refresh your page or check the System Status indicator in the top right. If the issue persists, clear your browser cache or re-authenticate.",
                    },
                    {
                        "question": "The Meta Ads Manager webhook is failing.",
                        "answer": "Ensure your Meta Pixel and Conversion API access tokens are valid and have not expired in your Meta Business Suite.",
                    },
                ]
            },
            {
                "name": "Account & access",
                "description": "Team members, roles, workspace sharing, and security",
                "type": FAQCategoryType.both,
                "faqs": [
                    {
                        "question": "How do I invite teammates to our shared Punk AI workspace?",
                        "answer": "Navigate to People > Users and click the 'Add New User' button. Enter their email address and select their access level. They will receive an email invitation to join your workspace immediately.",
                    },
                    {
                        "question": "Can I enforce SSO or 2-Factor Authentication for our team?",
                        "answer": "Yes, Workspace Admins can enforce Google SSO, Microsoft Entra ID, and mandatory TOTP 2-Factor Authentication directly from System > Security settings.",
                    },
                ]
            },
        ]

        cat_map = {}
        for cat_data in categories_to_seed:
            res = await db.execute(select(FAQCategory).where(FAQCategory.name.ilike(cat_data["name"])))
            existing_cat = res.scalar_one_or_none()
            if not existing_cat:
                cat = FAQCategory(
                    id=uuid.uuid4(),
                    name=cat_data["name"],
                    description=cat_data["description"],
                    type=cat_data["type"],
                    is_active=True,
                )
                db.add(cat)
                await db.commit()
                await db.refresh(cat)
                print(f"Created category: {cat.name}")
                cat_map[cat.name] = cat
            else:
                cat_map[cat_data["name"]] = existing_cat

            # Seed FAQs for category
            cat_obj = cat_map[cat_data["name"]]
            for faq_item in cat_data["faqs"]:
                f_res = await db.execute(select(FAQ).where(FAQ.question == faq_item["question"]))
                existing_faq = f_res.scalar_one_or_none()
                if not existing_faq:
                    new_faq = FAQ(
                        id=uuid.uuid4(),
                        category_id=cat_obj.id,
                        question=faq_item["question"],
                        answer=faq_item["answer"],
                        is_active=True,
                    )
                    db.add(new_faq)
                    await db.commit()
                    print(f" - Created FAQ: {new_faq.question}")

        # 2. Support Tickets
        tickets_to_seed = [
            {
                "name": "Alex Rahman",
                "email": "you@company.com",
                "problem_type": "Tokens & usage",
                "description": "Our automated creative generation batch halted today at 4,000 variations due to monthly token quota limits. Can we get an emergency top-up bundle allocated to our billing profile?",
                "status": SupportStatus.OPEN,
                "category_name": "Tokens & usage",
            },
            {
                "name": "Sarah Jenkins",
                "email": "sarah.j@growthmedia.io",
                "problem_type": "Billing & plans",
                "description": "We upgraded to the Pro tier annual plan this morning, but our workspace seat limit still shows 5 seats instead of unlimited. Please update our seat provisioning.",
                "status": SupportStatus.IN_PROGRESS,
                "category_name": "Billing & plans",
            },
            {
                "name": "Marcus Vance",
                "email": "marcus.v@hyperpulse.ai",
                "problem_type": "Troubleshooting",
                "description": "The TikTok Ads CAPI webhook integration keeps throwing HTTP 504 gateway timeout errors on high-volume event batches. Logs are attached.",
                "status": SupportStatus.OPEN,
                "category_name": "Troubleshooting",
            },
            {
                "name": "Elena Rostova",
                "email": "elena@adpeak.co",
                "problem_type": "Account & access",
                "description": "Need assistance configuring SAML 2.0 Single Sign-On via Okta for 45 team members across our regional marketing departments.",
                "status": SupportStatus.RESOLVED,
                "category_name": "Account & access",
            },
        ]

        for t in tickets_to_seed:
            t_res = await db.execute(select(Support).where(Support.email == t["email"], Support.description == t["description"]))
            existing_t = t_res.scalar_one_or_none()
            if not existing_t:
                cat_for_ticket = cat_map.get(t["category_name"])
                new_ticket = Support(
                    id=uuid.uuid4(),
                    name=t["name"],
                    email=t["email"],
                    problem_type=t["problem_type"],
                    description=t["description"],
                    status=t["status"],
                    category_id=cat_for_ticket.id if cat_for_ticket else None,
                )
                db.add(new_ticket)
                await db.commit()
                print(f"Created ticket: {new_ticket.name} ({new_ticket.problem_type})")

        print("=== Seeding Completed Successfully ===")

if __name__ == "__main__":
    asyncio.run(seed_data())
