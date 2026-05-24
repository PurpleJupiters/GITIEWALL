#!/usr/bin/env python3
r"""
process_audimee_vocals.py — Audimee Post-Download Automation

Run this after Audimee finishes converting your vocals and Chrome has saved
the zip to the AUDIMEE VOCAL DOWNLOADS folder.

What it does:
  1. Finds all .zip files in AUDIMEE VOCAL DOWNLOADS
  2. Extracts the WAV(s) from each zip into the same folder
  3. Deletes the zip
  4. Matches each extracted vocal to a song in the SunoMaster output folder
  5. Runs the pipeline with --vocal + --reuse-stems (fast ~2 min re-master)

Usage:
  python "E:\SunoMaster\scripts\process_audimee_vocals.py"

  # Dry run (shows what it WOULD do without running the pipeline)
  python "E:\SunoMaster\scripts\process_audimee_vocals.py" --dry-run

  # Skip pipeline, just unzip
  python "E:\SunoMaster\scripts\process_audimee_vocals.py" --unzip-only
"""

import re
import sys
import os
import zipfile
import shutil
import subprocess
import argparse
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
AUDIMEE_FOLDER = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs" / "AUDIMEE VOCAL DOWNLOADS"
OUTPUT_FOLDER  = Path(r"E:\SunoMaster\output")
DESKTOP_FOLDER = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs"
CONDA_PYTHON   = Path(r"C:\Dev\envs\sunomaster\python.exe")
PIPELINE       = Path(r"E:\SunoMaster\scripts\sunomaster_v54_final.py")
DEFAULT_REF    = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"
DEFAULT_OUTPUT = r"E:\SunoMaster\output"

# Guide file patterns that Audimee outputs should NOT match
GUIDE_PATTERNS = ("_click_", "_kick_pulse", "_vocal_envelope", "_master_v")


# ── Helpers ───────────────────────────────────────────────────────────────────

def fuzzy_key(s: str) -> str:
    """Lowercase alphanumeric only — for fuzzy name matching."""
    return ''.join(c for c in s.lower() if c.isalnum())


def has_duplicate_suffix(path: Path) -> bool:
    """Return True if the stem ends with (1), (2) etc. — a Chrome duplicate."""
    return bool(re.search(r'\s*\(\d+\)\s*$', path.stem))


def _has_real_stems(song_name: str) -> bool:
    """
    Return True if actual Demucs stem WAVs exist in the output folder
    for this song. Checks for at least one .wav inside demucs_stems/htdemucs_6s/.
    This is the ground truth for whether --reuse-stems will work.
    """
    key = fuzzy_key(song_name)
    if len(key) < 6:
        return False
    for d in sorted(OUTPUT_FOLDER.iterdir()):
        if not d.is_dir():
            continue
        dk = fuzzy_key(d.name)
        overlap = min(len(key), len(dk))
        if overlap >= 6 and key[:overlap] == dk[:overlap]:
            stems_path = d / "demucs_stems" / "htdemucs_6s"
            if stems_path.exists() and any(stems_path.rglob("*.wav")):
                return True
    return False


def find_reuse_stems_dir(song_name: str) -> bool:
    """Check if actual Demucs stem WAVs exist for this song (enables --reuse-stems)."""
    return _has_real_stems(song_name)


def find_original_input(vocal_stem: Path) -> Path | None:
    """
    Find the original input WAV for a given Audimee vocal file.

    Strategy:
      1. Strip Audimee/pipeline suffixes from the vocal filename to get the bare song key.
      2. Collect all matching WAVs from Downloads and Desktop.
      3. Prefer the match that already has real Demucs stems in the output folder.
      4. If none have stems, prefer non-duplicate (no Chrome '(1)' suffix) versions.
    """
    vocal_key = fuzzy_key(vocal_stem.stem)

    # Strip known suffixes iteratively — use fuzzy versions (no underscores/spaces)
    SUFFIXES = tuple(fuzzy_key(s) for s in
                     ('vocals', 'audimee', 'hailey', 'converted', 'stem'))
    changed = True
    while changed:
        changed = False
        for suffix in SUFFIXES:
            if vocal_key.endswith(suffix):
                vocal_key = vocal_key[:-len(suffix)]
                changed = True

    if len(vocal_key) < 4:
        return None

    search_dirs = [
        Path.home() / "Downloads",
        DESKTOP_FOLDER,
    ]

    candidates = []
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.wav")):
            fk = fuzzy_key(f.stem)
            prefix_len = min(len(vocal_key), len(fk), 12)
            if vocal_key[:prefix_len] == fk[:prefix_len] or vocal_key in fk:
                candidates.append(f)

    if not candidates:
        return None

    # Priority 1: candidate that already has real stems — prefer non-duplicate
    with_stems = [c for c in candidates if _has_real_stems(c.stem)]
    if with_stems:
        originals = [c for c in with_stems if not has_duplicate_suffix(c)]
        return originals[0] if originals else with_stems[0]

    # Priority 2: no stems found anywhere — prefer non-duplicate versions
    originals = [c for c in candidates if not has_duplicate_suffix(c)]
    return originals[0] if originals else candidates[0]


