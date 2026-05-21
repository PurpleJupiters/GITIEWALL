#!/usr/bin/env python3
"""MCP server — searches Outlook emails via win32com (local desktop Outlook)."""

import asyncio
from datetime import datetime, timedelta

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("outlook-email")

FOLDER_IDS = {
    "inbox": 6,
    "sent": 5,
    "drafts": 16,
    "deleted": 3,
    "outbox": 4,
}


def _get_namespace():
    import win32com.client
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")


def _folder_items(ns, folder_name: str):
    fid = FOLDER_IDS.get(folder_name.lower(), 6)
    return ns.GetDefaultFolder(fid).Items


def _format_email(msg) -> dict:
    preview = (getattr(msg, "Body", "") or "")[:400].replace("\r\n", " ").strip()
    return {
        "subject": getattr(msg, "Subject", "") or "",
        "sender": getattr(msg, "SenderName", "") or "",
        "sender_email": getattr(msg, "SenderEmailAddress", "") or "",
        "received": str(getattr(msg, "ReceivedTime", "")),
        "preview": preview,
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_emails",
            description=(
                "Search Outlook emails. Filters by keyword (subject + body), sender, "
                "subject text, folder, and how many days back to look."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to match anywhere in subject or body",
                    },
                    "sender": {
                        "type": "string",
                        "description": "Partial sender name or email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Partial subject line text",
                    },
                    "folder": {
                        "type": "string",
                        "description": "inbox (default), sent, drafts, deleted",
                        "default": "inbox",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to search (default 30)",
                        "default": 30,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 20, max 100)",
                        "default": 20,
                    },
                },
            },
        ),
        types.Tool(
            name="read_email",
            description="Read the full body of a specific Outlook email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Partial subject of the email to open",
                    },
                    "sender": {
                        "type": "string",
                        "description": "Partial sender name or email to narrow the match",
                    },
                    "folder": {
                        "type": "string",
                        "description": "inbox (default), sent, drafts",
                        "default": "inbox",
                    },
                },
                "required": ["subject"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        ns = _get_namespace()
    except Exception as exc:
        return [types.TextContent(
            type="text",
            text=f"Cannot connect to Outlook: {exc}\nMake sure Outlook is running.",
        )]

    if name == "search_emails":
        return _search(ns, arguments)
    if name == "read_email":
        return _read(ns, arguments)
    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


def _search(ns, args: dict) -> list[types.TextContent]:
    folder_name = args.get("folder", "inbox")
    days_back = int(args.get("days_back", 30))
    limit = min(int(args.get("limit", 20)), 100)
    query = (args.get("query") or "").lower()
    sender_q = (args.get("sender") or "").lower()
    subject_q = (args.get("subject") or "").lower()

    cutoff = datetime.now() - timedelta(days=days_back)
    cutoff_str = cutoff.strftime("%m/%d/%Y %H:%M %p")

    try:
        items = _folder_items(ns, folder_name)
        items.Sort("[ReceivedTime]", True)
        restricted = items.Restrict(f"[ReceivedTime] >= '{cutoff_str}'")

        results = []
        for msg in restricted:
            if len(results) >= limit:
                break
            try:
                subj = (getattr(msg, "Subject", "") or "").lower()
                s_name = (getattr(msg, "SenderName", "") or "").lower()
                s_email = (getattr(msg, "SenderEmailAddress", "") or "").lower()
                body = (getattr(msg, "Body", "") or "").lower()

                if sender_q and sender_q not in s_name and sender_q not in s_email:
                    continue
                if subject_q and subject_q not in subj:
                    continue
                if query and query not in subj and query not in body:
                    continue

                results.append(_format_email(msg))
            except Exception:
                continue

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

    except Exception as exc:
        return [types.TextContent(type="text", text=f"Search error: {exc}")]


def _read(ns, args: dict) -> list[types.TextContent]:
    folder_name = args.get("folder", "inbox")
    subject_q = (args.get("subject") or "").lower()
    sender_q = (args.get("sender") or "").lower()

    try:
        items = _folder_items(ns, folder_name)
        items.Sort("[ReceivedTime]", True)

        for msg in items:
            try:
                subj = (getattr(msg, "Subject", "") or "").lower()
                s_name = (getattr(msg, "SenderName", "") or "").lower()
                s_email = (getattr(msg, "SenderEmailAddress", "") or "").lower()

                if subject_q not in subj:
                    continue
                if sender_q and sender_q not in s_name and sender_q not in s_email:
                    continue

                body = (getattr(msg, "Body", "") or "")[:4000]
                text = (
                    f"Subject: {msg.Subject}\n"
                    f"From:    {msg.SenderName} <{msg.SenderEmailAddress}>\n"
                    f"Date:    {msg.ReceivedTime}\n\n"
                    f"{body}"
                )
                return [types.TextContent(type="text", text=text)]
            except Exception:
                continue

        return [types.TextContent(type="text", text="Email not found.")]

    except Exception as exc:
        return [types.TextContent(type="text", text=f"Read error: {exc}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
