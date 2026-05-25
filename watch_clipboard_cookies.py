"""
Watches clipboard — the moment you copy TikTok cookies via Cookie-Editor,
this saves them automatically and exits.
"""
import time, json, subprocess, sys
from pathlib import Path

OUT = Path(r"C:\Users\equat\Downloads\tiktok_cookies.json")

print("WAITING... Go to tiktok.com in Chrome, click Cookie-Editor → Export")
print("This window will close automatically once cookies are detected.\n", flush=True)

last = ""
while True:
    try:
        result = subprocess.run(
            ["powershell", "-command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        clip = result.stdout.strip()
        if clip and clip != last and clip.startswith("["):
            try:
                data = json.loads(clip)
                tiktok = [c for c in data if "tiktok" in c.get("domain", "").lower()]
                if len(tiktok) > 0:
                    OUT.write_text(clip, encoding="utf-8")
                    print(f"SAVED! {len(tiktok)} TikTok cookies → {OUT}")
                    print("You can close this window.")
                    input()
                    sys.exit(0)
            except json.JSONDecodeError:
                pass
        last = clip
    except Exception:
        pass
    time.sleep(1)