def unzip_file(zip_path: Path, dest_folder: Path) -> list[Path]:
    """Extract audio files from a zip flat into dest_folder. Returns extracted paths."""
    extracted = []
    print(f"  [UNZIP] Extracting: {zip_path.name}")
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.namelist():
            mp = Path(member)
            if mp.suffix.lower() in {'.wav', '.mp3', '.flac', '.aiff', '.ogg'}:
                # Flat extract — no subfolder structure preserved
                target = dest_folder / mp.name
                with z.open(member) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(target)
                print(f"  [UNZIP] Extracted: {target.name}")
    return extracted


def run_pipeline(input_wav: Path, vocal_wav: Path,
                 reuse_stems: bool, dry_run: bool) -> bool:
    """Run the SunoMaster pipeline with the Audimee vocal injected."""
    python_exe = str(CONDA_PYTHON) if CONDA_PYTHON.exists() else sys.executable

    cmd = [
        python_exe,
        str(PIPELINE),
        "--input",     str(input_wav),
        "--reference", DEFAULT_REF,
        "--output",    DEFAULT_OUTPUT,
        "--vocal",     str(vocal_wav),
    ]
    if reuse_stems:
        cmd.append("--reuse-stems")

    print(f"\n  [PIPELINE] Input   : {input_wav.name}")
    print(f"  [PIPELINE] Vocal   : {vocal_wav.name}")
    print(f"  [PIPELINE] Stems   : {'reuse (fast)' if reuse_stems else 'full Demucs run'}")

    if dry_run:
        print(f"  [PIPELINE] Command : {' '.join(cmd)}")
        print("  [DRY RUN] Skipping pipeline execution.")
        return True

    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Audimee post-download automation — unzip + re-master",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run",    action="store_true",
                        help="Show what would happen without running the pipeline")
    parser.add_argument("--unzip-only", action="store_true",
                        help="Only unzip, skip pipeline")
    parser.add_argument("--no-reuse",   action="store_true",
                        help="Force full Demucs re-run even if stems exist")
    args = parser.parse_args()

    if not AUDIMEE_FOLDER.exists():
        print(f"ERROR: Audimee folder not found: {AUDIMEE_FOLDER}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Audimee Vocal Processor")
    print(f"  Folder: {AUDIMEE_FOLDER}")
    print(f"{'='*60}\n")

    # ── Step 1: Unzip any downloaded zips ─────────────────────────────────────
    zips = list(AUDIMEE_FOLDER.glob("*.zip"))
    if not zips:
        print("[INFO] No zip files found. Checking for loose WAV files...")

    extracted_wavs = []
    for z in zips:
        wavs = unzip_file(z, AUDIMEE_FOLDER)
        extracted_wavs.extend(wavs)
        if not args.dry_run:
            z.unlink()
            print(f"  [UNZIP] Deleted zip: {z.name}")

    # ── Step 2: Find loose Audimee output WAVs (including in subfolders) ──────
    # These are Audimee-converted vocals — NOT the _vocals.wav inputs we uploaded,
    # and NOT pipeline guide files (click track, kick pulse, etc.)
    existing_wavs = [
        f for f in AUDIMEE_FOLDER.rglob("*.wav")
        if not f.name.endswith("_vocals.wav")
        and not any(p in f.name for p in GUIDE_PATTERNS)
    ]

    # Merge: deduplicate by filename, extracted_wavs take priority
    all_wavs = list({f.name: f for f in existing_wavs + extracted_wavs}.values())

    if not all_wavs:
        print("[INFO] No Audimee vocal WAVs found to process.")
        print(f"       Download from Audimee -> Chrome saves zip to:")
        print(f"       {AUDIMEE_FOLDER}")
        sys.exit(0)

    print(f"\n[INFO] Found {len(all_wavs)} Audimee vocal(s) to process:")
    for w in all_wavs:
        print(f"  * {w.name}")

    if args.unzip_only:
        print("\n[INFO] --unzip-only: done.")
        sys.exit(0)

    # ── Step 3: Match each vocal to its original input and run pipeline ────────
    print()
    results = []
    for vocal_wav in all_wavs:
        print(f"\n{'-'*50}")
        print(f"  Processing: {vocal_wav.name}")

        original = find_original_input(vocal_wav)
        if not original:
            print(f"  [WARN] Could not find original input WAV for: {vocal_wav.name}")
            print(f"         Place the original WAV in Downloads or {DESKTOP_FOLDER}")
            results.append((vocal_wav.name, False, "no original found"))
            continue

        print(f"  [MATCH]  Original: {original.name}")

        reuse = not args.no_reuse and find_reuse_stems_dir(original.stem)
        if reuse:
            print(f"  [INFO]   Stems found -- fast re-master mode (~2 min)")
        else:
            print(f"  [INFO]   No stems found -- full Demucs run (~10 min)")

        ok = run_pipeline(original, vocal_wav, reuse_stems=reuse, dry_run=args.dry_run)
        results.append((vocal_wav.name, ok, "OK" if ok else "FAILED"))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  COMPLETE")
    print(f"{'='*60}")
    for name, ok, status in results:
        mark = "[OK]    " if ok else "[FAILED]"
        print(f"  {mark} {name}  --  {status}")
    print(f"{'='*60}\n")

    failed = sum(1 for _, ok, _ in results if not ok)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
