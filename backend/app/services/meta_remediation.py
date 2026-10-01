"""
services/meta_remediation.py
────────────────────────────
The things Meta will not let Punk do for the user, and what to tell them instead.

Publishing a campaign, wiring conversion tracking, and building a custom audience all
have prerequisites the Graph API deliberately does not expose: accepting Custom Audience
Terms, attaching a payment method, verifying a domain or a business, accepting Lead Ads
terms, granting a Page role, linking an Instagram account, connecting a WhatsApp number,
configuring Aggregated Event Measurement, installing the pixel on the site. A token with
every scope in the world still cannot do any of them — they are consent and identity, and
Meta requires a human on a Meta screen.

Before this module, those landed on the user as Meta's raw prose behind "adjust the plan
and try again", which is wrong advice twice over: the plan is fine, and the fix is on a
page Punk never named.

Three ways a prerequisite is discovered, all answering with the same ``Remediation``:

  * **Before the work** — ``ad_account_blockers`` in ``meta_ads`` reads the account once at
    connect and hands back entries. Cheapest place to learn about a missing payment method.
  * **When Meta refuses** — ``resolve`` maps a ``MetaAdsError`` onto an entry.
  * **When Meta never complains at all** — ``check_plan_assets`` compares what the plan
    BUYS against what the Page actually HAS. An ad set bought on Instagram placements with
    no Instagram account linked publishes perfectly cleanly and then runs under a
    Page-backed identity nobody asked for. There is no error to catch; the only way to
    know is to look.

The catalog is a module-level dict on purpose. It is copy, it changes with a deploy, and a
database table for eighteen paragraphs of text would be a schema to maintain forever.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Remediation:
    """One thing the user has to go do in Meta, and what Punk does meanwhile."""

    key: str
    title: str
    # Why Meta refused, in plain words. Says out loud that the API cannot do it —
    # otherwise the obvious question is "why doesn't Punk just do that for me?".
    cause: str
    steps: tuple[str, ...]
    # Deep link to the exact Meta surface, as a format template over the ids in
    # ``render``. Never shown with an unfilled placeholder in it.
    url: str = ""
    # What Punk does about it right now, so the user is not left guessing whether
    # their campaign is half-built and spending.
    effect: str = ""
    # "blocks"   — cannot proceed until a human does this
    # "degrades" — Punk proceeds with less (geo-only instead of the audience)
    # "warns"    — proceeds fully, but the user is losing something they'd want
    severity: str = "blocks"
    # Which surfaces may raise it. Also disambiguates the code-only matches, where
    # one Meta code means different things at different steps.
    scopes: tuple[str, ...] = ("publish",)

    # ── matching (not part of the wire shape) ────────────────────────────────
    # Meta's ``error_subcode``. The most precise signal there is — and the one
    # Meta documents least, so only confirmed values belong here.
    subcodes: tuple[int, ...] = ()
    # Lowercased substrings of the error message / error_user_msg. The honest
    # fallback for every rejection whose subcode we have not seen in a real log.
    phrases: tuple[str, ...] = ()
    # Top-level ``code``. Only ever matched together with a scope, because a bare
    # code is far too broad on its own.
    codes: tuple[int, ...] = ()


_ADS_MANAGER = "https://adsmanager.facebook.com"
_BUSINESS = "https://business.facebook.com"


# Ordered because ``resolve`` walks it: put the specific before the general within
# each family, so a Custom Audience terms rejection never matches the account-level
# entry that happens to share a code.
CATALOG: dict[str, Remediation] = {}


def _entry(rem: Remediation) -> Remediation:
    CATALOG[rem.key] = rem
    return rem


# ── ad account: money, standing, permissions ─────────────────────────────────

# ── nothing to publish with yet ──────────────────────────────────────────────
# A brand-new advertiser can finish Meta's login and still hand Punk nothing to
# work with: no ad account, no Page. Both are created by the person, on Meta, and
# both are shared with an app only when ticked on the consent screen — so "connect
# again" is part of the fix either way. No codes/phrases: never matched off an
# exception, raised by looking at what the connection actually contains.

_entry(Remediation(
    key="no_ad_account",
    title="Meta shared no ad account with Punk",
    cause=(
        "Punk is connected, but Meta handed over no ad account to publish into. Either you "
        "have not created one yet, or it was not ticked on Meta's consent screen. Creating "
        "an ad account is something only you can do, on Meta."
    ),
    steps=(
        "Open Business settings → Accounts → Ad accounts and create an ad account.",
        "Come back and connect Meta again, and tick that ad account on Meta's consent screen.",
    ),
    url=f"{_BUSINESS}/settings/ad-accounts",
    effect="Nothing was created in Meta and nothing is spending.",
    severity="blocks",
    scopes=("publish", "manage"),
))

_entry(Remediation(
    key="no_facebook_page",
    title="Meta shared no Facebook Page with Punk",
    cause=(
        "Ads run as a Facebook Page, and Meta handed Punk none. Either you do not have a "
        "Page yet, or it was not ticked on Meta's consent screen — Punk only sees the Pages "
        "you share. Creating a Page, or getting a role on one, is something only you can do."
    ),
    steps=(
        "Create a Facebook Page, or ask an admin of an existing one to give you an Admin or "
        "Advertiser role.",
        "Come back and connect Meta again, and tick the Page on Meta's consent screen.",
    ),
    url="https://www.facebook.com/pages/create",
    effect="Nothing was created in Meta and nothing is spending.",
    severity="blocks",
    scopes=("publish", "manage"),
))

# ── after publish: Meta reviews every new ad ─────────────────────────────────
# Read off the ads themselves (``review_cards``), never matched off an exception.

_entry(Remediation(
    key="ads_in_review",
    title="Meta is reviewing your ads",
    cause=(
        "Every new ad is reviewed by Meta before it delivers, and a new ad account is "
        "reviewed more slowly. It is usually done within a day."
    ),
    steps=("Nothing to do — delivery starts by itself once the review passes.",),
    effect="Your campaign is set up; it just has not started delivering yet.",
    severity="warns",
    scopes=("manage",),
))

_entry(Remediation(
    key="ads_disapproved",
    title="Meta rejected one or more of your ads",
    cause=(
        "Meta reviewed the ads and turned some down, so they will not deliver. The reason "
        "Meta gave is below. Whether to appeal or change the ad is your call — Punk does "
        "not resubmit ads on your behalf."
    ),
    steps=(
        "Open the ads in Ads Manager and read Meta's reason for each.",
        "Edit the ad to fix it, or request a review if you think it was a mistake.",
    ),
    url=f"{_ADS_MANAGER}/adsmanager/manage/ads",
    effect="The rejected ads are not delivering; ads Meta approved are unaffected.",
    severity="blocks",
    scopes=("manage",),
))

_entry(Remediation(
    key="ad_account_no_payment",
    title="Your ad account has no payment method",
    cause=(
        "Meta will not create a campaign on an ad account it cannot bill. Adding a card "
        "or a payment method is done by an account admin in Ads Manager — there is no "
        "API for it, for the obvious reason."
    ),
    steps=(
        "Open Billing & payments for this ad account.",
        "Add a payment method and set it as primary.",
        "Come back and publish again — your plan is saved exactly as it is.",
    ),
    url=f"{_ADS_MANAGER}/ads/manage/account_settings/account_billing?act={{ad_account_id}}",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "audience", "manage"),
    phrases=("payment method", "funding source", "no payment"),
))

_entry(Remediation(
    key="ad_account_disabled",
    title="Meta has disabled this ad account",
    cause=(
        "The account is disabled or under review, so Meta refuses every write to it. "
        "Only an appeal in Account Quality can lift that — it is a decision about the "
        "account, not something a campaign can be edited around."
    ),
    steps=(
        "Open Account Quality and find this ad account.",
        "Read what Meta says the issue is, and request a review if you disagree.",
        "Once the account is active again, publish from here — nothing is lost.",
    ),
    url=f"{_BUSINESS}/accountquality",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "audience", "manage"),
    phrases=("account is disabled", "ad account is disabled", "account has been disabled"),
))

_entry(Remediation(
    key="ad_account_spend_limit",
    title="This ad account has hit its spending limit",
    cause=(
        "The account-level spending limit has been reached, so Meta will not let a new "
        "campaign start delivering. Raising or clearing it is an admin action in billing."
    ),
    steps=(
        "Open Billing & payments for this ad account.",
        "Under Account spending limit, raise it or remove it.",
        "Publish again — or switch the campaign on in Ads Manager if it is already built.",
    ),
    url=f"{_ADS_MANAGER}/ads/manage/account_settings/account_billing?act={{ad_account_id}}",
    effect="Anything already built is PAUSED and not spending.",
    severity="blocks",
    scopes=("publish", "manage"),
    phrases=("spending limit", "spend limit", "spend cap"),
))

_entry(Remediation(
    key="two_factor_required",
    title="Meta wants two-factor authentication on this business",
    cause=(
        "The business enforces two-factor authentication for everyone who touches its ad "
        "accounts, and the connected account has not set it up. Meta refuses the call "
        "until it is — that is the whole point of the requirement."
    ),
    steps=(
        "Turn on two-factor authentication on the Facebook account you connected to Punk.",
        "Reconnect Meta in Punk so the new session carries it.",
        "Publish again.",
    ),
    url=f"{_BUSINESS}/settings/security",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "audience", "tracking", "manage"),
    phrases=("two factor", "two-factor", "2fa"),
))

_entry(Remediation(
    key="page_role_missing",
    title="You need an admin role on this Facebook Page",
    cause=(
        "Ads run as a Page, and Meta only lets someone with an admin (or advertiser) role "
        "publish under it. Granting yourself a role is done by an existing Page admin — "
        "an API call cannot hand out permissions over a Page it does not control."
    ),
    steps=(
        "Ask an admin of the Page to give your account an Admin or Advertiser role, in "
        "Page settings → Page access.",
        "Accept the invitation.",
        "Reconnect Meta in Punk so the new permission is in your session, then publish.",
    ),
    url=f"{_BUSINESS}/settings/pages",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "manage"),
    phrases=(
        "must be an administrator of the page",
        "does not have permission to access the page",
        "pages_manage_ads",
    ),
))

_entry(Remediation(
    key="leadgen_tos",
    title="Lead Ads terms have not been accepted for this Page",
    cause=(
        "Instant forms collect people's contact details, so Meta requires a Page admin to "
        "accept the Lead Ads Terms of Service first. It is a consent — it cannot be "
        "accepted through the API on someone's behalf."
    ),
    steps=(
        "Open the Lead Ads terms for this Page.",
        "Sign in as a Page admin and accept them.",
        "Come back and publish again.",
    ),
    url="https://www.facebook.com/ads/leadgen/tos?page_id={page_id}",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish",),
    phrases=("lead gen terms", "leadgen terms", "terms of service have not been accepted"),
))

# Graph code 3 — "this app does not have the capability for this endpoint". That is
# the APP's access level (Standard vs Advanced, granted by App Review), not the
# user's token, so reconnecting cannot fix it: the same login mints the same
# grant. It used to share a card with 200/10/190 and send the advertiser round a
# reconnect loop. Nothing the advertiser does in Meta clears it, hence no url.
_entry(Remediation(
    key="app_access_level",
    title="Punk isn't approved for this Meta action yet",
    cause=(
        "Meta is refusing this call because Punk's app itself does not have the access "
        "level the action needs — it is not a problem with your account or your "
        "permissions, and reconnecting will not change it. Meta grants that access "
        "to the app after review, so only Punk can fix it."
    ),
    steps=(
        "Nothing to do on your side — please tell Punk support that Meta answered "
        "\"the app does not have the capability for this endpoint\".",
        "Do not keep reconnecting Meta; it will fail the same way.",
    ),
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "audience", "manage"),
    codes=(3,),
))

_entry(Remediation(
    key="app_missing_ads_management",
    title="Meta is refusing this call for permissions",
    cause=(
        "The connected session is missing the Ads Management access this action needs. "
        "Retrying the same way will keep failing — nothing about the campaign is wrong."
    ),
    steps=(
        "Reconnect your Meta account in Punk and accept every permission it asks for.",
        "If it still fails, check in Business settings that your account has an "
        "Advertiser or Admin role on this ad account.",
    ),
    url=f"{_BUSINESS}/settings/ad-accounts",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    # Not "tracking": a CAPI feed's 190 is not fixed by reconnecting, it is fixed
    # by a system user token — see tracking_token_expired, which owns that scope.
    scopes=("publish", "audience", "manage"),
    codes=(200, 10, 190),
))


# Raised at connect off the account's ``user_tasks`` — never matched off an exception
# (``app_missing_ads_management`` owns the refusal itself, and reads as one).
_entry(Remediation(
    key="ad_account_role_missing",
    title="You don't have an advertiser role on this ad account",
    cause=(
        "Meta lets you see this ad account, but your role on it is read-only or "
        "draft-only, and creating ads needs an Advertiser or Admin role. Roles are "
        "granted by an existing admin of the account — Punk cannot give you one."
    ),
    steps=(
        "Ask an admin of the ad account to give you the Advertiser or Admin role, in "
        "Business settings → Accounts → Ad accounts → Add people.",
        "Accept the invitation, then reconnect Meta in Punk.",
    ),
    url=f"{_BUSINESS}/settings/ad-accounts",
    effect="Nothing has been created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "manage"),
))


# ── business standing / special categories ───────────────────────────────────

_entry(Remediation(
    key="business_not_verified",
    title="This business needs to be verified",
    cause=(
        "Meta gates parts of the API behind business verification — a one-off check of "
        "your legal business details and documents in the Security Center. Nobody can do "
        "it for you, and no permission substitutes for it."
    ),
    steps=(
        "Open Security Center for your business.",
        "Start business verification and upload the documents Meta asks for.",
        "Verification usually takes a couple of days; publish from here once it clears.",
    ),
    url=f"{_BUSINESS}/settings/security?business_id={{business_id}}",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "audience", "tracking"),
    phrases=("business verification", "verify your business", "unverified business"),
))

_entry(Remediation(
    key="special_ad_category_cert",
    title="Meta wants this account certified for the ad category",
    cause=(
        "Housing, employment and credit ads are restricted. Where Meta requires it, an "
        "admin has to complete a one-off certification for the ad account before any ad "
        "in that category can run. Whether it applies depends on your country."
    ),
    steps=(
        "Open Account Quality and look for a certification or restricted-category task.",
        "Complete it as an admin of the ad account.",
        "Publish again once Meta shows the account as certified.",
    ),
    url=f"{_BUSINESS}/accountquality",
    effect="Anything already built is PAUSED and not spending.",
    severity="blocks",
    scopes=("publish",),
    phrases=("special ad category", "restricted category", "certification"),
))


# ── custom audiences ─────────────────────────────────────────────────────────

_entry(Remediation(
    key="custom_audience_tos",
    title="Custom Audience Terms have not been accepted",
    cause=(
        "Before an ad account can hold an audience built from a customer list, Meta needs "
        "an admin to accept the Custom Audience Terms of Service. It is a legal consent "
        "about the data — the API is not allowed to accept it for you."
    ),
    steps=(
        "Open the Custom Audience Terms for this ad account.",
        "Sign in as an admin of the account and accept them.",
        "Come back and hit publish again — the audience will be built then.",
    ),
    url=f"{_BUSINESS}/ads/manage/customaudiences/tos/?act={{ad_account_id}}",
    effect="Publishing carries on without the audience, targeted by location only.",
    severity="degrades",
    scopes=("audience", "publish"),
    subcodes=(1870034,),
    # 2663 measured live on 2026-08-20 building a website audience: "(#2663)
    # Terms of service has not been accepted." Same consent, different code from
    # the customer-list path — without it the one error a user can actually fix
    # came back as a raw Graph string.
    codes=(2654, 2663),
    phrases=("custom audience terms", "terms of service", "accept the terms"),
))

_entry(Remediation(
    key="audience_needs_business",
    title="This ad account isn't in a Meta Business",
    cause=(
        "Meta only allows a customer-list Custom Audience on an ad account that belongs "
        "to a Business. Yours sits on a personal account, so it will not hold the visitor "
        "audience we built from the places you picked."
    ),
    steps=(
        "Open Business settings and create a business portfolio if you don't have one.",
        "Add this ad account to it under Accounts → Ad accounts.",
        "Reconnect Meta in Punk, then publish — the audience will be built then.",
    ),
    url=f"{_BUSINESS}/settings/ad-accounts",
    effect="Publishing carries on without the audience, targeted by location only.",
    severity="degrades",
    scopes=("audience", "publish"),
    subcodes=(1870050,),
    phrases=("business account needed",),
))

_entry(Remediation(
    key="audience_too_small",
    title="This audience is too small to deliver",
    cause=(
        "Meta needs at least about 100 matched people in an audience before it will "
        "deliver to it, and fewer than that matched. Nothing is broken — there simply "
        "are not enough profiles behind the places selected."
    ),
    steps=(
        "Widen the area or add more locations, then rebuild the audience.",
        "Or publish targeted by location only — it reaches the same places, less precisely.",
    ),
    url=f"{_ADS_MANAGER}/adsmanager/audiences?act={{ad_account_id}}",
    effect="Publishing carries on without the audience, targeted by location only.",
    severity="degrades",
    scopes=("audience",),
    phrases=("audience is too small", "below the minimum size", "too small to"),
))

_entry(Remediation(
    key="lookalike_source_too_small",
    title="The lookalike source audience is too small",
    cause=(
        "A lookalike needs at least about 100 matched people from one country in its "
        "source audience. Meta will not build one from fewer."
    ),
    steps=(
        "Widen the area so the source audience has more people in it.",
        "Or publish with the seed audience and locations only, no lookalike.",
    ),
    url=f"{_ADS_MANAGER}/adsmanager/audiences?act={{ad_account_id}}",
    effect="Publishing carries on without the lookalike.",
    severity="degrades",
    scopes=("audience",),
    phrases=("lookalike source", "source audience is too small"),
))

_entry(Remediation(
    key="audience_still_matching",
    title="Meta is still matching this audience",
    cause=(
        "The profiles were uploaded and Meta is working through them. It usually takes "
        "under an hour, occasionally longer, and there is nothing to do but wait."
    ),
    steps=(
        "Check the audience in Ads Manager in an hour.",
        "Once its size stops saying 'Below 1000' or 'Populating', it is ready.",
    ),
    url=f"{_ADS_MANAGER}/adsmanager/audiences?act={{ad_account_id}}",
    effect="The campaign can still publish — delivery picks the audience up once it is ready.",
    severity="warns",
    scopes=("audience",),
    phrases=("still populating", "audience is not ready"),
))


# ── Page assets the plan buys but the Page doesn't have ──────────────────────
# These mostly fire with NO Meta error: see check_plan_assets.

_entry(Remediation(
    key="instagram_not_linked",
    title="No Instagram account is linked to this Page",
    cause=(
        "Your ads are set to run on Instagram, but the Page has no Instagram account "
        "connected. Meta will still show them — as the Page, under a placeholder profile "
        "with no bio, no posts and no way for anyone to follow you. Comments and DMs land "
        "somewhere you cannot see. Linking the account is done in Page settings; the API "
        "cannot connect one Meta identity to another."
    ),
    steps=(
        "Make sure your Instagram account is a Business or Creator account "
        "(Instagram app → Settings → Account type).",
        "In Page settings → Linked accounts, connect that Instagram account.",
        "Reconnect Meta in Punk so we can see it, then publish.",
    ),
    url=f"{_BUSINESS}/settings/instagram-account-v2",
    effect="The campaign still publishes — Instagram placements just run as the Page.",
    severity="warns",
    scopes=("publish",),
    # 3907008 is measured, not guessed: "Your ad must be associated with an
    # Instagram account", the rejection an Instagram-profile destination gets at
    # ad creation — past the preflight rollback, with the campaign already built.
    # See objective_matrix's INSTAGRAM_PROFILE rules, which declare the same
    # prerequisite so the editor can say it while the destination is being picked.
    subcodes=(3907008,),
    phrases=("associated with an instagram account", "instagram_actor_id"),
))

_entry(Remediation(
    key="instagram_not_business_account",
    title="That Instagram account can't run ads yet",
    cause=(
        "Only Business and Creator accounts can be advertised through. A personal "
        "Instagram account has to be switched over in the Instagram app — it is a setting "
        "on the account, not something the API can change from outside."
    ),
    steps=(
        "In the Instagram app: Settings → Account type and tools → Switch to professional.",
        "Pick Business or Creator.",
        "Link it to your Facebook Page, reconnect Meta in Punk, then publish.",
    ),
    url=f"{_BUSINESS}/settings/instagram-account-v2",
    effect="Instagram placements run as the Page until this is sorted.",
    severity="warns",
    scopes=("publish",),
    phrases=("not a business account", "professional account"),
))

_entry(Remediation(
    key="page_whatsapp_missing",
    title="This Page has no WhatsApp number linked",
    cause=(
        "A Click-to-WhatsApp ad opens a chat with the number linked to the Page, and this "
        "Page has none — so there is nothing for the button to dial. Connecting a WhatsApp "
        "Business number needs the WhatsApp app and a verification code, which is why it "
        "cannot be done through the API."
    ),
    steps=(
        "Open Meta Business Suite → Settings → WhatsApp accounts for this Page.",
        "Connect your WhatsApp Business number and complete the verification.",
        "Reconnect Meta in Punk, then publish. Or pick a different Page in the plan editor.",
    ),
    url=f"{_BUSINESS}/settings/whatsapp-business-accounts",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish",),
    phrases=("not linked to a whatsapp", "whatsapp account", "whatsapp number"),
))

_entry(Remediation(
    key="page_messaging_off",
    title="This Page has messaging switched off",
    cause=(
        "The ad sends people into a Messenger conversation, but the Page is not accepting "
        "messages. Meta refuses the ad rather than sending people into a dead end."
    ),
    steps=(
        "Open Page settings → Privacy → Messages and allow people to message the Page.",
        "Publish again.",
    ),
    url=f"{_BUSINESS}/settings/pages",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish",),
    phrases=("messaging is not enabled", "cannot receive messages"),
))

_entry(Remediation(
    key="page_unpublished",
    title="This Page isn't published",
    cause=(
        "The Page is in draft or unpublished, so nobody outside its admins can see it — "
        "and Meta will not run ads pointing at a Page the public cannot reach."
    ),
    steps=(
        "Open Page settings → Page visibility and publish the Page.",
        "Publish the campaign again.",
    ),
    url=f"{_BUSINESS}/settings/pages",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish",),
    phrases=("page is not published", "unpublished page"),
))


# ── conversion tracking / CAPI ───────────────────────────────────────────────

_entry(Remediation(
    key="tracking_no_dataset",
    title="No conversion dataset yet",
    cause=(
        "Conversions are reported into a dataset (a Pixel) that belongs to you. There "
        "isn't one resolved for this account, so there is nowhere to send them."
    ),
    steps=(
        "Publish a campaign with a conversion objective — Punk sets the dataset up as part "
        "of that.",
        "Or pick an existing dataset in the campaign plan editor if you already have one.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/datasets",
    effect="Conversions sent to Punk are accepted and dropped until a dataset exists.",
    severity="blocks",
    scopes=("tracking",),
))

_entry(Remediation(
    key="tracking_token_expired",
    title="The Meta token behind your conversion feed has expired",
    cause=(
        "A login token lasts about 60 days; a conversion feed runs for years. What it "
        "wants is a system user token, which you generate once in your own Business "
        "settings — Meta only issues those to a human clicking the button."
    ),
    steps=(
        "Business settings → Users → System users → Add, and create one with the Admin role.",
        "Generate a token for it with the ads_management and business_management permissions, "
        "and assign it your dataset and ad account.",
        "Paste that token into Punk's conversion tracking settings — it does not expire.",
    ),
    url=f"{_BUSINESS}/settings/system-users",
    effect="Conversions are not reaching Meta until this is fixed.",
    severity="blocks",
    scopes=("tracking",),
    codes=(190,),
    phrases=("access token", "session has expired", "token is invalid"),
))

_entry(Remediation(
    key="pixel_never_fired",
    title="Your Pixel has never fired",
    cause=(
        "The dataset exists but Meta has never received an event from it, which means the "
        "code is not on your site yet. A campaign optimizing for conversions learns from "
        "those events — with none arriving, it optimizes toward something it never sees."
    ),
    steps=(
        "Copy the pixel snippet from Punk's conversion tracking settings.",
        "Paste it into every page of your site just before </head> — or add it as a Custom "
        "HTML tag on All Pages in Google Tag Manager.",
        "Load your site once, then check Events Manager shows activity.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/dataset/{{dataset_id}}/overview",
    effect="The campaign can still run — it just cannot optimize for conversions yet.",
    severity="warns",
    scopes=("tracking", "publish"),
))

# Raised at connect, off what the account contains — never matched off an exception,
# and not shown on the publish gate (the plan editor's pixel picker owns that).
_entry(Remediation(
    key="no_pixel",
    title="No Pixel on this ad account",
    cause=(
        "Sales and website-lead goals learn from events a Pixel reports, and Punk found "
        "none on this ad account. Meta only lets you set one up on its own screen, and it "
        "then has to be installed on your site."
    ),
    steps=(
        "Open Events Manager and create a Pixel (dataset) for this ad account.",
        "Install its snippet on your site, then reconnect or pick it in the plan editor.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/datasets",
    effect="Punk will steer you toward goals that do not need one, like traffic or messages.",
    severity="warns",
    scopes=("tracking", "publish"),
))

_entry(Remediation(
    key="pixel_owner_mismatch",
    title="This dataset belongs to a different Meta business",
    cause=(
        "Your ad account can see this Pixel because it was shared with it, but a business "
        "that isn't yours owns it — so events it fires may be for another company's site, "
        "and that business can revoke access at any time."
    ),
    steps=(
        "Business settings → Data sources → Datasets, and confirm which business owns it.",
        "If it isn't yours, pick a different dataset in the plan editor — or create one in "
        "your own business.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/dataset/{{dataset_id}}/overview",
    effect="The campaign can still run — the pixel just may not be measuring your site.",
    severity="warns",
    scopes=("tracking", "publish"),
))

_entry(Remediation(
    key="lead_form_wrong_page",
    title="This instant form belongs to a different Page",
    cause=(
        "The form was created under a Page other than the one this campaign promotes. Meta "
        "cannot attach a lead form to an ad set unless the form and the promoted Page match."
    ),
    steps=(
        "Pick a form that belongs to the Page this campaign promotes — or leave it blank "
        "and Punk builds a default one on that Page.",
    ),
    effect="Publish creates a default instant form on the correct Page instead.",
    severity="warns",
    scopes=("tracking", "publish"),
))

_entry(Remediation(
    key="tracking_event_missing",
    title="Your dataset isn't receiving the event you're optimizing for",
    cause=(
        "Events are arriving, but not {event_name} — the one this campaign's delivery learns "
        "from. A base pixel installed site-wide fires PageView on every page and nothing else, "
        "so the dataset looks alive while the conversion Meta is optimizing toward has never "
        "been coded on your conversion page."
    ),
    steps=(
        "Open Punk's conversion tracking settings and pick {event_name} in the event list.",
        "Paste the event call it gives you onto the page that confirms the conversion — the "
        "order-received or thank-you page, not every page.",
        "Complete one conversion yourself, then check Events Manager lists {event_name}.",
        "Sending conversions from your server too? Use the same event name there.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/dataset/{{dataset_id}}/overview",
    effect="The campaign runs, but delivery is optimizing against an event it never sees.",
    severity="warns",
    scopes=("tracking", "publish"),
    # No subcodes/phrases/codes: nothing Meta rejects raises this. It comes from
    # the tracking diagnostic comparing the account's event against the dataset's
    # own stats, so ``resolve`` must never match it off an exception.
))

_entry(Remediation(
    key="lead_webhook_not_subscribed",
    title="Punk can't see your instant-form leads yet",
    cause=(
        "Meta would not let Punk subscribe to this Page's leads. The campaign runs and Meta "
        "still counts every lead, so delivery optimizes normally — but the leads themselves "
        "stay inside Meta, and Punk cannot report which of them turned into customers."
    ),
    steps=(
        "Open Business Settings and check Punk has the Page's leads_retrieval permission.",
        "Reconnect Meta in Punk with that permission granted.",
        "Until then, download leads from the Page's Lead Center — Publishing Tools → Forms "
        "Library.",
    ),
    url=f"{_BUSINESS}/settings/pages/{{page_id}}",
    effect="Leads are collected and counted by Meta; only the feedback loop into Punk is missing.",
    severity="warns",
    scopes=("tracking", "publish"),
    # Nothing Meta rejects raises this — subscribe_page_leadgen returns False
    # rather than throwing, so ``resolve`` must never match it off an exception.
))

_entry(Remediation(
    key="lead_dataset_missing",
    title="Your instant-form leads aren't teaching delivery anything",
    cause=(
        "Meta is pushing this Page's leads to Punk, but the ad account has no dataset to "
        "report them back into — so Punk reads each lead and has nowhere to send it. Meta "
        "still counts every lead and the campaign delivers normally; what is missing is the "
        "loop that tells delivery which leads were worth having."
    ),
    steps=(
        "Events Manager → Connect data sources → Web, and create a dataset. It costs "
        "nothing and needs no website — it is a container for the lead events.",
        "Come back to Punk's conversion tracking settings and pick it from the dataset list.",
        "Already have one on another ad account? Business settings → Data sources → "
        "Datasets, and assign it to this ad account first, or Punk cannot write to it.",
    ),
    url=f"{_BUSINESS}/events_manager2/list/",
    effect="Leads are collected and counted by Meta; only the quality feedback loop is off.",
    severity="warns",
    scopes=("tracking", "publish"),
    # No subcodes/phrases/codes: nothing Meta rejects raises this. It comes from the
    # tracking diagnostic noticing a subscribed Page with no dataset behind it, so
    # ``resolve`` must never match it off an exception.
))

_entry(Remediation(
    key="domain_not_verified",
    title="Your website domain isn't verified with Meta",
    cause=(
        "Meta needs the domain verified before it will attribute web conversions to your "
        "ads, and verification means proving you control the domain — a DNS record, an "
        "HTML file, or a meta tag. Only someone with access to the domain can do it."
    ),
    steps=(
        "Business settings → Brand safety → Domains, and add your domain.",
        "Verify it with the DNS TXT record, the HTML file upload, or the meta tag — "
        "whichever you can do on your host.",
        "Then configure your web events (see below) so conversions are attributed.",
    ),
    url=f"{_BUSINESS}/settings/owned-domains?business_id={{business_id}}",
    effect="The campaign still runs; conversion reporting will be incomplete.",
    severity="warns",
    scopes=("tracking", "publish"),
    # Never a bare "domain": it appears in link-format and policy rejections that
    # have nothing to do with verification, and this entry would swallow them.
    phrases=("domain verification", "domain is not verified", "verify your domain"),
))

_entry(Remediation(
    key="aem_not_configured",
    title="Web events aren't configured for this domain",
    cause=(
        "Since iOS 14, Meta only optimizes for up to eight web events per domain, and "
        "someone has to choose and rank them in Events Manager. Until that is done, "
        "conversions from a large share of visitors are not attributed at all."
    ),
    steps=(
        "Events Manager → Aggregated Event Measurement → Configure Web Events.",
        "Pick your verified domain and add the event this campaign optimizes for, ranked "
        "highest.",
        "Changes take about 72 hours to take effect for existing campaigns.",
    ),
    url=f"{_BUSINESS}/events_manager2/aggregated_event_measurement",
    effect="The campaign still runs; conversion reporting will be incomplete.",
    severity="warns",
    scopes=("tracking", "publish"),
    phrases=("aggregated event measurement", "event is not configured"),
))

_entry(Remediation(
    key="meta_scopes_outdated",
    title="Your Meta connection is missing a permission",
    cause=(
        "Punk asks for a few more Meta permissions than it did when you connected, and a "
        "token only ever carries the ones granted at the time it was made. Missing: "
        "{missing}. Everything you have set up keeps working — the features behind those "
        "permissions are the ones that cannot."
    ),
    steps=(
        "Open Punk's Meta connection settings and reconnect.",
        "Leave every permission checked on Meta's consent screen — unchecking one puts you "
        "back here.",
    ),
    url="",
    effect="Your campaigns and tracking are unaffected; some checks cannot run.",
    severity="warns",
    scopes=("tracking", "publish"),
    # No codes/subcodes/phrases: this is raised by comparing the stored scopes
    # against REQUIRED_SCOPES, never off a Meta rejection, so ``resolve`` must
    # not match it from an exception.
))

_entry(Remediation(
    key="dataset_not_assigned_to_account",
    title="Your dataset isn't assigned to this ad account",
    cause=(
        "The dataset lives in your business portfolio but the ad account running the ads "
        "has not been given access to it, so Meta will not let an ad set optimize against "
        "it. Assigning assets between a business and an account is a Business settings "
        "action."
    ),
    steps=(
        "Business settings → Data sources → Datasets, and pick this dataset.",
        "Under Connected assets, add the ad account you're advertising from.",
        "Publish again.",
    ),
    url=f"{_BUSINESS}/settings/datasets",
    effect="Nothing was created in your ad account and nothing is spending.",
    severity="blocks",
    scopes=("publish", "tracking"),
    phrases=("pixel is not", "dataset is not", "not shared with"),
))

_entry(Remediation(
    key="meta_rate_limited",
    title="Meta is throttling this ad account right now",
    cause=(
        "Meta's ads API rate limit is measured in minutes, not seconds — this account (or "
        "this app) made enough calls recently that Meta is refusing more until the window "
        "clears. Punk already retried this step several times with increasing delays "
        "before giving up; retrying instantly again would hit the same limit."
    ),
    steps=(
        "Wait a few minutes — Meta's ads throttle windows are typically short.",
        "Publish again. Nothing about your plan needs to change.",
        "If this keeps happening on the same account, heavy activity elsewhere on it "
        "(another tool, another campaign publishing at the same time) is worth checking.",
    ),
    url="",
    effect="This step did not complete; nothing past it was created or changed.",
    severity="blocks",
    scopes=("publish", "audience", "tracking", "manage"),
    codes=(4, 17, 32, 613, 80004),
    phrases=(
        "request limit reached", "too many calls", "user request limit",
        "application request limit", "please retry your request later",
    ),
))


# ── resolution ───────────────────────────────────────────────────────────────


def _haystack(exc: Any) -> str:
    """Everything about a rejection worth searching, lowercased."""
    return " ".join(
        str(part) for part in (getattr(exc, "user_msg", "") or "", str(exc)) if part
    ).lower()


def _log_shown(rem: Remediation, source: str, **extra: Any) -> None:
    """One greppable line per card put in front of a user.

    Counting these is how the team learns which prerequisite new advertisers actually
    stall on. Logged where a card is *decided* (an error resolved, a beat written) —
    not in ``render``, which re-runs on every redraw of a gate and would count one
    card many times.
    """
    logger.info(
        "remediation_shown key=%s severity=%s source=%s %s",
        rem.key, rem.severity, source,
        " ".join(f"{k}={v}" for k, v in extra.items() if v not in (None, "")),
    )


_FBTRACE = re.compile(r"fbtrace=(\S+)")


def resolve(exc: Any, *, step: str = "", scope: str = "") -> Remediation | None:
    """``_match``, plus a ``remediation_shown`` line carrying Meta's trace id.

    The trace id is what support quotes to Meta about a specific refusal.
    """
    found = _match(exc, step=step, scope=scope)
    if found:
        trace = _FBTRACE.search(str(exc))
        _log_shown(
            found, "error", step=step, scope=scope,
            code=getattr(exc, "code", None), subcode=getattr(exc, "subcode", None),
            fbtrace=trace.group(1) if trace else "",
        )
    return found


def _match(exc: Any, *, step: str = "", scope: str = "") -> Remediation | None:
    """The catalog entry for a Meta rejection, or None when we have nothing to add.

    Match order is precision order: **subcode → message substring → code**. A
    ``code`` alone (100, 200, 190) covers thousands of unrelated failures, so it
    only matches inside a ``scope`` that narrows it to one meaning.

    ``None`` is a perfectly good answer and the common one — callers keep their
    existing generic wording for it. It is also logged, because every miss is a
    catalog entry waiting to be written from a real payload rather than guessed.
    """
    code = getattr(exc, "code", None)
    subcode = getattr(exc, "subcode", None)
    scope = scope or _SCOPE_BY_STEP.get(step, "")

    def in_scope(rem: Remediation) -> bool:
        return not scope or not rem.scopes or scope in rem.scopes

    if subcode is not None:
        for rem in CATALOG.values():
            if subcode in rem.subcodes:
                return rem

    text = _haystack(exc)
    if text:
        for rem in CATALOG.values():
            if in_scope(rem) and any(p in text for p in rem.phrases):
                return rem

    if code is not None and scope:
        for rem in CATALOG.values():
            if code in rem.codes and in_scope(rem):
                return rem

    logger.warning(
        "remediation: no entry for code=%s subcode=%s step=%s scope=%s msg=%s",
        code, subcode, step or "-", scope or "-", str(exc)[:300],
    )
    return None


# Which family a publish step belongs to, so ``resolve`` can narrow a code-only
# match. Steps come from MetaPublishError.step in the publish executor.
_SCOPE_BY_STEP: dict[str, str] = {
    "custom_audience": "audience",
    "lookalike_audience": "audience",
    "audience_export": "audience",
    "preflight": "publish",
    "campaign": "publish",
    "adset": "publish",
    "ad": "publish",
    "creative": "publish",
    "media": "publish",
    "lead_form": "publish",
    "activate": "publish",
    "tracking": "tracking",
}


def render(rem: Remediation, *, unverified: bool = False, **ids: Any) -> dict[str, Any]:
    """The wire shape the chat beat, the gates and the fix-it card all read.

    ``unverified`` marks a card for something Punk has no way to read — the user is
    asked to confirm it themselves rather than told it is missing. The key is only
    present when true, so every existing card keeps its exact shape.

    A URL whose template needs an id we do not have comes back empty rather than
    half-substituted: a link reading ``…?business_id={business_id}`` is worse than
    no link, because the user clicks it and lands nowhere.
    """
    url = rem.url
    if url:
        # Meta's own consoles take the BARE account number in ?act= — Ads Manager
        # and the Custom Audience TOS page both do. Callers hand us the ``act_``
        # form because that is what the Graph API wants, so every card carrying
        # {ad_account_id} in its link was rendering ?act=act_123 and landing the
        # user on an error page at the exact moment they were trying to fix
        # something.
        ids = dict(ids)
        account = str(ids.get("ad_account_id") or "")
        if account.startswith("act_"):
            ids["ad_account_id"] = account[4:]
        try:
            url = url.format(**{k: v for k, v in ids.items() if v})
        except (KeyError, IndexError):
            url = ""
    card = {
        "key": rem.key,
        "title": rem.title,
        "cause": rem.cause,
        "steps": list(rem.steps),
        "url": url,
        "effect": rem.effect,
        "severity": rem.severity,
        "scope": rem.scopes[0] if rem.scopes else "",
    }
    if unverified:
        card["unverified"] = True
    return card


def beat_facts(rem: Remediation, *, unverified: bool = False, **ids: Any) -> dict[str, Any]:
    """The same entry as narrator grounding, in the shape ``failure`` beats use.

    Mirrors the facts the connect-time audience beat already passes, so the
    composer keeps writing one message instead of two minds writing two.
    ``unverified`` is for what Punk cannot read off the account: the beat asks the
    user to confirm it instead of claiming it is missing.
    """
    rendered = render(rem, **ids)
    _log_shown(rem, "beat")
    if unverified:
        return {
            "constraint": f"Confirm this is done: {rem.title.replace(' have not been', ' are')}",
            "cause": rem.cause + " Punk cannot check this from its side.",
            "effect": rem.effect,
            "fix": "If you have already accepted them, ignore this.",
            "steps": rendered["steps"],
            "url": rendered["url"],
            "user_must_do_it": True,
        }
    return {
        "constraint": rem.title,
        "cause": rem.cause,
        "effect": rem.effect,
        "fix": rem.steps[0] if rem.steps else "",
        "steps": rendered["steps"],
        "url": rendered["url"],
        "user_must_do_it": True,
    }


# ── the silent family: what the plan buys vs what the Page has ───────────────


def _plan_platforms(marketing_plan: dict) -> tuple[set[str], bool]:
    """``(platforms named across the plan, any ad set on automatic placements)``.

    An empty ``publisher_platforms`` is not "no platforms" — it is Advantage+
    placements, which includes Instagram. Treating it as absence is how a plan
    that definitely runs on Instagram looks like one that doesn't.
    """
    named: set[str] = set()
    automatic = False
    for adset in marketing_plan.get("adsets") or []:
        platforms = (adset.get("targeting") or {}).get("publisher_platforms") or []
        if platforms:
            named.update(str(p) for p in platforms)
        else:
            automatic = True
    return named, automatic


def _plan_destinations(marketing_plan: dict) -> set[str]:
    return {
        str(adset.get("destination_type") or "").upper()
        for adset in marketing_plan.get("adsets") or []
        if adset.get("destination_type")
    }


# Destinations that open an Instagram thread — these need a real linked account,
# not the Page-backed identity a feed ad can fall back to.
_IG_DESTINATIONS: frozenset[str] = frozenset({
    "INSTAGRAM_DIRECT",
    "MESSAGING_INSTAGRAM_DIRECT_MESSENGER",
    "MESSAGING_INSTAGRAM_DIRECT_WHATSAPP",
    "MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP",
})

_WHATSAPP_DESTINATIONS: frozenset[str] = frozenset({
    "WHATSAPP",
    "MESSAGING_MESSENGER_WHATSAPP",
    "MESSAGING_INSTAGRAM_DIRECT_WHATSAPP",
    "MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP",
})


def check_plan_assets(
    marketing_plan: dict,
    *,
    page: dict | None = None,
    instagram_user_id: str = "",
) -> list[Remediation]:
    """Prerequisites the plan needs from the Page, that the Page does not have.

    The one detection layer with no Meta error behind it. An ad set bought on
    Instagram placements with no Instagram account linked publishes cleanly, runs
    under a placeholder identity, and nobody finds out until they look at the ad.

    ``page`` is one entry from ``meta_ads.list_meta_pages``, which encodes three
    states deliberately: ``whatsapp`` present-and-a-dict (linked), present-and-None
    (provably not linked), **absent** (the token could not read the field). Only a
    provable "not linked" is reported — guessing from an unreadable field would
    block a Click-to-WhatsApp campaign that publishes perfectly well, which is why
    ``list_meta_pages`` omits the key rather than writing None.
    """
    page = page or {}
    found: list[Remediation] = []

    platforms, automatic = _plan_platforms(marketing_plan)
    destinations = _plan_destinations(marketing_plan)

    wants_instagram = (
        "instagram" in platforms or automatic or bool(destinations & _IG_DESTINATIONS)
    )
    if wants_instagram and not (instagram_user_id or (page.get("instagram") or {}).get("id")):
        found.append(CATALOG["instagram_not_linked"])

    # Present-and-None means Meta answered "no number". A missing key means the
    # token could not read the field at all, and that is not evidence of anything.
    if destinations & _WHATSAPP_DESTINATIONS and "whatsapp" in page and not page["whatsapp"]:
        found.append(CATALOG["page_whatsapp_missing"])

    return found


def prose(rem: Remediation) -> str:
    """One paragraph a chat prompt can carry: what is wrong, then what to do.

    For the places that can only show a sentence — an interrupt's prompt — rather than
    a fix-it card. No deep link: a prompt has nowhere to put one, and the card that
    follows it carries the link.
    """
    steps = " ".join(f"{i}) {step}" for i, step in enumerate(rem.steps, 1))
    return f"{rem.title}. {rem.cause} {steps}"


def render_all(rems: Iterable[Remediation], **ids: Any) -> list[dict[str, Any]]:
    """``render`` over a list, deduped by key and keeping catalog order."""
    seen: dict[str, dict[str, Any]] = {}
    for rem in rems:
        if rem.key not in seen:
            seen[rem.key] = render(rem, **ids)
    return list(seen.values())



# The order money flows in: get into the account, be able to pay, consent to the
# data terms, then measure. A new advertiser works down the list, so what stops
# everything after it comes first.
_READINESS_ORDER = {
    "no_ad_account": 0,
    "no_facebook_page": 0,
    "meta_scopes_outdated": 0,
    "app_access_level": 0,
    "audience_needs_business": 0,
    "ad_account_role_missing": 0,
    "page_role_missing": 0,
    "page_unpublished": 0,
    "ad_account_disabled": 0,
    "ad_account_no_payment": 1,
    "ad_account_spend_limit": 1,
    "custom_audience_tos": 2,
}
_SEVERITY_ORDER = {"blocks": 0, "degrades": 1, "warns": 2}


def readiness(
    found: Iterable[Remediation], *, tos_accepted: bool | None = None, **ids: Any
) -> list[dict[str, Any]]:
    """Everything a NEW advertiser still has to do in Meta, in the order to do it.

    ``found`` is what Punk could actually read off the account (``ad_account_
    blockers``). ``tos_accepted`` is ``meta_ads.fetch_custom_audience_tos``: whether
    the Custom Audience Terms were accepted. For Punk — whose product is the
    audience — that is nearly every first publish, and staying silent about it is
    what sends a new user through the same failure once per prerequisite.

      * ``True``  — accepted: no card. Nothing to do, so nothing to say.
      * ``False`` — provably not: a plain card.
      * ``None``  — Meta would not say: listed, marked ``unverified``, and the user
        is asked to confirm it rather than told it is missing.
    """
    cards = render_all(found, **ids)
    if not any(c["key"] == "custom_audience_tos" for c in cards) and tos_accepted is not True:
        cards.append(render(
            CATALOG["custom_audience_tos"], unverified=tos_accepted is None, **ids,
        ))
    return sorted(
        cards,
        key=lambda c: (
            _READINESS_ORDER.get(c["key"], 3),
            _SEVERITY_ORDER.get(c.get("severity"), 3),
        ),
    )


def _review_reasons(feedback: Any) -> list[str]:
    """Every human-readable string inside an ad's ``ad_review_feedback``.

    Meta nests them (``global`` and ``placement_specific``, each mapping a reason code
    to prose or to a further mapping), and the shape has not been read off a live
    payload yet — so this takes any string it finds rather than trusting a layout.
    """
    if isinstance(feedback, str):
        return [feedback] if feedback.strip() else []
    if isinstance(feedback, dict):
        return [r for v in feedback.values() for r in _review_reasons(v)]
    if isinstance(feedback, list):
        return [r for v in feedback for r in _review_reasons(v)]
    return []


_IN_REVIEW_STATUSES = frozenset({"PENDING_REVIEW", "IN_PROCESS"})


def review_cards(ads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """What Meta's review has done to a campaign's ads, as fix-it cards.

    A disapproval wins over "still in review": the user cannot act on the second but
    can on the first. Empty when nothing needs saying — an approved or paused ad has
    no card. Punk only reports; it never edits or resubmits an ad.
    """
    ads = list(ads)
    rejected = [a for a in ads if a.get("effective_status") == "DISAPPROVED"]
    if rejected:
        card = render(CATALOG["ads_disapproved"])
        lines = []
        for ad in rejected:
            reasons = list(dict.fromkeys(_review_reasons(ad.get("ad_review_feedback"))))[:3]
            name = ad.get("name") or ad.get("id") or "An ad"
            lines.append(f"{name}: {'; '.join(reasons) if reasons else 'no reason given'}")
        card["cause"] += " " + " | ".join(lines)
        return [card]
    if any(a.get("effective_status") in _IN_REVIEW_STATUSES for a in ads):
        return [render(CATALOG["ads_in_review"])]
    return []
