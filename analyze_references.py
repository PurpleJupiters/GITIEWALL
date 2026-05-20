"""
SunoMaster - Independent Reference Track Analyzer
==================================================
Uses the best available Python audio analysis libraries to produce
a fully independent measurement of all WAV files in a folder.

Libraries used:
  pyloudnorm  - EBU R128 / ITU-R BS.1770 integrated LUFS (industry standard)
  soundfile   - lossless WAV reading
  scipy       - Welch PSD spectral analysis, signal processing
  librosa     - BPM detection, key detection, spectral features
  numpy       - all numerical calculations
"""

import os, sys, json, glob, warnings
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.signal import welch

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False
    print("[WARN] librosa not installed - BPM and key detection unavailable")

try:
    import pyloudnorm as pyln
    HAS_LN = True
    print("[OK]  pyloudnorm available - EBU R128 LUFS measurement active")
except ImportError:
    HAS_LN = False
    print("[WARN] pyloudnorm not installed - using RMS approximation for LUFS")

# -- FOLDER TO ANALYZE --------------------------------------------------------

FOLDER = r"E:\SunoMaster\references\normalized reference tracks"

if not os.path.exists(FOLDER):
    print(f"ERROR: Folder not found: {FOLDER}")
    sys.exit(1)

wavs = sorted([os.path.join(FOLDER, f)
               for f in os.listdir(FOLDER) if f.lower().endswith('.wav')])

if not wavs:
    print(f"ERROR: No WAV files found in {FOLDER}")
    sys.exit(1)

print(f"\nFound {len(wavs)} WAV files to analyze:")
for w in wavs:
    print(f"  {os.path.basename(w)}")

# -- MEASUREMENT FUNCTIONS -----------------------------------------------------

def measure_lufs_stereo(audio, sr):
    """
    EBU R128 integrated LUFS - stereo measurement.
    Passes full stereo array to pyloudnorm (correct - do NOT downmix to mono).
    """
    if HAS_LN:
        try:
            meter = pyln.Meter(sr)
            return float(meter.integrated_loudness(audio))
        except Exception as e:
            pass
    # Fallback: stereo RMS
    rms = np.sqrt(np.mean(audio**2))
    return float(20 * np.log10(rms + 1e-12))

def measure_lufs_shortterm(audio, sr, window_s=3.0):
    """
    EBU R128 short-term LUFS - maximum over 3-second sliding windows.
    """
    if not HAS_LN:
        return None
    meter = pyln.Meter(sr)
    win  = int(window_s * sr)
    hop  = win // 2
    vals = []
    for i in range(0, len(audio) - win, hop):
        seg = audio[i:i+win]
        try:
            v = meter.integrated_loudness(seg)
            if not (np.isinf(v) or np.isnan(v)):
                vals.append(v)
        except Exception:
            pass
    return round(float(max(vals)), 2) if vals else None

def measure_lra(audio, sr):
    """
    Loudness Range (LRA) - EBU R128.
    Difference between 10th and 95th percentile of short-term LUFS distribution.
    """
    if not HAS_LN:
        return None
    meter = pyln.Meter(sr)
    win = int(3 * sr); hop = win // 2
    vals = []
    for i in range(0, len(audio) - win, hop):
        seg = audio[i:i+win]
        try:
            v = meter.integrated_loudness(seg)
            if not (np.isinf(v) or np.isnan(v)):
                vals.append(v)
        except Exception:
            pass
    if len(vals) < 4:
        return None
    return round(float(np.percentile(vals, 95) - np.percentile(vals, 10)), 2)

def measure_true_peak(audio):
    """
    True peak in dBTP (inter-sample peak).
    Uses 4x oversampling to detect inter-sample peaks.
    """
    from scipy.signal import resample_poly
    try:
        upsampled = resample_poly(audio, 4, 1)
        pk = np.max(np.abs(upsampled))
        return round(float(20 * np.log10(pk + 1e-12)), 3)
    except Exception:
        pk = np.max(np.abs(audio))
        return round(float(20 * np.log10(pk + 1e-12)), 3)

