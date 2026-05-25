"""
Extract TikTok cookies from Chrome and save in Cookie-Editor JSON format
"""
import os, json, shutil, sqlite3, base64
from pathlib import Path

# Chrome paths
local_state_path = Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data/Local State"
cookies_path     = Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data/Default/Network/Cookies"
cookies_copy     = Path(r"E:\SunoMaster\scripts\chrome_cookies_tmp.db")
output_path      = Path(r"C:\Users\equat\Downloads\tiktok_cookies.json")

# Step 1: Get encryption key
with open(local_state_path, "r", encoding="utf-8") as f:
    local_state = json.load(f)

encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
encrypted_key = base64.b64decode(encrypted_key_b64)[5:]  # strip "DPAPI" prefix

# Decrypt master key using Windows DPAPI
import win32crypt
master_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]

# Step 2: Copy cookies DB (Chrome locks it while running)
shutil.copy2(cookies_path, cookies_copy)

# Step 3: Query TikTok cookies
conn = sqlite3.connect(cookies_copy)
cursor = conn.execute("""
    SELECT name, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly, samesite
    FROM cookies
    WHERE host_key LIKE '%tiktok.com%'
""")
rows = cursor.fetchall()
conn.close()
cookies_copy.unlink()

# Step 4: Decrypt each cookie value
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def decrypt_value(encrypted_value, key):
    try:
        if encrypted_value[:3] == b'v10' or encrypted_value[:3] == b'v11':
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:]
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
        else:
            # Old DPAPI-encrypted
            return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode("utf-8")
    except Exception:
        return ""

# Step 5: Build Cookie-Editor format
cookie_list = []
for name, enc_val, host, path, expires, secure, httponly, samesite in rows:
    value = decrypt_value(enc_val, master_key)
    samesite_map = {-1: "unspecified", 0: "no_restriction", 1: "lax", 2: "strict"}
    cookie_list.append({
        "name": name,
        "value": value,
        "domain": host,
        "path": path,
        "expirationDate": expires / 1000000 - 11644473600 if expires > 0 else None,
        "secure": bool(secure),
        "httpOnly": bool(httponly),
        "sameSite": samesite_map.get(samesite, "unspecified"),
        "hostOnly": not host.startswith("."),
        "session": expires == 0,
        "storeId": "0",
    })

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(cookie_list, f, indent=2)

print(f"Saved {len(cookie_list)} TikTok cookies to {output_path}")
for c in cookie_list:
    if c["name"] in ("sessionid", "tt_webid", "tt_csrf_token", "msToken"):
        val_preview = c["value"][:20] + "..." if len(c["value"]) > 20 else c["value"]
        print(f"  {c['name']}: {val_preview}")
