"""
SunoMaster - Split & AI Detection Checker
==========================================
Splits all songs and reference tracks into 4 equal parts.
Saves part 1 of each to E:\SunoMaster\shortened\
Runs AI detection on each shortened file using:
  1. Internal fingerprint (always - no key needed)
  2. LetsSubmit API (if you provide an API key)
Prints a full comparison table: songs vs references.

This script is useful BEFORE running the pipeline (baseline),
and AFTER (to verify improvement).
The main sunomaster.py pipeline also does this automatically
at P0 (before cleaning) and P3 (after mastering).

USAGE:
  & "C:\Dev\envs\sunomaster\python.exe" "E:\SunoMaster\scripts\split_and_check.py"
  & "C:\Dev\envs\sunomaster\python.exe" "E:\SunoMaster\scripts\split_and_check.py" --lskey YOUR_KEY
  & "C:\Dev\envs\sunomaster\python.exe" "E:\SunoMaster\scripts\split_and_check.py" --lskey YOUR_KEY --phase after
"""

import os, sys, json, time, argparse, warnings
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d
from scipy.interpolate import interp1d

try:
    import requests; HAS_REQ = True
except ImportError:
    HAS_REQ = False; print("[WARN] requests not installed - LetsSubmit API unavailable")

# -- PATHS --------------------------------------------------------------------
BASE       = r"E:\SunoMaster"
RELEASES   = os.path.join(BASE, "releases")
REFERENCES = os.path.join(BASE, "references", "normalized reference tracks")
REF_ALT    = os.path.join(BASE, "references")
SHORTENED  = os.path.join(BASE, "shortened")
os.makedirs(SHORTENED, exist_ok=True)

# -- INTERNAL AI FINGERPRINT ---------------------------------------------------
FP_FMIN, FP_FMAX, FP_BINS, FP_DWIN = 5000, 16000, 128, 18

