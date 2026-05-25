"""
TikTok Auto-Unfollow — unfollows everyone you follow
Requires: C:\Users\equat\Downloads\tiktok_cookies.json (exported via Cookie-Editor)
"""
import json, requests, time, sys
from datetime import datetime

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

COOKIES_FILE = r"C:\Users\equat\Downloads\tiktok_cookies.json"
LOG_FILE     = r"E:\SunoMaster\scripts\tiktok_unfollow_log.txt"
DELAY        = 1.5  # seconds between unfollows

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# Load cookies
with open(COOKIES_FILE) as f:
    raw = json.load(f)

# Cookie-Editor exports as list of {name, value, ...} dicts
cookies = {c["name"]: c["value"] for c in raw}

session = requests.Session()
session.cookies.update(cookies)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.tiktok.com/",
    "Origin": "https://www.tiktok.com",
}

def get_ms_token():
    return cookies.get("msToken", "")

def get_following(cursor=0, count=200):
    url = "https://www.tiktok.com/api/relation/following/list/"
    params = {
        "count": count,
        "cursor": cursor,
        "scene": 21,
        "msToken": get_ms_token(),
    }
    r = session.get(url, headers=HEADERS, params=params, timeout=15)
    return r.json()

def unfollow(user_id, sec_uid):
    url = "https://www.tiktok.com/api/commit/follow/user/"
    params = {
        "user_id": user_id,
        "sec_user_id": sec_uid,
        "type": 2,  # 1=follow, 2=unfollow
        "msToken": get_ms_token(),
    }
    r = session.post(url, headers=HEADERS, params=params, timeout=15)
    return r.json()

# Collect all following first
log("=== TikTok Unfollow started ===")
log("Fetching following list...")

all_following = []
cursor = 0
while True:
    data = get_following(cursor=cursor)
    users = data.get("userList", [])
    if not users:
        break
    for u in users:
        ui = u.get("user", {})
        all_following.append({
            "user_id": ui.get("id"),
            "sec_uid": ui.get("secUid"),
            "nickname": ui.get("nickname", "?"),
            "unique_id": ui.get("uniqueId", "?"),
        })
    has_more = data.get("hasMore", False)
    cursor = data.get("cursor", 0)
    log(f"  Fetched {len(all_following)} so far...")
    if not has_more:
        break
    time.sleep(0.5)

total = len(all_following)
log(f"Total following: {total}")

done = 0
failed = []

for i, user in enumerate(all_following, 1):
    try:
        result = unfollow(user["user_id"], user["sec_uid"])
        status = result.get("status_code", -1)
        if status == 0:
            done += 1
            log(f"[{i}/{total}] UNFOLLOWED: @{user['unique_id']} ({user['nickname']})")
        else:
            failed.append(user["unique_id"])
            log(f"[{i}/{total}] FAILED (status {status}): @{user['unique_id']}")
    except Exception as e:
        failed.append(user["unique_id"])
        log(f"[{i}/{total}] ERROR: @{user['unique_id']} — {e}")
    time.sleep(DELAY)

log(f"\n=== DONE ===")
log(f"Unfollowed: {done}/{total}")
log(f"Failed: {len(failed)}")
if failed:
    log(f"Failed list: {failed}")

input("Enter to close")
