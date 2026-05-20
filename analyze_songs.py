"""
SunoMaster - Song Analyzer
==========================
Analyzes all songs in E:\SunoMaster\releases (one WAV per subfolder).
Uses identical measurements as the professional reference analysis.
Paste the full output back to Claude for comparison.
"""

import os, sys, json, warnings
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.signal import resample_poly, welch

try:
    import librosa; HAS_LIB = True
except ImportError: HAS_LIB = False; print("[WARN] librosa not found")

try:
    import pyloudnorm as pyln; HAS_LN = True
    print("[OK]  pyloudnorm active - stereo EBU R128 LUFS")
except ImportError:
    HAS_LN = False; print("[WARN] pyloudnorm not found - RMS approximation used")

RELEASES = r"E:\SunoMaster\releases"

if not os.path.exists(RELEASES):
    print(f"ERROR: {RELEASES} not found"); sys.exit(1)

songs = []
for entry in sorted(os.scandir(RELEASES), key=lambda e: e.name):
    if not entry.is_dir(): continue
    wavs = sorted([f for f in os.listdir(entry.path) if f.lower().endswith('.wav')])
    if not wavs: continue
    chosen = next((w for w in wavs if 'original' in w.lower()), wavs[0])
    songs.append((entry.name, os.path.join(entry.path, chosen)))

if not songs:
    print("No WAV files found in subfolders."); sys.exit(1)

print(f"\nFound {len(songs)} songs:")
for n, p in songs: print(f"  {n}")

# Reference averages (confirmed from Python independent analysis of 6 pro tracks)
REF = {
    "lufs": -8.119, "true_peak": 0.063, "crest": 8.975,
    "plr": 8.182, "lra": 4.657, "width": 0.1865,
    "correlation": 0.9288, "sub_leak": 0.0317,
    "bands": {
        "sub_20_40":       14.18,  "kick_40_80":      26.70,
        "bass_80_160":     17.13,  "low_mid_160_300": 11.32,
        "mid_300_800":      5.96,  "upper_800_2k":    -1.63,
        "presence_2k_5k":  -6.61, "high_5k_10k":     -9.72,
        "air_10k_20k":    -18.19,
    }
}

def lufs_stereo(audio, sr):
    if HAS_LN:
        try: return float(pyln.Meter(sr).integrated_loudness(audio))
        except Exception: pass
    return float(20*np.log10(np.sqrt(np.mean(audio**2))+1e-12))

