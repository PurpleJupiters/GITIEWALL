import asyncio
import sys

sys.stdout.reconfigure(line_buffering=True)

async def main():
    from playwright.async_api import async_playwright

    chrome_user_data = r"C:\Users\equat\AppData\Local\Google\Chrome\User Data"

    print("Starting Playwright...", flush=True)
    async with async_playwright() as p:
        print("Launching Chrome with existing profile...", flush=True)
        try:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=chrome_user_data,
                channel="chrome",
                headless=False,
                args=["--start-maximized", "--no-sandbox"],
                timeout=30000
            )
            print(f"Browser launched. Pages: {len(browser.pages)}", flush=True)
            page = browser.pages[0] if browser.pages else await browser.new_page()

            print("Navigating to Microsoft security...", flush=True)
            await page.goto("https://account.microsoft.com/security", wait_until="domcontentloaded", timeout=30000)
            print(f"URL: {page.url}", flush=True)
            print(f"Title: {await page.title()}", flush=True)

            await page.screenshot(path=r"E:\SunoMaster\scripts\ms_screenshot.png")
            print("Screenshot saved!", flush=True)

            await browser.close()
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()

asyncio.run(main())
print("Done.", flush=True)
