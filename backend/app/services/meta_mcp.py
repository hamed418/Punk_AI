"""
services/meta_mcp.py
────────────────────
Load Meta Ads MCP tools (pipeboard meta-ads-mcp) for Punk chat users.

Spawns the published MCP server as a stdio subprocess per campaign-manager
session, injecting the user's Meta OAuth token from Punk's DB — no separate
Pipeboard account or local OAuth callback required.

See: https://github.com/pipeboard-co/meta-ads-mcp
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from langchain_core.tools import BaseTool, StructuredTool
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import BaseModel, Field, create_model

from app.core.config import settings
from app.graph.campaign_manager_tools import (
    LEGACY_TOOLS,
    LEGACY_TOOL_REGISTRY,
    LEGACY_WRITE_TOOLS,
    PLANNING_TOOLS,
    list_user_campaigns,
)
from app.graph.tools import retrieve_marketing_knowledge

logger = logging.getLogger(__name__)

# Tools that must never be exposed to Punk users (auth is handled in-app).
_MCP_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "get_login_link",
})

# Read-only MCP tools that do not mutate Meta state.
_MCP_READ_EXACT: frozenset[str] = frozenset({
    "fetch",
    "generate_report",
    "get_insights",
    "compute_image_crops",
})

_MCP_READ_PREFIXES: tuple[str, ...] = (
    "get_",
    "search_",
    "estimate_",
)

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def is_mcp_write_tool(name: str) -> bool:
    """Return True when an MCP tool mutates Meta Ads state."""
    if name in _MCP_EXCLUDED_TOOLS:
        return False
    if name in _MCP_READ_EXACT or name.startswith(_MCP_READ_PREFIXES):
        return False
    return True


# Only these host env vars reach the third-party subprocess — everything else
# (POSTGRES_*, STRIPE_*, SECRET_KEY, AWS_*) stays out of its process image.
_ENV_PASSTHROUGH: tuple[str, ...] = (
    "PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONUNBUFFERED",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)


def _mcp_stdio_env(access_token: str) -> dict[str, str]:
    """Build subprocess env for meta-ads-mcp with Punk credentials."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({
        "META_ACCESS_TOKEN": access_token,
        "META_APP_ID": settings.META_APP_ID,
        "META_APP_SECRET": settings.META_APP_SECRET,
        "META_ADS_DISABLE_CALLBACK_SERVER": "1",
        "META_ADS_DISABLE_LOGIN_LINK": "1",
    })
    return env


def _args_schema_from_json(name: str, schema: dict[str, Any] | None) -> type[BaseModel]:
    """Best-effort JSON Schema → Pydantic model for LLM tool binding."""
    if not schema or schema.get("type") != "object":
        return create_model(f"{name}_args")

    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}

    for key, spec in props.items():
        if key == "access_token":
            # Token comes from Punk OAuth env — hide from LLM schema noise.
            continue
        json_type = spec.get("type", "string")
        if isinstance(json_type, list):
            json_type = next((t for t in json_type if t != "null"), "string")
        py_type = _JSON_TYPE_MAP.get(json_type, Any)
        if key in required:
            fields[key] = (py_type, Field(description=spec.get("description", "")))
        else:
            fields[key] = (
                py_type | None,
                Field(default=None, description=spec.get("description", "")),
            )

    return create_model(f"{name}_args", **fields)


def _tool_result_to_str(result: Any) -> str:
    content = getattr(result, "content", None) or []
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(block))
    if parts:
        return "\n".join(parts)
    if getattr(result, "isError", False):
        return "MCP tool returned an error with no message."
    return json.dumps(getattr(result, "model_dump", lambda: str(result))(), default=str)


