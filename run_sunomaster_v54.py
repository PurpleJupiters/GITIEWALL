#!/usr/bin/env python3
"""
Claude Code Runner for SunoMaster v5.4

This script wraps the main pipeline for clean execution via Claude Code.
It handles conda environment activation and runs the pipeline with the correct arguments.

Usage in Claude Code:
    python "E:\\SunoMaster\\scripts\\run_sunomaster_v54.py" --input "C:\\Users\\equat\\Downloads\\Transfinite (Agent WALL) Master.wav"

Or with all options:
    python "E:\\SunoMaster\\scripts\\run_sunomaster_v54.py" --input "SONG.wav" --reference "REFERENCE.wav" --output "E:\\SunoMaster\\output"
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

def run_pipeline(input_file, reference_file=None, output_dir=None, bpm=None,
                 vocal_file=None, reuse_stems=False):
    """Run the SunoMaster v5.4 pipeline."""
    
    # Defaults
    if output_dir is None:
        output_dir = r"E:\SunoMaster\output"
    if reference_file is None:
        reference_file = "# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"
    
    # Verify input exists
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_file}")
        sys.exit(1)
    
    # Use the sunomaster conda environment's Python
    conda_python = r"C:\Dev\envs\sunomaster\python.exe"
    python_exe = conda_python if Path(conda_python).exists() else sys.executable

    # Build command
    cmd = [
        python_exe,
        r"E:\SunoMaster\scripts\sunomaster_v54_final.py",
        "--input", str(input_path),
        "--reference", reference_file,
        "--output", output_dir,
    ]
    
    if bpm:
        cmd.extend(["--bpm", str(bpm)])
    if vocal_file:
        cmd.extend(["--vocal", str(vocal_file)])
    if reuse_stems:
        cmd.append("--reuse-stems")
    
    print(f"\n{'='*60}")
    print(f"  SunoMaster v5.4 — Claude Code Runner")
    print(f"{'='*60}")
    print(f"\nInput:     {input_path.name}")
    print(f"Reference: {reference_file}")
    print(f"Output:    {output_dir}")
    if bpm:
        print(f"BPM:       {bpm}")
    print(f"\n{'='*60}")
    print(f"  Starting pipeline...\n")
    
    # Run pipeline (conda activation happens automatically in sunomaster conda env)
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user.")
        return 1
    except Exception as e:
        print(f"\nERROR: {e}")
        return 1

def main():
    parser = argparse.ArgumentParser(
        description="SunoMaster v5.4 Pipeline Runner (Claude Code wrapper)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_sunomaster_v54.py --input "C:\\Users\\equat\\Downloads\\Transfinite (Agent WALL) Master.wav"
  python run_sunomaster_v54.py --input "song.wav" --output "E:\\SunoMaster\\output"
  python run_sunomaster_v54.py --input "song.wav" --reference "reference.wav" --bpm 132.5
        """
    )
    
    parser.add_argument(
        "--input",
        required=True,
        help="Input WAV file (full path or filename in current directory)"
    )
    parser.add_argument(
        "--reference",
        default=None,
        help="Reference track filename (default: Guy J - Worlds Apart Normalized -8 LUFS.wav)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: E:\\SunoMaster\\output)"
    )
    parser.add_argument(
        "--bpm",
        type=float,
        default=None,
        help="BPM override (optional — auto-detected if not provided)"
    )
    parser.add_argument(
        "--vocal",
        default=None,
        help="External vocal WAV from Audimee (replaces Demucs vocal stem, auto-aligned)"
    )
    parser.add_argument(
        "--reuse-stems",
        action="store_true",
        help="Skip Demucs + P0/P1 and reuse stems from previous run (fast re-master, ~2 min)"
    )

    args = parser.parse_args()

    returncode = run_pipeline(
        input_file=args.input,
        reference_file=args.reference,
        output_dir=args.output,
        bpm=args.bpm,
        vocal_file=args.vocal,
        reuse_stems=args.reuse_stems,
    )
    
    sys.exit(returncode)

if __name__ == "__main__":
    main()
