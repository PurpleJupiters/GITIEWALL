import asyncio
import sys
import re

sys.stdout.reconfigure(line_buffering=True)

async def main():
    from playwright.async_api import async_playwright

    print("Connecting to running Chrome via CDP...", flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222", timeout=15000)
        print(f"Connected! Contexts: {len(browser.contexts)}", flush=True)

        ctx = browser.contexts[0]
        pages = ctx.pages
        print(f"Open pages: {len(pages)}", flush=True)
        for pg in pages:
            print(f"  - {pg.url}", flush=True)

        # Open new page and navigate to Microsoft security
        page = await ctx.new_page()
        print("Navigating to Microsoft security...", flush=True)
        await page.goto("https://account.microsoft.com/security", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"URL: {url}", flush=True)
        print(f"Title: {title}", flush=True)

        await page.screenshot(path=r"E:\SunoMaster\scripts\ms_screenshot.png")
        print("Screenshot saved.", flush=True)

        if "account.microsoft.com" in url and "login" not in url.lower() and "microsoftonline" not in url:
            print("LOGGED IN! Proceeding with authenticator setup...", flush=True)

            # Navigate directly to add authenticator
            await page.goto("https://account.microsoft.com/security", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)

            # Click Advanced security options
            try:
                await page.click("a:has-text('Advanced security options')", timeout=8000)
                await page.wait_for_timeout(3000)
                print(f"Advanced options URL: {page.url}", flush=True)
                await page.screenshot(path=r"E:\SunoMaster\scripts\ms_advanced.png")
            except Exception as e:
                print(f"Advanced click failed: {e}", flush=True)
                # Try finding any link to security settings
                links = await page.eval_on_selector_all("a", "els => els.map(e => ({text: e.textContent.trim(), href: e.href}))")
                for l in links[:20]:
                    print(f"  Link: {l}", flush=True)

            # Try to find "add authenticator" options
            try:
                content = await page.content()
                if "authenticator" in content.lower() or "verification" in content.lower():
                    await page.screenshot(path=r"E:\SunoMaster\scripts\ms_auth_page.png")
                    print("Authenticator page found — screenshot saved.", flush=True)
            except Exception as e:
                print(f"Error: {e}", flush=True)
        else:
            print(f"NOT logged in. URL: {url}", flush=True)

        # Keep browser open — don't close so Ronald's session is preserved
        print("Done — Chrome stays open.", flush=True)

asyncio.run(main())
