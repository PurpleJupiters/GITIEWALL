#!/usr/bin/env python3
r"""
audimee_batch_playwright.py — Fully automated batch Audimee vocal conversion

What it does (hands-free after you press Enter):
  1. Finds all *_vocals.wav files in AUDIMEE VOCAL DOWNLOADS
  2. For each one:
       a. Opens Audimee in your real Chrome (keeps your login + Tampermonkey)
       b. Uploads the vocal WAV to the Audimee dropzone
       c. Confirms Hailey is selected (auto-selects if not)
       d. Clicks Convert and waits for completion (up to 10 min)
       e. Clicks the Download button when it appears
       f. Saves the zip to AUDIMEE VOCAL DOWNLOADS
       g. Extracts WAV(s), deletes the zip
       h. Moves to the next file
  3. Prints a summary when done

REQUIREMENTS:
  Close Chrome BEFORE running (script needs exclusive access to your profile).
  First-time setup (run once in your conda env):
    pip install playwright
    playwright install chrome

USAGE:
  C:\Dev\envs\sunomaster\python.exe "E:\SunoMaster\scripts\audimee_batch_playwright.py"
  ... --dry-run          (list files, open browser, but skip converting)
  ... --one "file.wav"   (process a single specific file)
  ... --headless         (run without visible browser window)
"""

import sys
import os
import time
import zipfile
import shutil
import argparse
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
AUDIMEE_FOLDER   = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs" / "AUDIMEE VOCAL DOWNLOADS"
AUDIMEE_URL      = "https://audimee.com/create"
HAILEY_NAME      = "Hailey"
CHROME_USER_DATA = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"

CONVERSION_TIMEOUT_S  = 600     # 10 minutes per song
POLL_INTERVAL_S       = 3       # how often to check for download button


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_vocals(folder: Path) -> list[Path]:
    """All *_vocals.wav files in the folder, sorted by name."""
    return sorted(folder.glob("*_vocals.wav"))


def extract_zip(zip_path: Path, dest: Path) -> list[Path]:
    """Extract audio files from zip flat into dest. Returns extracted paths."""
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.namelist():
            mp = Path(member)
            if mp.suffix.lower() in {".wav", ".mp3", ".flac", ".aiff", ".ogg"}:
                target = dest / mp.name
                with z.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(target)
    return extracted


def select_hailey(page, modal_selector='[role="dialog"]') -> bool:
    """Open Switch voice modal and select Hailey. Returns True if successful."""
    from playwright.sync_api import TimeoutError as PWTimeout

    # Check current voice
    try:
        h2 = page.locator("h2").first
        if h2.is_visible() and h2.inner_text().strip() == HAILEY_NAME:
            print(f"  [VOICE] Hailey already selected.")
            return True
    except Exception:
        pass

    # Click Switch voice
    try:
        switch = page.locator('button:has-text("Switch voice")').first
        switch.wait_for(state="visible", timeout=8_000)
        switch.click()
        time.sleep(0.8)
    except PWTimeout:
        print("  [VOICE] No Switch voice button found — assuming Hailey is pre-selected.")
        return True

    # Wait for modal
    try:
        page.wait_for_selector(modal_selector, timeout=6_000)
    except PWTimeout:
        print("  [VOICE] Modal did not open.")
        return False

    modal = page.locator(modal_selector).first

    # Look for Hailey directly
    hailey_el = modal.locator(f'text="{HAILEY_NAME}"').first
    if not hailey_el.is_visible():
        # Search box approach
        try:
            search = modal.locator("input").first
            search.wait_for(state="visible", timeout=4_000)
            # React-compatible clear + type
            search.triple_click()
            search.type(HAILEY_NAME, delay=60)
            time.sleep(1.0)
            hailey_el = modal.locator(f'text="{HAILEY_NAME}"').first
        except Exception as e:
            print(f"  [VOICE] Search error: {e}")
            return False

    # Click the card (walk up to button if needed)
    try:
        hailey_el.click()
        time.sleep(0.8)
    except Exception as e:
        print(f"  [VOICE] Click error: {e}")
        return False

    # Modal should close
    try:
        page.wait_for_selector(modal_selector, state="detached", timeout=4_000)
        print(f"  [VOICE] Hailey selected!")
        return True
    except PWTimeout:
        print(f"  [VOICE] Modal still open after clicking Hailey — continuing anyway.")
        return True