def spectral_bands(mono, sr):
    """
    Energy in defined frequency bands using Welch PSD.
    Returns values in dB relative to 1kHz band energy.
    """
    f, Pxx = welch(mono, sr, nperseg=min(8192, len(mono)//4),
                   noverlap=None, window='hann')
    def band_db(lo, hi):
        m = (f >= lo) & (f < hi)
        if not m.any():
            return -100.0
        return float(10 * np.log10(np.mean(Pxx[m]) + 1e-12))

    ref = band_db(800, 1200)
    return {
        "sub_20_40_Hz":        round(band_db(20,   40)    - ref, 2),
        "kick_40_80_Hz":       round(band_db(40,   80)    - ref, 2),
        "bass_80_160_Hz":      round(band_db(80,   160)   - ref, 2),
        "low_mid_160_300_Hz":  round(band_db(160,  300)   - ref, 2),
        "mid_300_800_Hz":      round(band_db(300,  800)   - ref, 2),
        "upper_800_2k_Hz":     round(band_db(800,  2000)  - ref, 2),
        "presence_2k_5k_Hz":   round(band_db(2000, 5000)  - ref, 2),
        "high_5k_10k_Hz":      round(band_db(5000, 10000) - ref, 2),
        "air_10k_20k_Hz":      round(band_db(10000,20000) - ref, 2),
        "reference_800_1200Hz_dBFS": round(ref, 2),
    }

def stereo_analysis(audio):
    """
    Stereo width, correlation, and sub-bass mono check.
    """
    if audio.shape[1] < 2:
        return {"width_ratio": 0.0, "correlation": 1.0, "sub_leak_ratio": 0.0}
    L, R = audio[:,0], audio[:,1]
    mid  = L + R
    side = L - R
    width = float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-9))
    corr  = float(np.corrcoef(L, R)[0,1])
    return {
        "width_ratio":   round(width, 4),
        "correlation":   round(corr, 4),
    }

def sub_mono_check(audio, sr):
    """
    Measures how much stereo content leaks below 120Hz.
    Good masters have essentially zero side energy in the sub.
    """
    if audio.shape[1] < 2:
        return 0.0
    lp = signal.butter(4, 120, btype='low', fs=sr, output='sos')
    sub_side = signal.sosfiltfilt(lp, audio[:,0] - audio[:,1])
    sub_mid  = signal.sosfiltfilt(lp, audio[:,0] + audio[:,1])
    ratio = float(np.sqrt(np.mean(sub_side**2)) /
                  (np.sqrt(np.mean(sub_mid**2)) + 1e-9))
    return round(ratio, 5)

def detect_bpm(mono, sr):
    if not HAS_LIBROSA:
        return None
    try:
        tempo, _ = librosa.beat.beat_track(
            y=mono.astype(np.float32), sr=sr, units='time')
        return round(float(np.atleast_1d(tempo)[0]), 2)
    except Exception:
        return None

def detect_key(mono, sr):
    if not HAS_LIBROSA:
        return None
    try:
        chroma = librosa.feature.chroma_cqt(
            y=mono.astype(np.float32), sr=sr).mean(axis=1)
        major  = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
        minor  = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        notes  = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        best_s, best_k, best_m = -np.inf, 0, 'major'
        for r in range(12):
            for prof, mode in [(major,'major'),(minor,'minor')]:
                sc = np.corrcoef(chroma, np.roll(prof,r))[0,1]
                if sc > best_s:
                    best_s, best_k, best_m = sc, r, mode
        return f"{notes[best_k]} {best_m} (conf {best_s:.2f})"
    except Exception:
        return None

def spectral_centroid(mono, sr):
    if not HAS_LIBROSA:
        return None
    try:
        c = librosa.feature.spectral_centroid(
            y=mono.astype(np.float32), sr=sr)
        return round(float(np.mean(c)), 1)
    except Exception:
        return None

# -- MAIN ANALYSIS LOOP --------------------------------------------------------

SEP = "=" * 72
results = []

print(f"\n{SEP}")
print("  INDEPENDENT REFERENCE TRACK ANALYSIS")
print(f"  Folder: {FOLDER}")
print(SEP)