def fingerprint(mono, sr):
    fmax = min(FP_FMAX, sr//2-200)
    f,_,Z = signal.stft(mono, fs=sr, nperseg=4096, noverlap=3072, window='hann')
    avg   = np.mean(np.abs(Z), axis=1)
    mask  = (f>=FP_FMIN)&(f<=fmax)
    bf    = np.linspace(FP_FMIN, fmax, FP_BINS)
    s     = interp1d(f[mask], avg[mask], kind='linear',
                     bounds_error=False, fill_value=0.0)(bf)
    lm  = minimum_filter1d(s, size=FP_DWIN); raw = s-lm; pk = raw.max()
    return raw/pk if pk>0 else raw.copy()

def fp_score(norm):
    top8  = np.sort(norm)[-8:]
    logit = (top8.mean()-0.35)*8.0
    return float(1.0/(1.0+np.exp(-logit)))

def internal_ai_score(wav_path):
    try:
        audio, sr = sf.read(wav_path, always_2d=True)
        mono = np.mean(audio, axis=1).astype(np.float64)
        norm = fingerprint(mono, sr)
        return round(fp_score(norm)*100, 1)
    except Exception as e:
        print(f"    [WARN] Internal score failed: {e}")
        return None

# -- LETSSUBMIT API ------------------------------------------------------------
def letssubmit_api(wav_path, api_key):
    """
    Upload shortened WAV to file.io (temporary link), then submit to LetsSubmit.
    Returns percentage score or None.
    """
    if not HAS_REQ or not api_key:
        return None
    try:
        print(f"    Uploading to file.io...")
        with open(wav_path, 'rb') as f:
            r = requests.post('https://file.io', files={'file':f},
                              data={'expires':'1h'}, timeout=120)
        if r.status_code != 200:
            print(f"    [WARN] file.io upload failed: {r.status_code}")
            return None
        url = r.json().get('link')
        if not url:
            print(f"    [WARN] No link from file.io"); return None

        print(f"    Submitting to LetsSubmit API...")
        r2 = requests.post(
            'https://api.letssubmit.com/analyze_song',
            headers={'Authorization': f'Bearer {api_key}',
                     'Content-Type': 'application/json'},
            json={'file_url': url}, timeout=300)
        if r2.status_code == 200:
            result = r2.json()
            score  = result.get('ai_percentage') or result.get('score') or result.get('pct')
            if score is not None:
                return round(float(score), 1)
            print(f"    LetsSubmit raw: {result}")
            return None
        else:
            print(f"    [WARN] LetsSubmit API: {r2.status_code} {r2.text[:100]}")
            return None
    except Exception as e:
        print(f"    [WARN] LetsSubmit error: {e}")
        return None

def letssubmit_open_browser(wav_path):
    """Open LetsSubmit in browser for manual check."""
    import webbrowser
    webbrowser.open("https://letssubmit.com/ai-music-checker")
    print(f"    Browser opened. Upload manually: {wav_path}")

# -- SPLIT INTO 4 EQUAL PARTS -------------------------------------------------
def split_and_save_part1(wav_path, out_name, out_dir):
    """
    Split WAV into 4 equal parts by sample count.
    Save ONLY part 1 to out_dir.
    Returns path to saved part 1.
    """
    audio, sr = sf.read(wav_path, always_2d=True)
    n     = audio.shape[0]
    part  = n // 4
    part1 = audio[:part]
    dur   = part/sr

    info  = sf.info(wav_path)
    sub   = 'PCM_24' if 'PCM_24' in info.subtype else 'PCM_16'

    out_path = os.path.join(out_dir, f"{out_name}_part1.wav")
    sf.write(out_path, part1, sr, subtype=sub)
    print(f"    Part 1 saved: {os.path.basename(out_path)} ({dur:.1f}s, {sr}Hz {sub})")
    return out_path, dur

# -- FIND FILES ----------------------------------------------------------------
def find_songs():
    songs = []
    if not os.path.exists(RELEASES): return songs
    for entry in sorted(os.scandir(RELEASES), key=lambda e: e.name):
        if not entry.is_dir(): continue
        wavs = sorted([f for f in os.listdir(entry.path) if f.lower().endswith('.wav')])
        if not wavs: continue
        chosen = next((w for w in wavs if 'original' in w.lower()), wavs[0])
        songs.append((entry.name, os.path.join(entry.path, chosen)))
    return songs

def find_references():
    refs = []
    search = REFERENCES if os.path.exists(REFERENCES) else REF_ALT
    if not os.path.exists(search): return refs
    for f in sorted(os.listdir(search)):
        if f.lower().endswith('.wav'):
            refs.append((os.path.splitext(f)[0], os.path.join(search, f)))
    return refs

# -- MAIN ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lskey",  default="", help="LetsSubmit API key")
    ap.add_argument("--phase",  default="before", help="before or after (labels the report)")
    ap.add_argument("--no-browser", action="store_true", help="Do not open browser for manual check")
    args = ap.parse_args()

    ls_key = args.lskey.strip() or None
    phase  = args.phase.strip()

    print(f"\n{'='*70}")
    print(f"  SunoMaster - Split & AI Detection Check ({phase.upper()})")
    print(f"  Output folder: {SHORTENED}")
    if ls_key:
        print(f"  LetsSubmit API: key provided - automated checking enabled")
    else:
        print(f"  LetsSubmit API: no key - browser will open for manual checking")
    print(f"{'='*70}\n")

    songs = find_songs()
    refs  = find_references()
    print(f"Found {len(songs)} songs in releases folder")
    print(f"Found {len(refs)} reference tracks")

    if not songs and not refs:
        print("Nothing to process."); return

    results = []

    # Process songs
    if songs:
        print(f"\n{'-'*70}")
        print(f"  YOUR SONGS")
        print(f"{'-'*70}")
        for name, wav_path in songs:
            print(f"\n  [{name}]")
            print(f"    Source: {os.path.basename(wav_path)}")
            try:
                out_path, dur = split_and_save_part1(wav_path, name, SHORTENED)
                internal     = internal_ai_score(out_path)
                ls_score     = None
                if ls_key:
                    ls_score = letssubmit_api(out_path, ls_key)
                    if ls_score is None:
                        print(f"    LetsSubmit API returned no score.")
                elif not args.no_browser:
                    letssubmit_open_browser(out_path)
                    time.sleep(2)

                print(f"    Internal AI fingerprint: {internal:.1f}%" if internal else "    Internal: N/A")
                if ls_score is not None:
                    print(f"    LetsSubmit score:        {ls_score:.1f}%")

                results.append({
                    "name": name, "type": "song", "dur_s": round(dur,1),
                    "internal_pct": internal, "letssubmit_pct": ls_score,
                    "part1_path": out_path
                })
            except Exception as e:
                print(f"    ERROR: {e}")

    # Process references
    if refs:
        print(f"\n{'-'*70}")
        print(f"  REFERENCE TRACKS")
        print(f"{'-'*70}")
        for name, wav_path in refs:
            safe_name = name.replace(' ','_').replace(',','').replace("'","")
            print(f"\n  [{name[:50]}]")
            try:
                out_path, dur = split_and_save_part1(wav_path, safe_name, SHORTENED)
                internal     = internal_ai_score(out_path)
                ls_score     = None
                if ls_key:
                    ls_score = letssubmit_api(out_path, ls_key)
                elif not args.no_browser:
                    time.sleep(1)  # don't spam browser

                print(f"    Internal AI fingerprint: {internal:.1f}%" if internal else "    Internal: N/A")
                if ls_score is not None:
                    print(f"    LetsSubmit score:        {ls_score:.1f}%")

                results.append({
                    "name": name, "type": "reference", "dur_s": round(dur,1),
                    "internal_pct": internal, "letssubmit_pct": ls_score,
                    "part1_path": out_path
                })
            except Exception as e:
                print(f"    ERROR: {e}")

    # Summary table
    print(f"\n{'='*70}")
    print(f"  SUMMARY TABLE - {phase.upper()} PIPELINE")
    print(f"{'='*70}")
    print(f"  {'Name':<42} {'Type':<10} {'Dur':>5} {'Internal%':>10} {'LetsSubmit%':>12}")
    print(f"  {'-'*68}")

    song_internals = [r['internal_pct'] for r in results if r['type']=='song' and r['internal_pct'] is not None]
    ref_internals  = [r['internal_pct'] for r in results if r['type']=='reference' and r['internal_pct'] is not None]
    song_ls        = [r['letssubmit_pct'] for r in results if r['type']=='song' and r['letssubmit_pct'] is not None]
    ref_ls         = [r['letssubmit_pct'] for r in results if r['type']=='reference' and r['letssubmit_pct'] is not None]

    for r in results:
        int_str = f"{r['internal_pct']:>9.1f}%" if r['internal_pct'] is not None else f"{'N/A':>10}"
        ls_str  = f"{r['letssubmit_pct']:>11.1f}%" if r['letssubmit_pct'] is not None else f"{'N/A':>12}"
        flag    = " [AI]" if (r['internal_pct'] or 0) > 50 else ""
        print(f"  {r['name'][:42]:<42} {r['type']:<10} {r['dur_s']:>4.0f}s {int_str} {ls_str}{flag}")

    print(f"  {'-'*68}")
    if song_internals:
        avg_s = np.mean(song_internals)
        avg_r = np.mean(ref_internals) if ref_internals else 0
        print(f"  {'YOUR SONGS average':<42} {'':10} {'':>5} {avg_s:>9.1f}%")
        print(f"  {'REFERENCE average':<42} {'':10} {'':>5} {avg_r:>9.1f}%")
        if ref_internals:
            gap = avg_s - avg_r
            print(f"  Gap (songs - references): {gap:+.1f}% internal AI score")
            print(f"  Goal: close this gap to < 5% through the pipeline")

    if not ls_key:
        print(f"\n  To automate LetsSubmit checking, run with your API key:")
        print(f"  & \"C:\\Dev\\envs\\sunomaster\\python.exe\" \"{os.path.abspath(__file__)}\" --lskey YOUR_KEY")
        print(f"  Get your key at: https://letssubmit.com/ai-music-checker/api")

    # Save report
    report_path = os.path.join(SHORTENED, f"ai_detection_report_{phase}.json")
    with open(report_path, 'w') as f:
        json.dump({"phase":phase,"results":results,
                   "song_avg_internal":float(np.mean(song_internals)) if song_internals else None,
                   "ref_avg_internal":float(np.mean(ref_internals)) if ref_internals else None}, f, indent=2)
    print(f"\n  Report saved: {report_path}")
    print(f"  Part 1 files saved in: {SHORTENED}")
    print(f"\n  All 12 files are in the shortened folder. Upload each to:")
    print(f"  https://letssubmit.com/ai-music-checker")
    print(f"{'='*70}")

if __name__ == '__main__':
    main()