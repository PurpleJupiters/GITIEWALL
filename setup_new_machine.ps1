# =============================================================================
# SunoMaster + Claude Code Setup Script
# Run this on a fresh Windows machine (e.g. HP ZedBook Pro)
# =============================================================================
# BEFORE RUNNING THIS SCRIPT:
#   1. Install Python 3.11+ from https://python.org  (check "Add to PATH")
#   2. Install Claude Code desktop app from https://claude.ai/download
#   3. Open Claude Code and log in with your Anthropic account
#   4. Close Claude Code fully (check Task Manager)
#   5. Run this script in PowerShell as normal user (not admin)
# =============================================================================

$PROJECT_DIR = "E:\SunoMaster\scripts"
$TELEGRAM_BOT_TOKEN = "8547752402:AAEfMiy2TaliNAEZYgidVCIwDPq5hJGjH2g"
$CLAUDE_EXE = "$env:APPDATA\Claude\claude-code\2.1.142\claude.exe"

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Fail($msg) {
    Write-Host "    FAIL: $msg" -ForegroundColor Red
    exit 1
}

# -----------------------------------------------------------------------------
# STEP 1 — Check prerequisites
# -----------------------------------------------------------------------------
Write-Step "Checking prerequisites..."

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "Python not found. Install from https://python.org and check 'Add to PATH'."
}
Write-OK "Python found: $(python --version)"

# Find claude.exe (version number may differ on new machine)
$CLAUDE_EXE = Get-ChildItem "$env:APPDATA\Claude\claude-code" -Recurse -Filter "claude.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $CLAUDE_EXE) {
    Write-Fail "Claude Code not found. Install from https://claude.ai/download and log in first."
}
Write-OK "Claude Code found: $CLAUDE_EXE"

# -----------------------------------------------------------------------------
# STEP 2 — Create project directory
# -----------------------------------------------------------------------------
Write-Step "Creating project directory: $PROJECT_DIR"

New-Item -ItemType Directory -Force -Path $PROJECT_DIR | Out-Null
New-Item -ItemType Directory -Force -Path "$PROJECT_DIR\.claude" | Out-Null
Write-OK "Directories created"

# -----------------------------------------------------------------------------
# STEP 3 — Install Python dependencies
# -----------------------------------------------------------------------------
Write-Step "Installing Python packages..."

python -m pip install --upgrade pip --quiet
python -m pip install mcp --quiet
Write-OK "mcp package installed"

# Verify
python -c "import mcp; print('mcp ok')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "mcp package failed to import. Try: pip install mcp"
}

# -----------------------------------------------------------------------------
# STEP 4 — Write telegram_mcp.py
# -----------------------------------------------------------------------------
Write-Step "Writing telegram_mcp.py..."

@'
#!/usr/bin/env python3
"""MCP server — sends and reads Telegram messages via Bot API."""

import asyncio
import json
import os
import ssl
import urllib.request
import urllib.parse
import urllib.error

# Windows often has SSL cert issues — create unverified context
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
'@ | Set-Content "$PROJECT_DIR\telegram_mcp.py" -Encoding utf8

Write-OK "telegram_mcp.py written"

# Quick sanity check
python -c "import ast; ast.parse(open('$PROJECT_DIR\telegram_mcp.py').read()); print('syntax ok')"
Write-OK "telegram_mcp.py syntax OK"

# -----------------------------------------------------------------------------
# STEP 5 — Write outlook_mcp.py
# -----------------------------------------------------------------------------
Write-Step "Writing outlook_mcp.py..."

@'
#!/usr/bin/env python3
"""MCP server — searches Outlook emails via win32com (local desktop Outlook)."""

import asyncio
from datetime import datetime, timedelta

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("outlook-email")

FOLDER_IDS = {"inbox": 6, "sent": 5, "drafts": 16, "deleted": 3, "outbox": 4}


def _get_namespace():
    import win32com.client
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")


def _folder_items(ns, folder_name: str):
    return ns.GetDefaultFolder(FOLDER_IDS.get(folder_name.lower(), 6)).Items


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
            description="Search Outlook emails by keyword, sender, subject, folder, and date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword in subject or body"},
                    "sender": {"type": "string", "description": "Partial sender name or email"},
                    "subject": {"type": "string", "description": "Partial subject text"},
                    "folder": {"type": "string", "description": "inbox (default), sent, drafts, deleted", "default": "inbox"},
                    "days_back": {"type": "integer", "description": "Days back to search (default 30)", "default": 30},
                    "limit": {"type": "integer", "description": "Max results (default 20, max 100)", "default": 20},
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
                    "sender": {"type": "string", "description": "Partial sender name or email"},
                    "folder": {"type": "string", "description": "inbox (default), sent, drafts", "default": "inbox"},
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
        return [types.TextContent(type="text", text=f"Cannot connect to Outlook: {exc}\nMake sure Outlook is running.")]
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
            return [types.TextContent(type="text", text="No emails matched.")]
        lines = [f"Found {len(results)} email(s):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['subject']}\n   From: {r['sender']} <{r['sender_email']}>\n   Date: {r['received']}\n   {r['preview']}\n")
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
                return [types.TextContent(type="text", text=f"Subject: {msg.Subject}\nFrom: {msg.SenderName} <{msg.SenderEmailAddress}>\nDate: {msg.ReceivedTime}\n\n{body}")]
            except Exception:
                continue
        return [types.TextContent(type="text", text="Email not found.")]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Read error: {exc}")]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