for path in wavs:
    name = os.path.basename(path)
    print(f"\nAnalyzing: {name}")
    print("-" * 60)

    audio, sr = sf.read(path, always_2d=True)
    audio = audio.astype(np.float64)
    mono  = np.mean(audio, axis=1)
    n     = audio.shape[0]
    dur_s = n / sr
    nch   = audio.shape[1]

    print(f"  File info  : {sr}Hz  {nch}ch  {dur_s:.1f}s  "
          f"{sf.info(path).subtype}")

    # LUFS measurements
    lufs_int   = measure_lufs_stereo(audio, sr)
    lufs_short = measure_lufs_shortterm(audio, sr)
    lra        = measure_lra(audio, sr)
    true_pk    = measure_true_peak(audio)
    plr        = round(true_pk - lufs_int, 2)

    # Peak and RMS
    sample_pk  = round(float(20*np.log10(np.max(np.abs(audio))+1e-12)), 3)
    rms_db     = round(float(20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)), 3)
    crest      = round(true_pk - rms_db, 2)

    print(f"  LUFS (integrated stereo EBU R128) : {lufs_int:.2f} LUFS")
    print(f"  LUFS (short-term max 3s window)   : "
          f"{lufs_short:.2f} LUFS" if lufs_short else "  LUFS short-term : N/A")
    print(f"  Loudness range (LRA)               : "
          f"{lra:.2f} dB" if lra else "  LRA : N/A")
    print(f"  True peak (4x oversampled)         : {true_pk:.3f} dBTP")
    print(f"  Sample peak                        : {sample_pk:.3f} dBFS")
    print(f"  RMS level                          : {rms_db:.3f} dBFS")
    print(f"  Crest factor (TruePeak - RMS)      : {crest:.2f} dB")
    print(f"  PLR (TruePeak - IntLUFS)           : {plr:.2f} dB")

    # Stereo
    st  = stereo_analysis(audio)
    sub = sub_mono_check(audio, sr)
    print(f"  Stereo width ratio                 : {st['width_ratio']:.4f}")
    print(f"  Stereo correlation (L/R)           : {st['correlation']:.4f}")
    print(f"  Sub-bass mono tightness (<120Hz)   : {sub:.5f} "
          f"({'excellent' if sub<0.03 else 'good' if sub<0.06 else 'review'})")

    # Spectral
    bands = spectral_bands(mono, sr)
    print("  Spectral balance (rel 800-1200Hz reference):")
    for bname, bval in bands.items():
        if bname == "reference_800_1200Hz_dBFS":
            print(f"    Reference level (800-1200Hz)   : {bval:.2f} dBFS")
        else:
            bar = "+" * max(0, int(bval/2)) if bval > 0 else "-" * max(0, int(-bval/2))
            print(f"    {bname:<30}: {bval:>+7.2f} dB  {bar}")

    # Rhythm and tonality
    bpm = detect_bpm(mono, sr)
    key = detect_key(mono, sr)
    cen = spectral_centroid(mono, sr)
    if bpm: print(f"  BPM (beat tracking)                : {bpm}")
    if key: print(f"  Key (Krumhansl-Schmuckler)         : {key}")
    if cen: print(f"  Spectral centroid (brightness)     : {cen:.0f} Hz")

    r = {
        "file": name,
        "duration_s": round(dur_s, 1),
        "sample_rate": sr,
        "channels": nch,
        "lufs_integrated": lufs_int,
        "lufs_shortterm_max": lufs_short,
        "lra_db": lra,
        "true_peak_dbtp": true_pk,
        "sample_peak_dbfs": sample_pk,
        "rms_dbfs": rms_db,
        "crest_factor_db": crest,
        "plr_db": plr,
        "stereo_width": st['width_ratio'],
        "stereo_correlation": st['correlation'],
        "sub_mono_tightness": sub,
        "bpm": bpm,
        "key": key,
        "spectral_centroid_hz": cen,
        "spectral_bands_rel_1kHz": bands,
    }
    results.append(r)

# -- AVERAGES -----------------------------------------------------------------

print(f"\n{SEP}")
print("  AVERAGED PROFILE ACROSS ALL TRACKS")
print(SEP)

scalar_keys = ["lufs_integrated","true_peak_dbtp","crest_factor_db","plr_db",
               "stereo_width","stereo_correlation","sub_mono_tightness",
               "spectral_centroid_hz"]
for k in scalar_keys:
    vals = [r[k] for r in results if r.get(k) is not None]
    if vals:
        print(f"  {k:<35}: {np.mean(vals):.4f}")

lra_vals = [r['lra_db'] for r in results if r.get('lra_db') is not None]
if lra_vals:
    print(f"  {'lra_db':<35}: {np.mean(lra_vals):.4f}")

print("\n  Spectral bands average (rel 800-1200Hz):")
band_names = list(results[0]['spectral_bands_rel_1kHz'].keys())
for b in band_names:
    if b == "reference_800_1200Hz_dBFS":
        continue
    vals = [r['spectral_bands_rel_1kHz'][b] for r in results]
    print(f"    {b:<35}: {np.mean(vals):>+7.2f} dB")

# -- SAVE JSON -----------------------------------------------------------------

out_path = os.path.join(FOLDER, "independent_analysis_report.json")
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({"tracks": results,
               "note": "Independent analysis - stereo EBU R128 LUFS"}, f, indent=2)
print(f"\n  Full report saved: {out_path}")
print(f"\n{SEP}")
print("  ANALYSIS COMPLETE")
print(SEP)