def upload_file(page, vocal_path: Path) -> bool:
    """Upload vocal WAV to Audimee dropzone. Returns True on success."""
    from playwright.sync_api import TimeoutError as PWTimeout

    # Audimee has a hidden file input behind a styled dropzone
    try:
        file_input = page.locator('input[type="file"]').first
        file_input.wait_for(state="attached", timeout=10_000)
        file_input.set_input_files(str(vocal_path))
        print(f"  [UPLOAD] {vocal_path.name}")
        time.sleep(2)
        return True
    except PWTimeout:
        print(f"  [UPLOAD] No file input found on page.")
        return False
    except Exception as e:
        print(f"  [UPLOAD] Error: {e}")
        return False


def wait_for_download_btn(page, timeout_s: int = CONVERSION_TIMEOUT_S):
    """
    Poll until a Download button / link appears on the page.
    Returns the locator, or None on timeout.
    """
    selectors = [
        'button:has-text("Download")',
        'a:has-text("Download")',
        '[class*="download"]:has-text("Download")',
        'button:has-text("Save")',
        'a[download]',
    ]
    deadline = time.time() + timeout_s
    dots = 0
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    print()  # newline after dots
                    return el
            except Exception:
                pass
        # Progress dots
        dots += 1
        if dots % 10 == 0:
            elapsed = int(time.time() - (deadline - timeout_s))
            print(f"  [WAIT] Still converting... ({elapsed}s elapsed)", end="\r", flush=True)
        time.sleep(POLL_INTERVAL_S)
    print()
    return None


# ── Core per-song logic ───────────────────────────────────────────────────────

