"""
tests/test_campaign_manager_wiring.py
─────────────────────────────────────
Guards the campaign-manager node's call into the tool context.

At HEAD 11c6f636 both call sites passed THREE positional args to
``campaign_manager_tool_context(access_token, ad_account_id, *, planning_enabled)``.
``@asynccontextmanager`` builds the generator eagerly in ``__init__``, so the
``TypeError`` fired before the ``async with`` body — every single campaign_manager
turn died. It surfaced as a bare ``{"type": "error"}`` SSE frame, which the
client has no branch for, so the user saw the stream simply stop.

Nothing caught it because the third argument was redundant, not missing:
``_cm_user_id`` is a ContextVar already set by the node itself.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.services.meta_mcp import campaign_manager_tool_context

_NODE = Path(__file__).resolve().parents[1] / "app" / "graph" / "campaign_manager_node.py"


def _call_shapes(source: str, func_name: str) -> list[tuple[int, list[str]]]:
    """(positional count, keyword names) for every call to ``func_name``."""
    tree = ast.parse(source)
    out: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == func_name:
            out.append((len(node.args), [k.arg for k in node.keywords if k.arg]))
    return out


def test_every_tool_context_call_binds_to_its_signature():
    shapes = _call_shapes(_NODE.read_text(encoding="utf-8"), "campaign_manager_tool_context")
    assert shapes, "expected campaign_manager_node to call campaign_manager_tool_context"

    # asynccontextmanager wraps the generator; __wrapped__ is the real function.
    target = getattr(campaign_manager_tool_context, "__wrapped__", campaign_manager_tool_context)
    sig = inspect.signature(target)

    for positional, keywords in shapes:
        sig.bind(*(["x"] * positional), **{k: True for k in keywords})


def test_user_id_reaches_the_tools_by_contextvar_not_by_argument():
    """Why the stray argument was wrong rather than the signature being short:
    list_user_campaigns reads user_id off a ContextVar the node sets directly."""
    source = _NODE.read_text(encoding="utf-8")
    assert "_cm_user_id.set(" in source

    target = getattr(campaign_manager_tool_context, "__wrapped__", campaign_manager_tool_context)
    assert "user_id" not in inspect.signature(target).parameters