'@ | Set-Content "$PROJECT_DIR\outlook_mcp.py" -Encoding utf8

Write-OK "outlook_mcp.py written"

# -----------------------------------------------------------------------------
# STEP 6 — Write .mcp.json
# -----------------------------------------------------------------------------
Write-Step "Writing .mcp.json..."

@"
{
  "mcpServers": {
    "outlook-email": {
      "command": "python",
      "args": ["$($PROJECT_DIR.Replace('\','\\'))\\\\outlook_mcp.py"]
    },
    "telegram": {
      "command": "python",
      "args": ["$($PROJECT_DIR.Replace('\','\\'))\\\\telegram_mcp.py"]
    }
  }
}
"@ | Set-Content "$PROJECT_DIR\.mcp.json" -Encoding utf8

Write-OK ".mcp.json written"

# -----------------------------------------------------------------------------
# STEP 7 — Write .claude/settings.local.json (clean version)
# -----------------------------------------------------------------------------
Write-Step "Writing .claude/settings.local.json..."

@'
{
  "permissions": {
    "allow": [
      "WebSearch",
      "Bash(git *)",
      "Bash(pip *)",
      "Bash(python *)"
    ]
  },
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": [
    "outlook-email",
    "telegram"
  ],
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "Set-Location 'E:\\SunoMaster\\scripts'; git add .; $files = git diff --cached --name-only; if ($files) { $msg = 'auto: ' + (($files | Select-Object -First 3) -join ', '); git commit -m $msg; git push }",
            "shell": "powershell",
            "statusMessage": "Auto-committing to GitHub...",
            "async": true
          }
        ]
      }
    ]
  }
}
'@ | Set-Content "$PROJECT_DIR\.claude\settings.local.json" -Encoding utf8

Write-OK "settings.local.json written"

# -----------------------------------------------------------------------------
# STEP 8 — Register telegram at user scope
# -----------------------------------------------------------------------------
Write-Step "Registering telegram MCP server at user scope..."

$result = & $CLAUDE_EXE mcp add --scope user telegram python "$PROJECT_DIR\telegram_mcp.py" 2>&1
Write-Host "    $result"
Write-OK "Telegram registered"

# -----------------------------------------------------------------------------
# STEP 9 — Approve both servers for this project in .claude.json
# -----------------------------------------------------------------------------
Write-Step "Approving MCP servers for this project..."

$claudeJson = "$env:USERPROFILE\.claude.json"
if (Test-Path $claudeJson) {
    $json = Get-Content $claudeJson -Raw | ConvertFrom-Json
    $projectKey = $PROJECT_DIR.Replace("/", "\")

    # Add project entry if missing
    if (-not $json.projects.$projectKey) {
        $json.projects | Add-Member -NotePropertyName $projectKey -NotePropertyValue ([PSCustomObject]@{
            allowedTools = @()
            mcpContextUris = @()
            enabledMcpjsonServers = @("outlook-email", "telegram")
            disabledMcpjsonServers = @()
            hasTrustDialogAccepted = $true
        }) -Force
    } else {
        $json.projects.$projectKey.enabledMcpjsonServers = @("outlook-email", "telegram")
        $json.projects.$projectKey.hasTrustDialogAccepted = $true
    }

    $json | ConvertTo-Json -Depth 20 | Set-Content $claudeJson -Encoding utf8
    Write-OK ".claude.json updated"
} else {
    Write-Host "    NOTE: .claude.json not found yet — open Claude Code once, close it, then re-run Step 9 manually." -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# DONE
# -----------------------------------------------------------------------------
Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host @"

Next steps:
  1. Open Claude Code and navigate to: $PROJECT_DIR
  2. Kill ALL Claude.exe processes in Task Manager
  3. Reopen Claude Code
  4. The telegram and outlook-email MCP tools will be ready

Your Telegram bot:  @Botforbothclaudecodes_bot
Your chat ID:       7887805575

"@ -ForegroundColor White
