"""
Extract TikTok cookies from Chrome via Chrome DevTools Protocol (CDP).
Temporarily relaunches Chrome with remote debugging — restores session automatically.
"""
import subprocess, time, json, urllib.request, websocket, os, sys
from pathlib import Path

CHROME   = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT     = 9222
OUT_FILE = r"C:\Users\equat\Downloads\tiktok_cookies.json"

# 1. Close existing Chrome gracefully
print("Closing Chrome...", flush=True)
subprocess.run(["taskkill", "/IM", "chrome.exe", "/F"], capture_output=True)
time.sleep(2)

# 2. Launch Chrome with remote debugging
print("Launching Chrome with debug port...", flush=True)
proc = subprocess.Popen([
    CHROME,
    f"--remote-debugging-port={PORT}",
    "--no-first-run",
    "--no-default-browser-check",
    "https://www.tiktok.com"
], creationflags=subprocess.DETACHED_PROCESS)
time.sleep(4)

# 3. Get websocket debugger URL
try:
    with urllib.request.urlopen(f"http://localhost:{PORT}/json", timeout=10) as r:
        targets = json.loads(r.read())
    ws_url = next((t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"), None)
    if not ws_url:
        print("No page target found"); sys.exit(1)
    print(f"Connected to: {ws_url[:60]}...", flush=True)
except Exception as e:
    print(f"Failed to connect to CDP: {e}"); sys.exit(1)

# 4. Get all cookies via CDP
ws = websocket.create_connection(ws_url, timeout=10)
ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
result = json.loads(ws.recv())
ws.close()

all_cookies = result.get("result", {}).get("cookies", [])
tiktok_cookies = [c for c in all_cookies if "tiktok.com" in c.get("domain", "")]
print(f"Found {len(tiktok_cookies)} TikTok cookies", flush=True)

# 5. Convert to Cookie-Editor format
cookie_list = []
for c in tiktok_cookies:
    cookie_list.append({
        "name":           c.get("name", ""),
        "value":          c.get("value", ""),
        "domain":         c.get("domain", ""),
        "path":           c.get("path", "/"),
        "expirationDate": c.get("expires") if c.get("expires", -1) > 0 else None,
        "secure":         c.get("secure", False),
        "httpOnly":       c.get("httpOnly", False),
        "sameSite":       c.get("sameSite", "unspecified").lower(),
        "hostOnly":       not c.get("domain", "").startswith("."),
        "session":        c.get("session", False),
        "storeId":        "0",
    })

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(cookie_list, f, indent=2)

print(f"\nSaved to {OUT_FILE}", flush=True)
for c in cookie_list:
    if c["name"] in ("sessionid", "sid_tt", "uid_tt", "msToken"):
        val = c["value"][:25] + "..." if len(c["value"]) > 25 else c["value"]
        print(f"  {c['name']}: {val if val else '(empty)'}")

print("\nDone! Chrome will keep running with your session.", flush=True)
input("Press Enter to close this window")
