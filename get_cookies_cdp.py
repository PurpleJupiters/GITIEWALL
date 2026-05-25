import urllib.request, json, websocket
from pathlib import Path

with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
    targets = json.loads(r.read())

ws_url = next((t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"), None)
print("WS:", ws_url[:60] if ws_url else "None")

ws = websocket.create_connection(ws_url, timeout=10)
ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
result = json.loads(ws.recv())
ws.close()

all_cookies = result.get("result", {}).get("cookies", [])
tiktok = [c for c in all_cookies if "tiktok.com" in c.get("domain", "")]
print(f"TikTok cookies: {len(tiktok)}")

cookie_list = []
for c in tiktok:
    val = c["value"][:40] + "..." if len(c["value"]) > 40 else c["value"]
    print(f"  {c['name']}: {val if val else '(empty)'}")
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

out = Path(r"C:\Users\equat\Downloads\tiktok_cookies.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(cookie_list, f, indent=2)
print(f"\nSaved {len(cookie_list)} cookies to {out}")