def _wrap_mcp_tool(session: ClientSession, mcp_tool: Any) -> StructuredTool:
    name = mcp_tool.name
    description = mcp_tool.description or name
    input_schema = getattr(mcp_tool, "inputSchema", None)
    args_schema = _args_schema_from_json(name, input_schema)

    async def _invoke(**kwargs: Any) -> str:
        kwargs.pop("access_token", None)
        cleaned = {k: v for k, v in kwargs.items() if v is not None}
        result = await session.call_tool(name, cleaned)
        return _tool_result_to_str(result)

    return StructuredTool(
        name=name,
        description=description,
        coroutine=_invoke,
        args_schema=args_schema,
    )


@dataclass(frozen=True)
class CampaignManagerToolSet:
    """Tools + registries for one campaign-manager ReAct session."""

    tools: list[Any]
    registry: dict[str, Any]
    write_tools: frozenset[str]
    uses_mcp: bool


@asynccontextmanager
async def _mcp_tool_set(
    access_token: str,
    ad_account_id: str,
    *,
    planning_enabled: bool,
) -> AsyncIterator[CampaignManagerToolSet]:
    """Spawn meta-ads-mcp over stdio and yield its tools.

    Raises if the handshake fails or times out — the caller decides on
    fallback. The timeout covers only connect/initialize/list_tools; it opens
    and closes inside the stream contexts so anyio cancel scopes stay LIFO.
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "meta_ads_mcp"],
        env=_mcp_stdio_env(access_token),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            async with asyncio.timeout(settings.META_MCP_CONNECT_TIMEOUT_S):
                await session.initialize()
                listed = await session.list_tools()

            mcp_tools = [
                _wrap_mcp_tool(session, t)
                for t in listed.tools
                if t.name not in _MCP_EXCLUDED_TOOLS
            ]
            if not mcp_tools:
                raise RuntimeError("meta-ads-mcp returned no tools")

            write_tools = frozenset(
                t.name for t in mcp_tools if is_mcp_write_tool(t.name)
            )
            registry = {t.name: t for t in mcp_tools}

            punk_tools: list[Any] = [list_user_campaigns, retrieve_marketing_knowledge]
            if planning_enabled:
                punk_tools.extend(PLANNING_TOOLS)
            for t in punk_tools:
                registry[t.name] = t

            logger.info(
                "meta_mcp: loaded %d MCP tools (%d write) for account %s",
                len(mcp_tools),
                len(write_tools),
                ad_account_id or "(none)",
            )
            yield CampaignManagerToolSet(
                tools=punk_tools + mcp_tools,
                registry=registry,
                write_tools=write_tools,
                uses_mcp=True,
            )


@asynccontextmanager
async def campaign_manager_tool_context(
    access_token: str,
    ad_account_id: str,
    *,
    planning_enabled: bool,
) -> AsyncIterator[CampaignManagerToolSet]:
    """
    Yield the tool set for a campaign-manager session.

    When META_MCP_ENABLED is true, loads tools from meta-ads-mcp over stdio
    and keeps the MCP session alive for the duration of the context block.
    Falls back to legacy Punk tools when the MCP handshake fails. Errors
    raised by the caller's body propagate untouched — only setup failures
    trigger the fallback.
    """
    if not settings.META_MCP_ENABLED:
        yield _legacy_tool_set(planning_enabled)
        return

    connected = False
    try:
        async with _mcp_tool_set(
            access_token, ad_account_id, planning_enabled=planning_enabled,
        ) as tool_set:
            connected = True
            yield tool_set
            return
    except Exception as exc:
        if connected:
            raise
        logger.warning(
            "meta_mcp: failed to load MCP tools, using legacy tools — %s",
            exc,
            exc_info=settings.DEBUG,
        )

    yield _legacy_tool_set(planning_enabled)


def _legacy_tool_set(planning_enabled: bool) -> CampaignManagerToolSet:
    tools: list[Any] = list(LEGACY_TOOLS)
    if planning_enabled:
        tools = tools + list(PLANNING_TOOLS)
    return CampaignManagerToolSet(
        tools=tools,
        registry=dict(LEGACY_TOOL_REGISTRY),
        write_tools=LEGACY_WRITE_TOOLS,
        uses_mcp=False,
    )
