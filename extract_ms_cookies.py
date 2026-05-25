import sqlite3, json, base64, shutil, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import win32crypt

sys.stdout.reconfigure(line_buffering=True)

CHROME_BASE = r"C:\Users\equat\AppData\Local\Google\Chrome\User Data"
LOCAL_STATE  = os.path.join(CHROME_BASE, "Local State")
COOKIES_DB   = os.path.join(CHROME_BASE, "Default", "Network", "Cookies")
TMP_COOKIES  = r"C:\Temp\chrome_cookies_tmp.db"

# 1. Get encryption key
with open(LOCAL_STATE, "r", encoding="utf-8") as f:
    ls = json.load(f)

key_b64 = ls["os_crypt"]["encrypted_key"]
encrypted_key = base64.b64decode(key_b64)[5:]          # strip "DPAPI" prefix
aes_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
print(f"AES key length: {len(aes_key)}", flush=True)

# 2. Copy cookies DB (Chrome locks it)
shutil.copy2(COOKIES_DB, TMP_COOKIES)

# 3. Decrypt cookies for Microsoft domains
conn = sqlite3.connect(TMP_COOKIES)
cur  = conn.cursor()
cur.execute("""
    SELECT host_key, name, encrypted_value
    FROM cookies
    WHERE host_key LIKE '%microsoft.com%' OR host_key LIKE '%microsoftonline.com%'
    ORDER BY host_key, name
""")

ms_cookies = {}
for host, name, enc_val in cur.fetchall():
    try:
        # Chrome v80+ format: b'\x76\x31\x30' prefix (v10), then 12-byte nonce, then ciphertext
        if enc_val[:3] == b'v10':
            nonce      = enc_val[3:15]
            ciphertext = enc_val[15:]
            value      = AESGCM(aes_key).decrypt(nonce, ciphertext, None).decode("utf-8")
        else:
            value = win32crypt.CryptUnprotectData(enc_val, None, None, None, 0)[1].decode("utf-8")
        ms_cookies[f"{host}::{name}"] = value
    except Exception as e:
        ms_cookies[f"{host}::{name}"] = f"<decrypt error: {e}>"

conn.close()

print(f"\nFound {len(ms_cookies)} Microsoft cookies:", flush=True)
for k, v in ms_cookies.items():
    # Only show key names + first 20 chars of value for safety
    print(f"  {k} = {v[:30]}...", flush=True)

# Save for next step
with open(r"E:\SunoMaster\scripts\ms_cookies.json", "w") as f:
    json.dump(ms_cookies, f, indent=2)

print("\nSaved to ms_cookies.json", flush=True)
