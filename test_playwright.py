import asyncio
import sys
import re

sys.stdout.reconfigure(line_buffering=True)

async def main():
    from playwright.async_api import async_playwright

    chrome_profile = r"C:\Temp\ChromePlay"

    print("Starting Playwright with temp profile...", flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile,
            channel="chrome",
            headless=False,
            args=["--start-maximized", "--no-sandbox"],
            timeout=30000
        )
        print(f"Browser launched. Pages: {len(browser.pages)}", flush=True)
        page = browser.pages[0] if browser.pages else await browser.new_page()

        print("Navigating to Microsoft security...", flush=True)
        await page.goto("https://account.microsoft.com/security", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"URL: {url}", flush=True)
        print(f"Title: {title}", flush=True)

        await page.screenshot(path=r"E:\SunoMaster\scripts\ms_screenshot.png")
        print("Screenshot saved.", flush=True)

        # If logged in, try to navigate to advanced security options
        if "account.microsoft.com" in url and "login" not in url.lower():
            print("Logged in! Looking for security options...", flush=True)

            # Try clicking "Advanced security options"
            try:
                await page.click("text=Advanced security options", timeout=5000)
                await page.wait_for_timeout(3000)
                await page.screenshot(path=r"E:\SunoMaster\scripts\ms_advanced.png")
                print("Clicked Advanced security options", flush=True)
            except:
                print("Could not find Advanced security options, trying direct URL...", flush=True)
                await page.goto("https://account.microsoft.com/security/authenticator/add", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                await page.screenshot(path=r"E:\SunoMaster\scripts\ms_auth_add.png")
                print(f"Direct URL: {page.url}", flush=True)
        else:
            print("NOT logged in — saving screenshot for inspection.", flush=True)

        await browser.close()
        print("Done.", flush=True)

asyncio.run(main())
