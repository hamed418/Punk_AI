"""app/services/meta_ads.py::granted_ad_account_ids — connect stores only
what Meta actually granted.

``/me/adaccounts`` lists every account a Business system-user token can
reach — for a token minted under Facebook Login for Business, that is every
account assigned to the system user, not just the ones picked in the login
dialog. ``granular_scopes`` is Meta's own authoritative record of the grant;
this is the filter that keeps the connect flow honest.
"""
from app.services.meta_ads import granted_ad_account_ids


def test_filters_to_granted_ids_only():
    scopes = [{"scope": "ads_management", "target_ids": ["116187595198313"]}]

    assert granted_ad_account_ids(scopes) == {"116187595198313"}


def test_matches_across_the_act_prefix_boundary():
    # me/adaccounts ids come back act_-prefixed; granular_scopes target_ids
    # come back bare numeric. Both must resolve to the same identity.
    scopes = [{"scope": "ads_read", "target_ids": ["act_116187595198313"]}]

    assert granted_ad_account_ids(scopes) == {"116187595198313"}


def test_merges_across_scope_entries():
    scopes = [
        {"scope": "ads_management", "target_ids": ["1"]},
        {"scope": "ads_read", "target_ids": ["2"]},
        {"scope": "pages_show_list", "target_ids": ["999"]},  # unrelated scope, ignored
    ]

    assert granted_ad_account_ids(scopes) == {"1", "2"}


def test_returns_none_when_no_ads_scope_entry_exists():
    # Legacy `user` tokens, or a debug_token read that didn't carry this
    # permission's entry at all — unknown, must not read as "grant nothing".
    scopes = [{"scope": "pages_show_list", "target_ids": ["1"]}]

    assert granted_ad_account_ids(scopes) is None


def test_returns_none_when_target_ids_is_absent():
    # Meta omits target_ids when the permission covers every asset.
    scopes = [{"scope": "ads_management"}]

    assert granted_ad_account_ids(scopes) is None


def test_returns_none_on_empty_granular_scopes():
    # fetch_token_info's own failure value — must read as "unknown".
    assert granted_ad_account_ids([]) is None
    assert granted_ad_account_ids(None) is None