def lufs_shortterm(audio, sr):
    if not HAS_LN: return None
    m = pyln.Meter(sr); win = int(3*sr); vals = []
    for i in range(0, len(audio)-win, win//2):
        try:
            v = m.integrated_loudness(audio[i:i+win])
            if not (np.isinf(v) or np.isnan(v)): vals.append(v)
        except: pass
    return round(float(max(vals)), 2) if vals else None

def lra_measure(audio, sr):
    if not HAS_LN: return None
    m = pyln.Meter(sr); win = int(3*sr); vals = []
    for i in range(0, len(audio)-win, win//2):
        try:
            v = m.integrated_loudness(audio[i:i+win])
            if not (np.isinf(v) or np.isnan(v)): vals.append(v)
        except: pass
    if len(vals) < 4: return None
    return round(float(np.percentile(vals,95)-np.percentile(vals,10)), 2)

def true_peak(audio):
    try:
        up = resample_poly(audio, 4, 1)
        return round(float(20*np.log10(np.max(np.abs(up))+1e-12)), 3)
    except:
        return round(float(20*np.log10(np.max(np.abs(audio))+1e-12)), 3)

def be(f, P, lo, hi):
    m = (f>=lo)&(f<hi)
    return float(10*np.log10(np.mean(P[m])+1e-12)) if m.any() else -100.0

def spectral_bands(mono, sr):
    f, P = welch(mono, sr, nperseg=min(8192, len(mono)//4), window='hann')
    ref  = be(f,P,800,1200)
    return {
        "sub_20_40":       round(be(f,P,20,40)    -ref, 2),
        "kick_40_80":      round(be(f,P,40,80)    -ref, 2),
        "bass_80_160":     round(be(f,P,80,160)   -ref, 2),
        "low_mid_160_300": round(be(f,P,160,300)  -ref, 2),
        "mid_300_800":     round(be(f,P,300,800)  -ref, 2),
        "upper_800_2k":    round(be(f,P,800,2000) -ref, 2),
        "presence_2k_5k":  round(be(f,P,2000,5000)-ref, 2),
        "high_5k_10k":     round(be(f,P,5000,10000)-ref,2),
        "air_10k_20k":     round(be(f,P,10000,20000)-ref,2),
        "ref_level_dBFS":  round(ref, 2),
    }

def infrasonic(mono, sr):
    f, P = welch(mono, sr, nperseg=min(8192, len(mono)//4))
    return round(be(f,P,5,30) - be(f,P,800,1200), 1)

def ultrasonic(mono, sr):
    f, P = welch(mono, sr, nperseg=min(8192, len(mono)//4))
    hi   = min(20000, sr//2-100)
    return round(be(f,P,16000,hi) - be(f,P,800,1200), 1)

def stereo_info(audio):
    if audio.shape[1] < 2: return 0.0, 1.0
    m = audio[:,0]+audio[:,1]; s = audio[:,0]-audio[:,1]
    w = float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-9))
    c = float(np.corrcoef(audio[:,0],audio[:,1])[0,1])
    return round(w,4), round(c,4)

def sub_leak(audio, sr):
    if audio.shape[1] < 2: return 0.0
    lp   = signal.butter(4,120,btype='low',fs=sr,output='sos')
    side = signal.sosfiltfilt(lp, audio[:,0]-audio[:,1])
    mid  = signal.sosfiltfilt(lp, audio[:,0]+audio[:,1])
    return round(float(np.sqrt(np.mean(side**2))/(np.sqrt(np.mean(mid**2))+1e-9)),5)

def find_active(audio, sr):
    win = int(0.5*sr); thr = 10**(-40/20)
    mono = np.mean(audio,axis=1)
    for i in range(0,len(mono)-win,win//2):
        if np.sqrt(np.mean(mono[i:i+win]**2)) > thr: return i
    return 0

def detect_bpm(mono, sr):
    if not HAS_LIB: return None
    try:
        bp  = signal.butter(4,[40,min(4000,sr//2-100)],btype='band',fs=sr,output='sos')
        mbp = signal.sosfiltfilt(bp, mono.astype(np.float32))
        t,_ = librosa.beat.beat_track(y=mbp.astype(np.float32),sr=sr,units='time')
        return round(float(np.atleast_1d(t)[0]),2)
    except: return None

def detect_key(mono, sr):
    if not HAS_LIB: return None
    try:
        ch  = librosa.feature.chroma_cqt(y=mono.astype(np.float32),sr=sr).mean(axis=1)
        maj = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
        mn  = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        nts = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        bs,bk,bm = -np.inf,0,'major'
        for r in range(12):
            for p,md in [(maj,'major'),(mn,'minor')]:
                sc = np.corrcoef(ch,np.roll(p,r))[0,1]
                if sc>bs: bs,bk,bm=sc,r,md
        return f"{nts[bk]} {bm} (conf {bs:.2f})"
    except: return None

def spectral_centroid(mono, sr):
    if not HAS_LIB: return None
    try: return round(float(np.mean(librosa.feature.spectral_centroid(
            y=mono.astype(np.float32),sr=sr))),0)
    except: return None

def d(val, ref, unit=""):
    diff = val - ref
    arrow = "+" if diff > 0.05 else ("-" if diff < -0.05 else "=")
    return f"{val:>8.2f}  ref={ref:>7.2f}  {arrow}{abs(diff):.2f}{unit}"

SEP = "=" * 72
all_results = []

print(f"\n{SEP}")
print("  AGENT WALL - SONG ANALYSIS vs PROFESSIONAL REFERENCE AVERAGE")
print(f"{SEP}")

for folder_name, wav_path in songs:
    print(f"\n{'=' * 72}")
    print(f"  Song    : {folder_name}")
    print(f"  File    : {os.path.basename(wav_path)}")
    print("=" * 72)

    try:
        audio, sr = sf.read(wav_path, always_2d=True)
        audio = audio.astype(np.float64)
        mono  = np.mean(audio, axis=1)
        n     = audio.shape[0]; dur = n/sr
        info  = sf.info(wav_path)
        print(f"  Format          : {sr}Hz  {audio.shape[1]}ch  {dur:.1f}s  {info.subtype}")

        active = find_active(audio, sr)
        print(f"  Active section  : starts at {active/sr:.1f}s", end="")
        print("  [SILENT INTRO DETECTED]" if active > sr*3 else "")

        # Loudness
        li  = lufs_stereo(audio, sr)
        lst = lufs_shortterm(audio, sr)
        llr = lra_measure(audio, sr)
        tp  = true_peak(audio)
        sp  = round(float(20*np.log10(np.max(np.abs(audio))+1e-12)),3)
        rms = round(float(20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)),3)
        cr  = round(tp-rms, 2)
        pl  = round(tp-li, 2)

        print(f"\n  --- LOUDNESS ---")
        print(f"  LUFS integrated (stereo EBU R128) : {d(li,  REF['lufs'])}")
        print(f"  LUFS short-term max (3s)          : {lst:.2f}" if lst else "  LUFS short-term  : N/A")
        print(f"  Loudness range LRA                : {d(llr, REF['lra'], 'dB')}" if llr else "  LRA              : N/A")
        print(f"  True peak (4x oversampled)        : {d(tp,  REF['true_peak'], 'dBTP')}")
        print(f"  Sample peak                       : {sp:.3f} dBFS")
        print(f"  RMS level                         : {rms:.3f} dBFS")
        print(f"  Crest factor (TruePeak - RMS)     : {d(cr,  REF['crest'], 'dB')}")
        print(f"  PLR (TruePeak - IntLUFS)          : {d(pl,  REF['plr'],   'dB')}")

        # AI forensic checks
        inf = infrasonic(mono, sr)
        ult = ultrasonic(mono, sr)
        print(f"\n  --- AI FORENSIC ---")
        print(f"  Infrasonic excess (sub-30Hz rel 1kHz) : {inf:+.1f} dB", end="")
        print("  [ELEVATED - AI artefact likely]" if inf > -10 else "  [OK]")
        print(f"  Ultrasonic (16-20kHz rel 1kHz)        : {ult:+.1f} dB", end="")
        print("  [ELEVATED - codec wall possible]" if ult > -25 else "  [OK]")

        # Stereo
        w, c = stereo_info(audio)
        sl   = sub_leak(audio, sr)
        print(f"\n  --- STEREO ---")
        print(f"  Width ratio                       : {d(w,  REF['width'])}")
        print(f"  Correlation (L/R)                 : {d(c,  REF['correlation'])}")
        sl_tag = 'excellent' if sl<0.03 else 'good' if sl<0.06 else 'REVIEW'
        print(f"  Sub mono tightness (<120Hz)       : {sl:.5f}  [{sl_tag}]  ref={REF['sub_leak']:.4f}")

        # Spectral
        bands = spectral_bands(mono, sr)
        print(f"\n  --- SPECTRAL BALANCE (rel 800-1200Hz) ---")
        bnames = ["sub_20_40","kick_40_80","bass_80_160","low_mid_160_300","mid_300_800",
                  "upper_800_2k","presence_2k_5k","high_5k_10k","air_10k_20k"]
        blabels= ["Sub  20-40 Hz ","Kick 40-80 Hz ","Bass 80-160Hz ",
                  "LMid 160-300Hz","Mid  300-800Hz","Upper 800-2kHz",
                  "Pres 2k-5kHz  ","High 5k-10kHz ","Air  10k-20kHz"]
        for bk, bl in zip(bnames, blabels):
            val = bands[bk]; ref_v = REF["bands"][bk]
            diff_v = val-ref_v
            bar_s  = "+" * max(0,int(val/2)) if val>0 else "-"*max(0,int(-val/2))
            arrow  = "^" if diff_v>1.5 else ("v" if diff_v<-1.5 else "=")
            print(f"    {bl}: {val:>+7.2f} dB  {arrow}{abs(diff_v):.1f}  ref={ref_v:>+6.2f}  {bar_s}")
        print(f"    Reference level (800-1200Hz)    : {bands['ref_level_dBFS']:.2f} dBFS")

        # Rhythm
        bpm = detect_bpm(mono, sr)
        key = detect_key(mono, sr)
        cen = spectral_centroid(mono, sr)
        print(f"\n  --- RHYTHM & TONALITY ---")
        if bpm: print(f"  BPM   : {bpm}")
        if key: print(f"  Key   : {key}")
        if cen: print(f"  Spectral centroid (brightness) : {cen:.0f} Hz  (ref avg 2947 Hz)")

        all_results.append({
            "song": folder_name, "lufs": round(li,2), "true_peak": tp,
            "crest": cr, "plr": pl, "lra": llr, "width": w, "correlation": c,
            "sub_leak": sl, "infrasonic_excess": inf, "ultrasonic": ult,
            "bpm": bpm, "key": key, "bands": {k:bands[k] for k in bnames}
        })

    except Exception as e:
        print(f"  ERROR: {e}")

# Summary comparison table
print(f"\n{SEP}")
print("  SUMMARY: YOUR SONGS vs PROFESSIONAL REFERENCE AVERAGE")
print(SEP)
print(f"  {'Song':<40} {'LUFS':>6}  {'Peak':>6}  {'Crest':>6}  {'PLR':>6}  {'Corr':>6}")
print(f"  {'(Reference average)':<40} {REF['lufs']:>6.1f}  {REF['true_peak']:>6.2f}  {REF['crest']:>6.2f}  {REF['plr']:>6.2f}  {REF['correlation']:>6.3f}")
print("  " + "-"*68)
for r in all_results:
    name = r['song'][:40]
    print(f"  {name:<40} {r['lufs']:>6.1f}  {r['true_peak']:>6.2f}  {r['crest']:>6.2f}  {r['plr']:>6.2f}  {r['correlation']:>6.3f}")

print(f"\n  {'Song':<40} {'Width':>7}  {'Kick dB':>8}  {'Air dB':>8}  {'InfraExc':>9}")
print(f"  {'(Reference average)':<40} {REF['width']:>7.4f}  {REF['bands']['kick_40_80']:>+8.2f}  {REF['bands']['air_10k_20k']:>+8.2f}  {'N/A':>9}")
print("  " + "-"*68)
for r in all_results:
    name = r['song'][:40]
    print(f"  {name:<40} {r['width']:>7.4f}  {r['bands']['kick_40_80']:>+8.2f}  {r['bands']['air_10k_20k']:>+8.2f}  {r['infrasonic_excess']:>+9.1f}")

# Save JSON
out_path = os.path.join(RELEASES, "song_analysis_report.json")
with open(out_path,'w',encoding='utf-8') as f:
    json.dump({"songs":all_results,"reference_average":REF},f,indent=2)
print(f"\n  Full report saved: {out_path}")
print(f"\n{SEP}")
print("  ANALYSIS COMPLETE - paste this full output back to Claude")
print(SEP)