def process_one(page, vocal_path: Path, dry_run: bool) -> tuple[bool, str]:
    """Full Audimee flow for one vocal file. Returns (success, status_message)."""
    from playwright.sync_api import TimeoutError as PWTimeout

    if dry_run:
        print(f"  [DRY RUN] Would upload: {vocal_path.name}")
        return True, "dry run"

    # ── 1. Navigate to Audimee ─────────────────────────────────────────────
    print(f"  [NAV] Opening {AUDIMEE_URL}")
    try:
        page.goto(AUDIMEE_URL, wait_until="domcontentloaded", timeout=30_000)
    except PWTimeout:
        page.goto(AUDIMEE_URL, timeout=30_000)

    # Give Tampermonkey time to auto-select Hailey
    time.sleep(4)

    # ── 2. Upload ──────────────────────────────────────────────────────────
    if not upload_file(page, vocal_path):
        return False, "upload failed"

    # ── 3. Voice selection ────────────────────────────────────────────────
    # Tampermonkey may have already done this; select_hailey() checks first
    select_hailey(page)
    time.sleep(1)

    # ── 4. Click Convert ──────────────────────────────────────────────────
    convert_selectors = [
        'button:has-text("Convert")',
        'button:has-text("Start conversion")',
        'button:has-text("Generate")',
        'button:has-text("Process")',
        'button[type="submit"]',
    ]
    convert_btn = None
    for sel in convert_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                convert_btn = el
                break
        except Exception:
            continue

    if not convert_btn:
        ss = AUDIMEE_FOLDER / f"debug_{vocal_path.stem}_no_convert_btn.png"
        try:
            page.screenshot(path=str(ss))
        except Exception:
            pass
        return False, "Convert button not found (screenshot saved)"

    convert_btn.click()
    print(f"  [CONVERT] Clicked Convert — waiting for completion (up to {CONVERSION_TIMEOUT_S//60} min)...")
    time.sleep(2)

    # ── 5. Wait for Download button ───────────────────────────────────────
    dl_btn = wait_for_download_btn(page, timeout_s=CONVERSION_TIMEOUT_S)
    if not dl_btn:
        ss = AUDIMEE_FOLDER / f"debug_{vocal_path.stem}_timeout.png"
        try:
            page.screenshot(path=str(ss))
        except Exception:
            pass
        return False, f"Timed out after {CONVERSION_TIMEOUT_S}s waiting for Download button"

    # ── 6. Download the result ─────────────────────────────────────────────
    print(f"  [DOWNLOAD] Download button found — clicking...")
    zip_dest = None
    try:
        with page.expect_download(timeout=60_000) as dl_info:
            dl_btn.click()
        download = dl_info.value
        fname = download.suggested_filename or f"{vocal_path.stem}_result.zip"
        zip_dest = AUDIMEE_FOLDER / fname
        download.save_as(str(zip_dest))
        print(f"  [DOWNLOAD] Saved: {fname}")
    except Exception as e:
        return False, f"Download failed: {e}"

    # ── 7. Extract and clean up ────────────────────────────────────────────
    if not zip_dest or not zip_dest.exists():
        return False, "Zip file not found after download"

    try:
        extracted = extract_zip(zip_dest, AUDIMEE_FOLDER)
        zip_dest.unlink()
        print(f"  [EXTRACT] Deleted zip: {zip_dest.name}")
        for f in extracted:
            print(f"  [EXTRACT] Got: {f.name}")
    except Exception as e:
        return False, f"Extraction failed: {e}"

    names = ", ".join(f.name for f in extracted)
    return True, f"-> {names}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fully automated batch Audimee vocal conversion via Playwright",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run",  action="store_true",
                        help="Navigate + list files but skip converting")
    parser.add_argument("--one",      metavar="FILE",
                        help="Process a single WAV file instead of the whole folder")
    parser.add_argument("--headless", action="store_true",
                        help="Run without visible browser (may break Tampermonkey)")
    args = parser.parse_args()

    # Sanity check
    if not AUDIMEE_FOLDER.exists():
        print(f"ERROR: Audimee folder not found:\n  {AUDIMEE_FOLDER}")
        sys.exit(1)

    # Check playwright
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed.")
        print(f"Fix:  {sys.executable} -m pip install playwright")
        print(f"Then: {sys.executable} -m playwright install chrome")
        sys.exit(1)

    # Collect files
    if args.one:
        p = Path(args.one)
        if not p.exists():
            p = AUDIMEE_FOLDER / args.one
        if not p.exists():
            print(f"ERROR: File not found: {args.one}")
            sys.exit(1)
        vocals = [p]
    else:
        vocals = find_vocals(AUDIMEE_FOLDER)

    if not vocals:
        print("[INFO] No *_vocals.wav files found in:")
        print(f"       {AUDIMEE_FOLDER}")
        print()
        print("The pipeline saves vocal stems there automatically.")
        print("Run process_audimee_vocals.py if you already have zips to extract.")
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"  Audimee Batch Automation — Playwright")
    print(f"  Files   : {len(vocals)}")
    print(f"  Folder  : {AUDIMEE_FOLDER}")
    if args.dry_run:
        print(f"  Mode    : DRY RUN (no conversion)")
    print(f"{'='*60}")
    print()
    print("  IMPORTANT: Make sure Chrome is closed before continuing.")
    print("  Press Enter to start, or Ctrl+C to cancel.")
    try:
        input()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)

    results = []

    with sync_playwright() as p:
        print("  [BROWSER] Launching Chrome with your profile...")

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_USER_DATA),
            channel="chrome",
            headless=args.headless,
            accept_downloads=True,
            args=[
                "--profile-directory=Default",
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
            ],
            viewport={"width": 1280, "height": 900},
        )

        # Use first page or open new
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for i, vocal in enumerate(vocals, 1):
            print(f"\n{'─'*60}")
            print(f"  [{i}/{len(vocals)}] {vocal.name}")
            print(f"{'─'*60}")

            ok, status = process_one(page, vocal, args.dry_run)
            results.append((vocal.name, ok, status))

            if not ok:
                print(f"\n  [FAILED] {status}")
            else:
                print(f"\n  [OK] {status}")

            # Brief pause between songs
            if i < len(vocals):
                print(f"\n  Pausing 3s before next file...")
                time.sleep(3)

        ctx.close()
        print("\n  [BROWSER] Chrome closed.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  COMPLETE — {len(results)} file(s) processed")
    print(f"{'='*60}")
    for name, ok, status in results:
        mark = "[ OK ]" if ok else "[FAIL]"
        print(f"  {mark}  {name}")
        print(f"         {status}")
    print(f"{'='*60}\n")

    failed = sum(1 for _, ok, _ in results if not ok)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
