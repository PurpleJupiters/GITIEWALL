#!/usr/bin/env python3
"""Run once in Termux to authenticate Claude Code with your Outlook account.

Usage:
    python outlook_setup_android.py
"""

import json
from pathlib import Path

import msal

CONFIG_PATH = Path.home() / ".outlook_mcp" / "config.json"
CACHE_PATH  = Path.home() / ".outlook_mcp" / "token_cache.json"
SCOPES      = ["https://graph.microsoft.com/Mail.Read"]


def main():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load or create config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
    else:
        config = {}

    if not config.get("client_id"):
        print("\n--- Outlook MCP Setup ---")
        print("You need the Application (client) ID from your Azure App Registration.")
        print("See README or the setup instructions for how to get it.\n")
        client_id = input("Paste your Application (client) ID: ").strip()
        tenant    = input("Tenant ID (press Enter to use 'common' — works for most accounts): ").strip() or "common"
        config["client_id"] = client_id
        config["tenant_id"] = tenant
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print(f"Config saved to {CONFIG_PATH}\n")

    client_id = config["client_id"]
    tenant_id = config.get("tenant_id", "common")

    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())

    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    # Check existing cached token first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            if cache.has_state_changed:
                CACHE_PATH.write_text(cache.serialize())
            username = accounts[0].get("username", "unknown")
            print(f"Already authenticated as: {username}")
            print("Token is valid — MCP server is ready.")
            return

    # Trigger device flow (user visits a URL and enters a code)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"Error initiating device flow: {flow.get('error_description', 'unknown')}")
        return

    print("\n" + "=" * 60)
    print(flow["message"])
    print("=" * 60)
    print("\nOpen that URL in any browser (phone or desktop), enter the code, then")
    print("sign in with your Microsoft/Outlook account.")
    print("\nWaiting... (you have ~15 minutes)\n")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        if cache.has_state_changed:
            CACHE_PATH.write_text(cache.serialize())
        username = result.get("id_token_claims", {}).get("preferred_username", "unknown")
        print(f"\nAuthentication successful! Signed in as: {username}")
        print("Token cached. The MCP server will now work without re-authentication.")
    else:
        print(f"\nAuthentication failed: {result.get('error_description', 'unknown error')}")


if __name__ == "__main__":
    main()
