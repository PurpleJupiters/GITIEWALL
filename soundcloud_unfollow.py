"""
SoundCloud Auto-Unfollow — Agent WALL
Unfollows all 440 artists in soundcloud_UNFOLLOW.xlsx
"""
import json, requests, time, urllib3, pandas as pd
from datetime import datetime

urllib3.disable_warnings()

CLIENT_ID   = "tUy37JutyVy6r6JSMLnScSmBwA5DoTXE"
MY_ID       = 196753
BASE        = "https://api-v2.soundcloud.com"
UNFOLLOW_XL = r"E:\SunoMaster\scripts\soundcloud_UNFOLLOW.xlsx"
JSON_SRC    = r"E:\SunoMaster\scripts\soundcloud_following.json"
AUTH_FILE   = r"C:\Users\equat\Downloads\sc_auth.json"
LOG_FILE    = r"E:\SunoMaster\scripts\unfollow_log.txt"
DELAY       = 0.8   # seconds between calls

with open(AUTH_FILE) as f:
    auth = json.load(f)["auth"]

HEADERS = {
    "Authorization": auth,
    "Origin": "https://soundcloud.com",
    "Referer": "https://soundcloud.com/wall-0/following",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

with open(JSON_SRC) as f:
    all_users = json.load(f)
id_map = {u["username"]: u["id"] for u in all_users}

df = pd.read_excel(UNFOLLOW_XL)
to_unfollow = []
for _, row in df.iterrows():
    uname = row["Username"]
    uid = id_map.get(uname)
    if uid:
        to_unfollow.append({"username": uname, "id": uid, "followers": row.get("Followers", 0)})

total = len(to_unfollow)
done = 0
failed = []

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(line + "\n")

log(f"=== Unfollow started — {total} artists ===")

for i, artist in enumerate(to_unfollow, 1):
    url = f"{BASE}/me/followings/{artist['id']}?client_id={CLIENT_ID}&app_version=1779379648"
    try:
        r = requests.delete(url, headers=HEADERS, verify=False, timeout=10)
        if r.status_code in (200, 201, 204):
            done += 1
            log(f"[{i}/{total}] UNFOLLOWED: {artist['username']} ({artist['followers']} followers)")
        elif r.status_code == 404:
            done += 1
            log(f"[{i}/{total}] ALREADY UNFOLLOWED: {artist['username']}")
        elif r.status_code == 401:
            log(f"AUTH EXPIRED at {i}/{total}. Re-run after refreshing token.")
            break
        else:
            failed.append(artist["username"])
            log(f"[{i}/{total}] FAILED ({r.status_code}): {artist['username']}")
    except Exception as e:
        failed.append(artist["username"])
        log(f"[{i}/{total}] ERROR: {artist['username']} — {e}")

    time.sleep(DELAY)

log(f"\n=== DONE ===")
log(f"Unfollowed: {done}/{total}")
log(f"Failed: {len(failed)}")
if failed:
    log(f"Failed list: {failed}")
log(f"New following count should be approx: 2000 - {done} = {2000 - done}")
