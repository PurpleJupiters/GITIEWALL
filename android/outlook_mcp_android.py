#!/usr/bin/env python3
"""MCP server — Outlook email via Microsoft Graph API.
Android/Termux version. Run outlook_setup_android.py once before using this.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import msal
import requests
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

CONFIG_PATH = Path.home() / ".outlook_mcp" / "config.json"
CACHE_PATH  = Path.home() / ".outlook_mcp" / "token_cache.json"
SCOPES      = ["https://graph.microsoft.com/Mail.Read"]
GRAPH_BASE  = "https://graph.microsoft.com/v1.0/me"

FOLDER_PATHS = {
    "inbox":   "mailFolders/inbox/messages",
    "sent":    "mailFolders/sentItems/messages",
    "drafts":  "mailFolders/drafts/messages",
    "deleted": "mailFolders/deletedItems/messages",
}

server = Server("outlook-email")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    if not CONFIG_PATH.exists() or not CACHE_PATH.exists():
        raise RuntimeError(
            "Not set up. Run outlook_setup_android.py in Termux first."
        )

    config    = json.loads(CONFIG_PATH.read_text())
    client_id = config["client_id"]
    tenant_id = config.get("tenant_id", "common")

    cache = msal.SerializableTokenCache()
    cache.deserialize(CACHE_PATH.read_text())

    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            "No cached account found. Run outlook_setup_android.py again."
        )

    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if result and "access_token" in result:
        if cache.has_state_changed:
            CACHE_PATH.write_text(cache.serialize())
        return result["access_token"]

    raise RuntimeError(
        "Token expired. Run outlook_setup_android.py in Termux to re-authenticate."
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def _graph_get(path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Tools ─────────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_emails",
            description=(
                "Search Outlook emails. Filter by keyword (subject + body), "
                "sender, subject text, folder, and how many days back to look."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":    {"type": "string",  "description": "Keyword to match in subject or body"},
                    "sender":   {"type": "string",  "description": "Partial sender name or email"},
                    "subject":  {"type": "string",  "description": "Partial subject line text"},
                    "folder":   {"type": "string",  "description": "inbox (default), sent, drafts, deleted", "default": "inbox"},
                    "days_back":{"type": "integer", "description": "Days back to search (default 30)", "default": 30},
                    "limit":    {"type": "integer", "description": "Max results (default 20, max 50)",  "default": 20},
                },
            },
        ),
        types.Tool(
            name="read_email",
            description="Read the full body of a specific Outlook email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Partial subject of the email"},
                    "sender":  {"type": "string", "description": "Partial sender name or email"},
                    "folder":  {"type": "string", "description": "inbox (default), sent, drafts", "default": "inbox"},
                },
                "required": ["subject"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "search_emails":
            return _search(arguments)
        if name == "read_email":
            return _read(arguments)
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except RuntimeError as exc:
        return [types.TextContent(type="text", text=str(exc))]
    except requests.HTTPError as exc:
        return [types.TextContent(type="text", text=f"Graph API error: {exc}")]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Error: {exc}")]


def _folder_path(folder: str) -> str:
    return FOLDER_PATHS.get(folder.lower(), FOLDER_PATHS["inbox"])


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _search(args: dict) -> list[types.TextContent]:
    folder    = args.get("folder", "inbox")
    days_back = int(args.get("days_back", 30))
    limit     = min(int(args.get("limit", 20)), 50)
    query     = (args.get("query") or "").strip()
    sender_q  = (args.get("sender") or "").lower()
    subject_q = (args.get("subject") or "").lower()

    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params: dict = {
        "$top":     min(limit * 3, 100),
        "$orderby": "receivedDateTime desc",
        "$select":  "subject,from,receivedDateTime,bodyPreview",
    }

    if query:
        # $search does full-text; can't combine with $filter
        params["$search"] = f'"{query}"'
    else:
        params["$filter"] = f"receivedDateTime ge {cutoff}"

    data     = _graph_get(f"/{_folder_path(folder)}", params)
    messages = data.get("value", [])

    results = []
    for msg in messages:
        if len(results) >= limit:
            break
        subj      = (msg.get("subject") or "").lower()
        from_addr = msg.get("from", {}).get("emailAddress", {})
        s_name    = (from_addr.get("name")    or "").lower()
        s_email   = (from_addr.get("address") or "").lower()

        if sender_q  and sender_q  not in s_name  and sender_q  not in s_email:
            continue
        if subject_q and subject_q not in subj:
            continue

        results.append({
            "subject":      msg.get("subject", ""),
            "sender":       from_addr.get("name",    ""),
            "sender_email": from_addr.get("address", ""),
            "received":     msg.get("receivedDateTime", ""),
            "preview":      (msg.get("bodyPreview") or "")[:300],
        })

    if not results:
        return [types.TextContent(type="text", text="No emails matched your criteria.")]

    lines = [f"Found {len(results)} email(s):\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r['subject']}\n"
            f"   From: {r['sender']} <{r['sender_email']}>\n"
            f"   Date: {r['received']}\n"
            f"   {r['preview']}\n"
        )
    return [types.TextContent(type="text", text="\n".join(lines))]


def _read(args: dict) -> list[types.TextContent]:
    folder    = args.get("folder", "inbox")
    subject_q = (args.get("subject") or "").lower()
    sender_q  = (args.get("sender")  or "").lower()

    params: dict = {
        "$top":     50,
        "$orderby": "receivedDateTime desc",
        "$select":  "subject,from,receivedDateTime,body",
    }
    if subject_q:
        params["$search"] = f'"{subject_q}"'

    data     = _graph_get(f"/{_folder_path(folder)}", params)
    messages = data.get("value", [])

    for msg in messages:
        subj      = (msg.get("subject") or "").lower()
        from_addr = msg.get("from", {}).get("emailAddress", {})
        s_name    = (from_addr.get("name")    or "").lower()
        s_email   = (from_addr.get("address") or "").lower()

        if subject_q not in subj:
            continue
        if sender_q and sender_q not in s_name and sender_q not in s_email:
            continue

        body_html = msg.get("body", {}).get("content", "")
        body_text = _strip_html(body_html)[:4000].strip()

        return [types.TextContent(type="text", text=(
            f"Subject: {msg.get('subject', '')}\n"
            f"From:    {from_addr.get('name', '')} <{from_addr.get('address', '')}>\n"
            f"Date:    {msg.get('receivedDateTime', '')}\n\n"
            f"{body_text}"
        ))]

    return [types.TextContent(type="text", text="Email not found.")]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
