#!/usr/bin/env python3
r"""
batch_sunomaster.py — Process multiple songs through SunoMaster v5.4

Scans an input folder for WAV files and runs the full pipeline on each one.
Optionally matches Audimee vocal replacements from a separate folder.

Usage:
  # Process all WAVs in a folder
  python batch_sunomaster.py --input-folder "E:\Songs"

  # Process with Audimee vocal replacements
  python batch_sunomaster.py --input-folder "E:\Songs" --vocals-folder "E:\Audimee"

  # Fast re-master with new vocals (reuse existing stems)
  python batch_sunomaster.py --input-folder "E:\Songs" --vocals-folder "E:\Audimee" --reuse-stems

  # Override BPM for all songs (or use per-song BPM file — see below)
  python batch_sunomaster.py --input-folder "E:\Songs" --bpm 133.9

Audimee vocal matching:
  The script matches vocal files by song name (case-insensitive, ignoring spaces/dashes).
  Example:
    Song:  "Transfinite (Agent WALL) Master.wav"
    Vocal: "Transfinite_audimee.wav"  <-- matched by "transfinite" prefix
    Vocal: "Transfinite (Agent WALL) Master_vocal.wav"  <-- also matched

Per-song BPM override:
  Place a text file next to the WAV with the same name + "_bpm.txt" containing
  just the BPM number, e.g. "MySong_bpm.txt" containing "128.0".
  If not found, BPM is auto-detected.
"""

import sys
import os
import subprocess
import argparse
import time
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
CONDA_PYTHON   = r"C:\Dev\envs\sunomaster\python.exe"
PIPELINE_SCRIPT = Path(__file__).parent / "sunomaster_v54_final.py"
DEFAULT_OUTPUT  = r"E:\SunoMaster\output"
DEFAULT_REF     = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"


def find_vocal_match(song_name: str, vocals_folder: Path) -> Path | None:
    """
    Find an Audimee vocal WAV that matches the given song name.
    Matching is fuzzy: compares lowercase alphanumeric characters only.
    """
    def _key(s):
        return ''.join(c for c in s.lower() if c.isalnum())

    song_key = _key(song_name)
    for f in vocals_folder.glob("*.wav"):
        if _key(f.stem) in song_key or song_key[:12] in _key(f.stem):
            return f
    return None


def load_bpm_override(song_path: Path) -> float | None:
    """Look for a {songname}_bpm.txt file next to the WAV."""
    bpm_file = song_path.parent / (song_path.stem + "_bpm.txt")
    if bpm_file.exists():
        try:
            return float(bpm_file.read_text().strip())
        except Exception:
            pass
    return None


def run_song(song_path: Path, vocal_path: Path | None, output_dir: str,
             reference: str, bpm: float | None, reuse_stems: bool,
             python_exe: str) -> tuple[bool, float]:
    """Run the pipeline for a single song. Returns (success, elapsed_seconds)."""
    python_exe = python_exe if Path(python_exe).exists() else sys.executable

    cmd = [
        python_exe,
        str(PIPELINE_SCRIPT),
        "--input",     str(song_path),
        "--output",    output_dir,
        "--reference", reference,
    ]
    if bpm:
        cmd += ["--bpm", str(bpm)]
    if vocal_path:
        cmd += ["--vocal", str(vocal_path)]
    if reuse_stems:
        cmd.append("--reuse-stems")

    t0 = time.time()
    result = subprocess.run(cmd, check=False)
    elapsed = time.time() - t0
    return result.returncode == 0, elapsed


def main():
    parser = argparse.ArgumentParser(
        description="SunoMaster v5.4 Batch Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input-folder",  required=True,
                        help="Folder containing input WAV files")
    parser.add_argument("--vocals-folder", default=None,
                        help="Folder containing Audimee vocal WAVs (optional)")
    parser.add_argument("--output",        default=DEFAULT_OUTPUT,
                        help=f"Output root folder (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--reference",     default=DEFAULT_REF,
                        help="Reference WAV file or filename in default folder")
    parser.add_argument("--bpm",           type=float, default=None,
                        help="BPM override for ALL songs (auto-detected if omitted)")
    parser.add_argument("--reuse-stems",   action="store_true",
                        help="Skip Demucs for songs that already have P1 stems")
    parser.add_argument("--pattern",       default="*.wav",
                        help="Glob pattern for input files (default: *.wav)")
    args = parser.parse_args()

    input_folder  = Path(args.input_folder)
    vocals_folder = Path(args.vocals_folder) if args.vocals_folder else None
    python_exe    = CONDA_PYTHON

    if not input_folder.exists():
        print(f"ERROR: Input folder not found: {input_folder}")
        sys.exit(1)
    if vocals_folder and not vocals_folder.exists():
        print(f"ERROR: Vocals folder not found: {vocals_folder}")
        sys.exit(1)

    songs = sorted(input_folder.glob(args.pattern))
    if not songs:
        print(f"No WAV files found in: {input_folder}")
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"  SunoMaster v5.4 — Batch Runner")
    print(f"  Songs found   : {len(songs)}")
    print(f"  Output        : {args.output}")
    print(f"  Vocal folder  : {vocals_folder or 'none (Demucs vocals)'}")
    print(f"  Reuse stems   : {args.reuse_stems}")
    print(f"{'='*60}\n")

    results = []
    for idx, song in enumerate(songs, 1):
        vocal = find_vocal_match(song.stem, vocals_folder) if vocals_folder else None
        bpm   = load_bpm_override(song) or args.bpm

        print(f"\n[{idx}/{len(songs)}] {song.name}")
        if vocal:
            print(f"         Vocal: {vocal.name}")
        if bpm:
            print(f"         BPM  : {bpm}")

        ok, elapsed = run_song(
            song_path   = song,
            vocal_path  = vocal,
            output_dir  = args.output,
            reference   = args.reference,
            bpm         = bpm,
            reuse_stems = args.reuse_stems,
            python_exe  = python_exe,
        )
        status = "[OK]" if ok else "[FAILED]"
        results.append((song.name, ok, elapsed))
        print(f"         {status}  {elapsed/60:.1f} min")

    # ── Summary ────────────────────────────────────────────────────────────────
    total = time.time()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE  —  {passed} OK  /  {failed} FAILED")
    print(f"{'='*60}")
    for name, ok, elapsed in results:
        mark = "[OK]    " if ok else "[FAILED]"
        print(f"  {mark} {name:<50} {elapsed/60:.1f} min")
    print(f"{'='*60}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
