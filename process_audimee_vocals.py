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

  # Dry run — shows what it WOULD do, without running the pipeline
  python "E:\SunoMaster\scripts\process_audimee_vocals.py" --dry-run

  # Skip pipeline, just unzip
  python "E:\SunoMaster\scripts\process_audimee_vocals.py" --unzip-only
"""

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


def fuzzy_key(s: str) -> str:
    """Lowercase alphanumeric only — for fuzzy name matching."""
    return ''.join(c for c in s.lower() if c.isalnum())


def find_original_input(vocal_stem: Path) -> Path | None:
    """
    Find the original input WAV for a given Audimee vocal file.
    Looks in Downloads and Latest Mastered Songs.
    Matches by fuzzy song name prefix.
    """
    vocal_key = fuzzy_key(vocal_stem.stem)
    # Strip known suffixes that Audimee or the pipeline might add
    for suffix in ['_vocals', '_audimee', '_hailey', '_converted']:
        if vocal_key.endswith(suffix):
            vocal_key = vocal_key[:-len(suffix)]

    search_dirs = [
        Path.home() / "Downloads",
        DESKTOP_FOLDER,
    ]
    for d in search_dirs:
        for f in d.glob("*.wav"):
            fk = fuzzy_key(f.stem)
            if vocal_key in fk or fk.startswith(vocal_key[:10]):
                return f
    return None


def find_reuse_stems_dir(song_name: str) -> bool:
    """Check if P1 stems exist for this song (enables --reuse-stems)."""
    key = fuzzy_key(song_name)
    for d in OUTPUT_FOLDER.iterdir():
        if not d.is_dir():
            continue
        if fuzzy_key(d.name)[:len(key)] == key[:min(len(key), len(fuzzy_key(d.name)))]:
            stems_dir = d / "demucs_stems"
            if stems_dir.exists():
                return True
    return False


def unzip_file(zip_path: Path, dest_folder: Path) -> list[Path]:
    """Extract a zip file, return list of extracted WAV paths."""
    extracted = []
    print(f"  [UNZIP] Extracting: {zip_path.name}")
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.namelist():
            mp = Path(member)
            if mp.suffix.lower() in {'.wav', '.mp3', '.flac', '.aiff', '.ogg'}:
                # Extract flat (no subfolders) into dest_folder
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

    print(f"\n  [PIPELINE] Input  : {input_wav.name}")
    print(f"  [PIPELINE] Vocal  : {vocal_wav.name}")
    print(f"  [PIPELINE] Reuse  : {reuse_stems}")
    print(f"  [PIPELINE] Command: {' '.join(cmd)}\n")

    if dry_run:
        print("  [DRY RUN] Skipping pipeline execution.")
        return True

    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Audimee post-download automation — unzip + re-master",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run",     action="store_true",
                        help="Show what would happen without running the pipeline")
    parser.add_argument("--unzip-only",  action="store_true",
                        help="Only unzip, skip pipeline")
    parser.add_argument("--no-reuse",    action="store_true",
                        help="Force full Demucs re-run (slow) even if stems exist")
    args = parser.parse_args()

    if not AUDIMEE_FOLDER.exists():
        print(f"ERROR: Audimee folder not found: {AUDIMEE_FOLDER}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Audimee Vocal Processor")
    print(f"  Folder: {AUDIMEE_FOLDER}")
    print(f"{'='*60}\n")

    # ── Step 1: Find and unzip all zips ────────────────────────────────────────
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

    # Also pick up any WAVs already in the folder (or subfolders) that look like
    # Audimee outputs — i.e. NOT the _vocals.wav we put there ourselves, and NOT
    # the guide files the pipeline generates.
    GUIDE_PATTERNS = ("_click_", "_kick_pulse", "_vocal_envelope", "_master_v")
    existing_wavs = [
        f for f in AUDIMEE_FOLDER.rglob("*.wav")
        if not f.name.endswith("_vocals.wav")
        and not any(p in f.name for p in GUIDE_PATTERNS)
    ]
    all_wavs = list({f.name: f for f in extracted_wavs + existing_wavs}.values())

    if not all_wavs:
        print("[INFO] No Audimee vocal WAVs found to process.")
        print(f"       Download from Audimee → Chrome saves zip to:")
        print(f"       {AUDIMEE_FOLDER}")
        sys.exit(0)

    print(f"\n[INFO] Found {len(all_wavs)} Audimee vocal(s) to process:")
    for w in all_wavs:
        print(f"  • {w.name}")

    if args.unzip_only:
        print("\n[INFO] --unzip-only: done.")
        sys.exit(0)

    # ── Step 2: Match each vocal to its original input and run pipeline ─────────
    print()
    results = []
    for vocal_wav in all_wavs:
        print(f"\n{'-'*50}")
        print(f"  Processing: {vocal_wav.name}")

        # Find original input WAV
        original = find_original_input(vocal_wav)
        if not original:
            print(f"  [WARN] Could not find original input WAV for: {vocal_wav.name}")
            print(f"         Skipping pipeline run. Place the original WAV in Downloads")
            print(f"         or {DESKTOP_FOLDER}")
            results.append((vocal_wav.name, False, "no original found"))
            continue

        # Check if we can reuse stems
        reuse = not args.no_reuse and find_reuse_stems_dir(original.stem)
        if reuse:
            print(f"  [INFO] Existing stems found — using --reuse-stems (fast mode)")
        else:
            print(f"  [INFO] No existing stems — full Demucs run needed (~10 min)")

        ok = run_pipeline(original, vocal_wav, reuse_stems=reuse, dry_run=args.dry_run)
        results.append((vocal_wav.name, ok, "OK" if ok else "FAILED"))

    # ── Summary ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  COMPLETE")
    print(f"{'='*60}")
    for name, ok, status in results:
        mark = "[OK]    " if ok else "[FAILED]"
        print(f"  {mark} {name}  —  {status}")
    print(f"{'='*60}\n")

    failed = sum(1 for _, ok, _ in results if not ok)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
