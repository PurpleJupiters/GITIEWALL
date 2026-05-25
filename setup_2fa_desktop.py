import asyncio
import subprocess
import sys
import time
import os
import re

async def main():
    from playwright.async_api import async_playwright

    chrome_user_data = r"C:\Users\equat\AppData\Local\Google\Chrome\User Data"

    print("Killing existing Chrome...")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    time.sleep(2)

    print("Launching Chrome with your existing profile...")
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_user_data,
            channel="chrome",
            headless=False,
            args=["--start-maximized"]
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        print("Navigating to Microsoft account security...")
        await page.goto("https://account.microsoft.com/security", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        print(f"Page title: {await page.title()}")
        print(f"URL: {page.url}")

        # Check if we're logged in or need to sign in
        if "login" in page.url.lower() or "signin" in page.url.lower():
            print("NOT LOGGED IN - waiting up to 60s for manual login...")
            await page.wait_for_url("**/security**", timeout=60000)

        print("On security page. Looking for 'Advanced security options'...")
        await page.wait_for_timeout(2000)

        # Try to find and click advanced security options
        try:
            advanced = page.locator("text=Advanced security options").first
            await advanced.click()
            await page.wait_for_timeout(3000)
            print("Clicked Advanced security options")
        except Exception as e:
            print(f"Could not find 'Advanced security options': {e}")

        # Look for "Add a new way to sign in" or similar
        try:
            add_btn = page.locator("text=Add a new way to sign in").first
            await add_btn.click()
            await page.wait_for_timeout(2000)
            print("Clicked Add a new way to sign in")
        except Exception as e:
            print(f"Trying alternative button: {e}")
            try:
                add_btn = page.locator("text=Use an app").first
                await add_btn.click()
                await page.wait_for_timeout(2000)
            except Exception as e2:
                print(f"Alternative also failed: {e2}")

        # Try to find "I can't scan the barcode" to get text secret
        await page.wait_for_timeout(3000)
        try:
            cant_scan = page.locator("text=can't scan").first
            await cant_scan.click()
            await page.wait_for_timeout(2000)
            print("Clicked can't scan barcode")
        except:
            pass

        # Extract secret key from page
        content = await page.content()

        # Look for base32 secret (usually 16-32 chars of A-Z2-7)
        secrets = re.findall(r'secret=([A-Z2-7]{16,})', content)
        if not secrets:
            secrets = re.findall(r'[A-Z2-7]{16,32}', content)

        if secrets:
            secret = secrets[0]
            print(f"\nSECRET KEY FOUND: {secret}")
            # Save it
            with open("totp_secret.txt", "w") as f:
                f.write(secret)
            print("Saved to totp_secret.txt")
        else:
            print("Secret not found in page source, taking screenshot...")
            await page.screenshot(path="ms_security_page.png")
            print("Screenshot saved: ms_security_page.png")

        print("\nKeeping browser open for 30 seconds...")
        await page.wait_for_timeout(30000)
        await browser.close()

asyncio.run(main())
