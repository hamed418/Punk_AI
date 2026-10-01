#!/usr/bin/env python
"""
seed_super_admin.py
-------------------
Creates or updates a Super Admin user account in the database.

Usage:
    python seed_super_admin.py

Environment variables (or .env file):
    SUPER_ADMIN_EMAIL      — email for the super admin account (default: superadmin@punkai.com)
    SUPER_ADMIN_PASSWORD   — password for the super admin account (default: SuperAdmin@123!)
    SUPER_ADMIN_NAME       — display name (default: Super Admin)

This script is idempotent — safe to run multiple times.
If the user exists, their role is promoted to super_admin.
If the user doesn't exist, they are created with super_admin role.
"""

import asyncio
import os
import sys
from pathlib import Path

# ── Load .env if available ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded .env from {env_path}")
except ImportError:
    pass  # python-dotenv not installed; rely on os env

# ── Config ───────────────────────────────────────────────────────────────────
SUPER_ADMIN_EMAIL    = os.getenv("SUPER_ADMIN_EMAIL", "superadmin@punkai.com")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "SuperAdmin@123!")
SUPER_ADMIN_NAME     = os.getenv("SUPER_ADMIN_NAME", "Super Admin")


async def seed():
    # Import after env is loaded so settings can pick up DB URL
    import app.db.model_registry  # noqa: F401 — force all SQLAlchemy mappers to register
    from app.db.database import AsyncSessionLocal
    from app.modules.user.models import User
    from app.shared.enums import UserRole
    from app.core.security import hash_password
    from sqlalchemy import select
    from starlette.concurrency import run_in_threadpool

    print("=" * 55)
    print("  Punk AI — Super Admin Seed Script")
    print("=" * 55)
    print(f"  Email : {SUPER_ADMIN_EMAIL}")
    print(f"  Name  : {SUPER_ADMIN_NAME}")
    print("=" * 55)

    async with AsyncSessionLocal() as db:
        try:
            # Check for existing user
            result = await db.execute(
                select(User).where(User.email == SUPER_ADMIN_EMAIL.lower())
            )
            user = result.scalar_one_or_none()

            hashed_pw = await run_in_threadpool(hash_password, SUPER_ADMIN_PASSWORD)

            if user:
                # Update existing user to super_admin
                old_role = user.role.value if hasattr(user.role, "value") else user.role
                user.role = UserRole.super_admin
                user.password_hash = hashed_pw
                user.is_active = True
                user.is_verified = True
                if not user.full_name:
                    user.full_name = SUPER_ADMIN_NAME
                db.add(user)
                await db.commit()
                await db.refresh(user)
                print(f"\n✅ Updated existing user '{user.email}'")
                print(f"   Role changed: {old_role} → super_admin")
                print(f"   Password updated, is_active=True, is_verified=True")
            else:
                # Create new super_admin user
                import uuid
                user = User(
                    id=uuid.uuid4(),
                    email=SUPER_ADMIN_EMAIL.lower(),
                    password_hash=hashed_pw,
                    full_name=SUPER_ADMIN_NAME,
                    role=UserRole.super_admin,
                    is_active=True,
                    is_verified=True,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                print(f"\n✅ Created new Super Admin user")
                print(f"   ID    : {user.id}")
                print(f"   Email : {user.email}")
                print(f"   Role  : {user.role.value}")

            print("\n" + "=" * 55)
            print("  Super Admin is ready.")
            print("  Login at: POST /auth/admin/login")
            print("=" * 55 + "\n")

        except Exception as e:
            await db.rollback()
            print(f"\n❌ Seed failed: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(seed())
