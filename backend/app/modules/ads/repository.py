from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from app.core.logging import logger
from app.shared.enums import AdPlatform
from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.user.models import User

class AdsRepository:
    async def _lead_pages(self, db: AsyncSession, *where) -> set[str]:
        """Pages whose leadgen webhook the matching ad accounts are subscribed to."""
        rows = await db.execute(select(AdsAccount.tracking_lead_page_id).where(*where))
        return {str(p) for p in rows.scalars() if p}

    async def _drop_lead_subscriptions(self, db: AsyncSession, page_ids: set[str]) -> None:
        """Turn off Meta's lead delivery for Pages no ad account claims any more.

        Removing an account deletes the only row that can route a lead back to it, so
        without this Meta keeps pushing that Page's leads at ``/tracking/webhook``
        for good, to be read and dropped. Call AFTER the removal commits: a failed
        removal must not leave the Page unsubscribed.

        The DELETE is Page-wide, so a Page another ad account still subscribed to
        (an agency's second client) is left alone. Needs no user token — it is
        called with the app's own — which is what lets it run after the connection
        row is gone. Best-effort: a Meta failure must never block a disconnect.
        """
        if not page_ids:
            return
        try:
            still_claimed = await self._lead_pages(
                db, AdsAccount.tracking_lead_page_id.in_(page_ids)
            )
            from app.services.meta_ads import unsubscribe_page_leadgen

            for page_id in sorted(page_ids - still_claimed):
                await unsubscribe_page_leadgen(page_id)
        except Exception:
            logger.warning("disconnect: could not unsubscribe leadgen for %s", page_ids, exc_info=True)

    async def save_user_oauth_tokens(
        self,
        user_id: str,
        platform: AdPlatform,
        tokens: Dict[str, Any],
        db: AsyncSession,
        _retrying: bool = False,
    ) -> None:
        """Save or update OAuth tokens for a specific platform in the database.

        Read-then-insert, so two callbacks racing can both miss the row and both
        try to insert. The ``(user_id, platform)`` unique constraint turns that
        into an IntegrityError instead of a duplicate row; the loser retries once
        and takes the update branch. Without the constraint the race produced a
        second row that permanently broke every read for that user.
        """
        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        )
        result = await db.execute(stmt)
        token_obj = result.scalar_one_or_none()

        expires_in = tokens.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        if not token_obj:
            token_obj = OAuthToken(
                user_id=user_id,
                platform=platform,
            )
            db.add(token_obj)

        token_obj.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            token_obj.refresh_token = tokens["refresh_token"]

        # Unconditional, not `if expires_at:`. A non-expiring system-user token's
        # response carries no `expires_in` at all, so `expires_at` computes to
        # None here — and the old guard skipped the assignment on None, which on
        # a *reconnect* from a user token to a system token left the row's stale
        # 60-day expiry in place. A never-expiring token was then declared dead
        # forever by _token_is_live/get_meta_credentials. None now clears it.
        token_obj.expires_at = expires_at
        if "token_type" in tokens:
            token_obj.token_type = tokens["token_type"]

        if "scope" in tokens:
            token_obj.scopes = tokens["scope"].split(" ")
        elif "scopes" in tokens:
            token_obj.scopes = tokens["scopes"]

        if "ad_account_id" in tokens:
            token_obj.ad_account_id = tokens["ad_account_id"]
        if "accessible_accounts" in tokens:
            accounts = tokens["accessible_accounts"] or []
            token_obj.accessible_accounts = accounts
            # Keep the user's existing pick when it is still one of their
            # accounts. This line used to be an unconditional
            # `accounts[0]["id"]`, which did two bad things: it silently moved a
            # multi-account user back to their first account on every reconnect,
            # and it raised IndexError on an empty list — 500ing the whole OAuth
            # callback for any new advertiser who has not created an ad account
            # yet.
            ids = {a.get("id") for a in accounts if isinstance(a, dict)}
            if token_obj.selected_account not in ids:
                token_obj.selected_account = accounts[0]["id"] if accounts else None

        if "page_id" in tokens:
            token_obj.page_id = tokens["page_id"]
        if "page_name" in tokens:
            token_obj.page_name = tokens["page_name"]
        if "meta_user_name" in tokens:
            token_obj.meta_user_name = tokens["meta_user_name"]
        if "meta_user_image" in tokens:
            token_obj.meta_user_image = tokens["meta_user_image"]

        try:
            # No `users.select_meta_id` write here any more. Under Facebook
            # Login for Business the token is a Business Integration System
            # User token, and `/me` on that token returns the system user, not
            # the person — there is no Meta app-scoped user id to store. (And
            # `select_meta_id` holds the *selected ad account id* everywhere
            # else it's written — app/modules/payment/service.py,
            # app/modules/user/service.py — so it was never the right column
            # for a person id anyway.)
            await db.flush()

            if "accessible_accounts" in tokens:
                from app.modules.ads.models import AdsAccount
                accounts = tokens["accessible_accounts"] or []
                
                existing_accs_stmt = select(AdsAccount).where(AdsAccount.oauth_token_id == token_obj.id)
                existing_accs_result = await db.execute(existing_accs_stmt)
                existing_accs = existing_accs_result.scalars().all()
                
                existing_ids = {acc.ad_account_id: acc for acc in existing_accs}
                new_ids = {a.get("id") for a in accounts if isinstance(a, dict) and a.get("id")}
                
                for acc_id, acc in existing_ids.items():
                    if acc_id not in new_ids:
                        await db.delete(acc)
                
                for acc in accounts:
                    if not isinstance(acc, dict): continue
                    acc_id = acc.get("id")
                    acc_name = acc.get("name")
                    if not acc_id: continue
                    
                    if acc_id in existing_ids:
                        existing_ids[acc_id].ad_account_name = acc_name
                    else:
                        new_ads_account = AdsAccount(
                            user_id=user_id,
                            oauth_token_id=token_obj.id,
                            ad_account_id=acc_id,
                            ad_account_name=acc_name
                        )
                        db.add(new_ads_account)

            await db.commit()
        except IntegrityError:
            if _retrying:
                raise
            # Someone else inserted the row between our SELECT and our INSERT.
            # Roll back and go round once more — the row exists now, so the
            # second pass updates it instead.
            await db.rollback()
            await self.save_user_oauth_tokens(
                user_id, platform, tokens, db, _retrying=True
            )

    async def get_user_tokens(self, db: AsyncSession, user_id: str):
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def disconnect_account(self, db: AsyncSession, user_id: str, platform: AdPlatform) -> bool:
        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        )
        result = await db.execute(stmt)
        token_obj = result.scalar_one_or_none()

        if not token_obj:
            return False

        pages = await self._lead_pages(db, AdsAccount.oauth_token_id == token_obj.id)
        # Explicitly delete related AdsAccount entries first
        await db.execute(delete(AdsAccount).where(AdsAccount.oauth_token_id == token_obj.id))

        if token_obj.platform == AdPlatform.meta:
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(select_meta_id=None)
            )

        await db.delete(token_obj)
        await db.commit()
        await self._drop_lead_subscriptions(db, pages)
        return True

    async def disconnect_connection_by_id(self, db: AsyncSession, user_id: str, oauth_token_id: str) -> bool:
        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.id == oauth_token_id
        )
        result = await db.execute(stmt)
        token_obj = result.scalar_one_or_none()

        if not token_obj:
            return False

        pages = await self._lead_pages(db, AdsAccount.oauth_token_id == token_obj.id)
        # Explicitly delete related AdsAccount entries first
        await db.execute(delete(AdsAccount).where(AdsAccount.oauth_token_id == token_obj.id))

        if token_obj.platform == AdPlatform.meta:
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(select_meta_id=None)
            )

        await db.delete(token_obj)
        await db.commit()
        await self._drop_lead_subscriptions(db, pages)
        return True

    async def remove_ads_account(
        self, db: AsyncSession, user_id: str, ad_account_id: str
    ) -> str:
        """Remove a single ad account, or refuse when it is paid for.

        Returns ``"removed" | "not_found" | "paid"`` rather than raising, so
        the router maps outcomes to status codes without a bespoke exception.
        Unlike ``disconnect_account``, the Meta connection itself survives —
        only this one account (and the ``ads_accounts`` row carrying its
        per-account tracking secrets) goes away — unless it was the last
        account, in which case the whole connection is dead weight and this
        delegates to ``disconnect_connection_by_id``.
        """
        from app.services.entitlement import ad_account_is_paid

        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == AdPlatform.meta,
        )
        result = await db.execute(stmt)
        token_obj = result.scalar_one_or_none()
        if not token_obj:
            return "not_found"

        accounts = token_obj.accessible_accounts or []
        if ad_account_id not in {a.get("id") for a in accounts if isinstance(a, dict)}:
            return "not_found"

        if await ad_account_is_paid(user_id, ad_account_id, db):
            return "paid"

        acc_stmt = select(AdsAccount).where(
            AdsAccount.oauth_token_id == token_obj.id,
            AdsAccount.ad_account_id == ad_account_id,
        )
        acc_result = await db.execute(acc_stmt)
        acc_obj = acc_result.scalar_one_or_none()
        pages = {str(acc_obj.tracking_lead_page_id)} if acc_obj and acc_obj.tracking_lead_page_id else set()
        if acc_obj:
            await db.delete(acc_obj)

        remaining = [a for a in accounts if a.get("id") != ad_account_id]
        if not remaining:
            # Last account — a connection with nothing left is dead weight;
            # the user reconnects to grant one again.
            await self.disconnect_connection_by_id(db, user_id, token_obj.id)
            await self._drop_lead_subscriptions(db, pages)
            return "removed"

        token_obj.accessible_accounts = remaining
        was_selected = token_obj.selected_account == ad_account_id
        if was_selected:
            token_obj.selected_account = remaining[0]["id"]
        if token_obj.ad_account_id == ad_account_id:
            token_obj.ad_account_id = remaining[0]["id"]

        if was_selected:
            # Keeps both selection columns in step like update_selected_account
            # does, but inline: that method commits, and this removal (the ads
            # row delete above included) must land as ONE transaction.
            await db.execute(
                update(User)
                .where(User.id == user_id, User.select_meta_id == ad_account_id)
                .values(select_meta_id=remaining[0]["id"])
            )

        await db.commit()
        await self._drop_lead_subscriptions(db, pages)
        return "removed"

    async def update_selected_account(self, db: AsyncSession, user_id: str, selected_account: str) -> bool:
        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == AdPlatform.meta
        )
        result = await db.execute(stmt)
        token_obj = result.scalar_one_or_none()

        if not token_obj:
            return False

        # Same membership idiom as save_user_oauth_tokens above: only an
        # account Meta actually granted this token access to is a legal pick.
        # This used to accept any string at all, including an account the
        # user has no Meta access to — there was no check here whatsoever.
        ids = {a.get("id") for a in (token_obj.accessible_accounts or []) if isinstance(a, dict)}
        if selected_account not in ids:
            return False

        # Nothing to invalidate on a switch: the dataset lives on the ads_accounts
        # row it belongs to, so picking another account reads that account's own
        # tracking state. This used to NULL a connection-level dataset here, which
        # is the special case the grain change deleted — don't put it back.
        token_obj.selected_account = selected_account
        # users.select_meta_id mirrors this column and the two are read by
        # different halves of the app: publish/campaign-list read selected_account
        # (oauth.get_meta_credentials), the profile UI reads select_meta_id. Both
        # move here under ONE commit — every selection write goes through this
        # method. Callers used to write select_meta_id alone (payment's
        # assign_ad_account), so a user could pay for B while Punk kept
        # publishing into A; and user/service committed this column first and the
        # user row second, leaving a window where the two disagreed.
        await db.execute(
            update(User).where(User.id == user_id).values(select_meta_id=selected_account)
        )
        await db.commit()
        return True

    async def get_meta_connection(self, db: AsyncSession, user_id: str) -> OAuthToken | None:
        """The user's Meta connection row, or None.

        The whole row — credentials, selected account, page — not just what
        ``oauth.get_meta_credentials`` returns. Tracking state hangs off the
        ``ads_accounts`` row this connection points at, see
        ``get_tracking_account``.
        """
        stmt = select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == AdPlatform.meta,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_account_by_lead_page_id(
        self, db: AsyncSession, page_id: str
    ) -> AdsAccount | None:
        """Resolve an ad account from the Page its leadgen webhook fires for.

        Unscoped by user for the same reason as ``get_account_by_ingest_key``:
        Meta is the caller and holds no login. Unlike the ingest key this is not a
        secret — the payload it arrives in is authenticated by its HMAC signature
        instead, which is checked before this is ever reached.

        The connection rides along because forwarding the lead needs its token.

        ponytail: newest subscriber wins if two ad accounts subscribed the same
        Page. Split per-account if an agency ever hits it.
        """
        if not page_id:
            return None
        stmt = (
            select(AdsAccount)
            .where(AdsAccount.tracking_lead_page_id == str(page_id))
            .order_by(AdsAccount.updated_at.desc())
            .options(selectinload(AdsAccount.oauth_token))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_account_by_ingest_key(
        self, db: AsyncSession, ingest_key: str
    ) -> AdsAccount | None:
        """Resolve an ad account from its conversion-ingest key.

        The only lookup in this repository that is not scoped by user_id — it is
        how the customer's own website identifies itself, since it holds no login.
        The caller still re-compares the key in constant time.

        The connection rides along because sending needs its token: one query, and
        the row is useless without it.
        """
        if not ingest_key:
            return None
        stmt = (
            select(AdsAccount)
            .where(AdsAccount.tracking_ingest_key == ingest_key)
            .options(selectinload(AdsAccount.oauth_token))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_tracking_account(
        self, db: AsyncSession, user_id: str
    ) -> AdsAccount | None:
        """The ad account tracking reads and writes, or None when not connected.

        The user's currently selected account — the one campaigns publish into —
        with its connection loaded. Created on demand: a connection made before
        ``ads_accounts`` existed has no rows until the user reconnects, and a
        missing row must not read as "tracking is off".
        """
        conn = await self.get_meta_connection(db, user_id)
        if not conn or not conn.selected_account:
            return None
        stmt = (
            select(AdsAccount)
            .where(
                AdsAccount.oauth_token_id == conn.id,
                AdsAccount.ad_account_id == conn.selected_account,
            )
            .options(selectinload(AdsAccount.oauth_token))
        )
        account = (await db.execute(stmt)).scalars().first()
        if account:
            return account

        account = AdsAccount(
            user_id=conn.user_id,
            oauth_token_id=conn.id,
            ad_account_id=conn.selected_account,
            ad_account_name=conn.ad_account_name,
        )
        db.add(account)
        try:
            await db.commit()
        except IntegrityError:
            # uq_ads_accounts_token_account: someone else inserted it between our
            # SELECT and our INSERT. Their row is the row.
            await db.rollback()
            return (await db.execute(stmt)).scalars().first()
        await db.refresh(account)
        return account

    async def save_tracking_state(
        self, db: AsyncSession, user_id: str, **fields: Any
    ) -> bool:
        """Write the ad account's tracking_* columns, only those actually passed.

        Same "only if it was sent" rule as ``save_user_oauth_tokens``: a caller
        resolving the dataset must not blank the ingest key a customer already
        installed in their site snippet.
        """
        allowed = {
            "tracking_dataset_id",
            "tracking_business_id",
            "tracking_ingest_key",
            "tracking_system_user_token",
            "tracking_event_type",
            "tracking_method",
            "tracking_lead_page_id",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"save_tracking_state: unknown field(s) {sorted(unknown)}")

        account = await self.get_tracking_account(db, user_id)
        if not account:
            return False
        for key, value in fields.items():
            setattr(account, key, value)
        await db.commit()
        return True