#!/usr/bin/env python3
"""MCP server -- sends and reads Telegram messages via Bot API."""

import asyncio
import json
import os
import ssl
import urllib.request
import urllib.error

# Windows often has SSL cert issues -- create unverified context
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("telegram")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8547752402:AAEfMiy2TaliNAEZYgidVCIwDPq5hJGjH2g")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _api(method: str, params: dict = None) -> dict:
    url = f"{API_BASE}/{method}"
    data = json.dumps(params or {}).encode("utf-8") if params else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
        return json.loads(resp.read())


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="send_message",
            description="Send a Telegram message to a chat or user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or @username"},
                    "text": {"type": "string", "description": "Message text to send"},
                },
                "required": ["chat_id", "text"],
            },
        ),
        types.Tool(
            name="get_updates",
            description="Get recent messages sent to the bot.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of updates (default 10, max 100)", "default": 10},
                },
            },
        ),
        types.Tool(
            name="get_chat_info",
            description="Get information about a Telegram chat or user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or @username"},
                },
                "required": ["chat_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "send_message":
            return _send_message(arguments)
        if name == "get_updates":
            return _get_updates(arguments)
        if name == "get_chat_info":
            return _get_chat_info(arguments)
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except urllib.error.URLError as exc:
        return [types.TextContent(type="text", text=f"Network error: {exc}")]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Error: {exc}")]


def _send_message(args: dict) -> list[types.TextContent]:
    result = _api("sendMessage", {"chat_id": args["chat_id"], "text": args["text"]})
    if result.get("ok"):
        msg = result["result"]
        return [types.TextContent(type="text", text=f"Sent. Message ID: {msg['message_id']}")]
    return [types.TextContent(type="text", text=f"Failed: {result.get('description')}")]


def _get_updates(args: dict) -> list[types.TextContent]:
    limit = min(int(args.get("limit", 10)), 100)
    result = _api("getUpdates", {"limit": limit})
    if not result.get("ok"):
        return [types.TextContent(type="text", text=f"Failed: {result.get('description')}")]
    updates = result["result"]
    if not updates:
        return [types.TextContent(type="text", text="No recent messages.")]
    lines = [f"Found {len(updates)} update(s):\n"]
    for u in updates:
        msg = u.get("message") or u.get("channel_post")
        if not msg:
            continue
        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        name = (sender.get("first_name", "") + " " + sender.get("last_name", "")).strip()
        chat_name = chat.get("title") or chat.get("username") or str(chat.get("id"))
        lines.append(f"- [{chat_name}] {name or 'Unknown'}: {msg.get('text', '(no text)')}")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _get_chat_info(args: dict) -> list[types.TextContent]:
    result = _api("getChat", {"chat_id": args["chat_id"]})
    if not result.get("ok"):
        return [types.TextContent(type="text", text=f"Failed: {result.get('description')}")]
    chat = result["result"]
    return [types.TextContent(type="text", text="\n".join([
        f"Chat ID: {chat.get('id')}",
        f"Type: {chat.get('type')}",
        f"Title: {chat.get('title', 'N/A')}",
        f"Username: @{chat.get('username', 'N/A')}",
    ]))]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())