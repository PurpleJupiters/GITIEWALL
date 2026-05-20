"""
================================================================================
SunoMaster v5.0  -  Professional Audio Production Pipeline
================================================================================
Reconciled from two development sessions. All QA findings incorporated.

Three-Phase Release Plan:
  Phase A  Clean Suno stems -> SoundCloud masters  (this script)
  Phase B  Re-split masters -> MIDI -> Ableton hardware reconstruction
  Phase C  Hardware-recorded versions -> Major label submission

DESIGN CONTRACT (absolute rules - never broken):
  - No pitch changes. No song structure changes.
  - Timing changes only via 128-subdivision slip-quantization (P1).
  - All outputs match original mix duration exactly (pad/trim with silence).
  - Max 2 dB corrective EQ per band.
  - Max 3 dB GR per compressor stage.
  - PLR never forced below 6 dB.
  - ZERO hard clipping above 0 dBFS at any stage.
  - Only even-harmonic (non-destructive) saturation.
  - AI resonance notching on individual stems ONLY - NEVER on full mix.
  - Sub below 100 Hz always mono across all pipelines.
  - Stereo correlation must remain > 0.5 (> 0.7 preferred).
  - All EQ uses sosfiltfilt (zero-phase). Dynamics use sosfilt (causal).
  - ONE soft-clip pass only in P3. No iterations.
  - Export: 24-bit WAV, original sample rate, dither OFF, normalize OFF.

PIPELINES:
  P0  AI Removal     LP@18kHz, HP@18Hz, infrasonic scan, metadata strip
  P1  Stem Cleaning  Noise gate, AI resonance removal, console strip
  P2  Mixing         Kick sidechain, gain stage, EQ, compress, -6dBFS
  P3  Mastering      Genre LUFS, M/S widen, ONE soft-clip, -2dBTP
  P4  MIDI/Ableton   Key, drums, melodic MIDI, automation, .als project
  P5  Final Cleanup  Metadata strip + AI scan on all output files

MASTERING TARGETS (confirmed from 6 professional reference tracks):
  Integrated LUFS  -8.0 LUFS (underground electronic default)
  True peak        -2.0 dBTP (2 dB headroom for mastering engineer)
  PLR              6-9 dB
  Crest factor     > 8.9 dB (reference average)
  LRA              4-7 dB

REFERENCE SPECTRAL PROFILE (confirmed by two independent analyses):
  Sub  20-40 Hz    +14.18 dB rel 1kHz
  Kick 40-80 Hz    +26.70 dB rel 1kHz  <-- dominant region
  Bass 80-160 Hz   +17.13 dB rel 1kHz
  LMid 160-300 Hz  +11.32 dB rel 1kHz
  Pres 2-5 kHz     - 6.61 dB rel 1kHz
  High 5-10 kHz    - 9.72 dB rel 1kHz
  Air  10-20 kHz   -18.19 dB rel 1kHz

ABLETON LIVE 12 (P4):
  Routing   tracks -> bus -> PREMIX -> Master
  Colors    Kick/Bass=black, Drums=red, Vocals=yellow, Synths=purple,
            Guitar=orange, Piano=blue, FX=maroon, PREMIX=light-grey
  Buses     LOWEND, DRUMS, VOCALS, SYNTHS, GUITAR, PIANO, FX
  Returns   SHORT REVERB, LONG REVERB, SHORT DELAY, LONG DELAY
  Master    LEVELS by Mastering the Mix
================================================================================
"""

import os, sys, json, time, shutil, warnings, subprocess, webbrowser, gzip
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.interpolate import interp1d, CubicSpline
import librosa
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    import pyloudnorm as pyln;  HAS_LN  = True
except ImportError:             HAS_LN  = False
try:
    from mutagen.id3 import ID3; HAS_MUT = True
except ImportError:              HAS_MUT = False
try:
    import requests;             HAS_REQ = True
except ImportError:              HAS_REQ = False
try:
    import pretty_midi;          HAS_PM  = True
except ImportError:              HAS_PM  = False


# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

VERSION        = "5.0"
TRUE_PEAK_DB   = -2.0       # 2 dB headroom for mastering engineer
MIN_PLR        = 6.0
MAX_PLR        = 9.0
MIX_CEILING_DB = -6.0       # P2 output ceiling
MAX_EQ_DB      = 2.0        # max per-band EQ correction
MAX_GR_DB      = 3.0        # max compressor gain reduction
GRID_DIV       = 128        # beat quantization subdivisions
CF_LEN         = 256        # crossfade length for quantize edits (samples)
NORM_REF_SUBDIR = "normalized reference tracks"

# Genre-aware LUFS targets (from other chat spec)
GENRE_LUFS = {
    "techno":               -7.5,
    "underground":          -8.0,   # default
    "house":                -8.0,
    "deep_house":           -9.0,
    "progressive":          -9.5,
    "melodic":              -10.0,
    "ambient":              -20.0,
}

# Genre minimum crest factors
GENRE_CREST_MIN = {
    "techno": 7.5, "underground": 8.0, "house": 8.0,
    "deep_house": 8.5, "progressive": 8.5, "melodic": 9.0, "ambient": 12.0,
}

# Virtual Analog Console assignment per stem
CONSOLE_MAP = {
    "bass":   "SSL",    # tight, punchy, even harmonics
    "drums":  "SSL",    # tight, punchy
    "guitar": "API",    # presence, 2nd/3rd harmonics
    "piano":  "Neve",   # warm, silky
    "vocals": "Neve",   # warm, silky
    "other":  "Neve",   # warm, silky
    "kick":   "SSL",
}

# AI fingerprint
FP_FMIN, FP_FMAX, FP_BINS, FP_DWIN = 5000, 16000, 128, 18

# Ableton color palette
ALS_COLOR  = {"black":1,"red":14,"yellow":5,"purple":25,"orange":9,"blue":20,"maroon":13,"light_grey":18}
STEM_COLOR = {"kick":"black","bass":"black","drums":"red","vocals":"yellow","other":"purple","guitar":"orange","piano":"blue","fx":"maroon"}
BUS_COLOR  = {"LOWEND":"black","DRUMS":"red","VOCALS":"yellow","SYNTHS":"purple","GUITAR":"orange","PIANO":"blue","FX":"maroon","PREMIX":"light_grey"}
BUS_MEMBERS= {"LOWEND":["kick","bass"],"DRUMS":["drums"],"VOCALS":["vocals"],"SYNTHS":["other"],"GUITAR":["guitar"],"PIANO":["piano"],"FX":[]}
STEM_VOL   = {"kick":0.90,"drums":0.75,"bass":0.85,"vocals":0.80,"guitar":0.65,"piano":0.65,"other":0.70,"fx":0.55}
STEM_PAN   = {"kick":0.0,"bass":0.0,"drums":0.0,"vocals":0.0,"guitar":0.15,"piano":-0.15,"other":0.0,"fx":0.0}


# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

_LOG = []

def log(msg, level="INFO"):
    line = f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}"
    print(line); _LOG.append(line)

def save_log(path):
    with open(path, 'w', encoding='utf-8') as f: f.write('\n'.join(_LOG))

def section(title=""):
    bar = "=" * 66
    if title: log(bar); log(f"  {title}"); log(bar)
    else:     log(bar)

def _report(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=2)


# -----------------------------------------------------------------------------
# PATH CONFIGURATION
# -----------------------------------------------------------------------------

def select_computer(args):
    if args.computer == "2":
        return f"{args.drive.upper()}:\\", "HP ZBook"
    return "E:\\", "Lenovo ThinkStation"

def build_paths(root):
    sm = os.path.join(root, "SunoMaster")
    p  = {"root": sm}
    for n in ("releases","collection","references","scripts","downloads","backup","shortened","output"):
        p[n] = os.path.join(sm, n)
    return p

def ensure_root(paths):
    for p in paths.values(): os.makedirs(p, exist_ok=True)

def create_song_folders(base):
    for sub in [
        "P0_DETECTION/cleaned","P0_DETECTION/detection_reports","P0_DETECTION/shortened",
        "P1_STEMCLEANING/stems_raw","P1_STEMCLEANING/stems_cleaned",
        "P1_STEMCLEANING/phase_reports","P1_STEMCLEANING/alignment_reports",
        "P2_MIXING/pre_master","P2_MIXING/stems_processed",
        "P2_MIXING/mono_check","P2_MIXING/mix_reports",
        "P3_MASTERING/final_master","P3_MASTERING/streaming",
        "P3_MASTERING/shortened","P3_MASTERING/mastering_reports",
        "P4_MIDI/midi_stems","P4_MIDI/automation_lanes",
        "P4_MIDI/ableton/samples/stems","P4_MIDI/ableton/samples/master",
        "P4_MIDI/midi_reports",
    ]:
        os.makedirs(os.path.join(base, sub), exist_ok=True)

def find_wav(folder):
    wavs = [f for f in os.listdir(folder) if f.lower().endswith('.wav')]
    for w in wavs:
        if 'original' in w.lower(): return os.path.join(folder, w)
    return os.path.join(folder, wavs[0]) if wavs else None


# -----------------------------------------------------------------------------
# REFERENCE PROFILE
# -----------------------------------------------------------------------------

def load_or_build_profile(ref_dir):
    path = os.path.join(ref_dir, "reference_profile.json")
    if os.path.exists(path):
        try:
            with open(path) as f: data = json.load(f)
            log(f"Reference profile loaded: {path}")
            return data.get("average", data)
        except Exception as e: log(f"Could not read profile: {e}", "WARN")
    norm_dir = os.path.join(ref_dir, NORM_REF_SUBDIR)
    search   = norm_dir if os.path.exists(norm_dir) else ref_dir
    wavs     = [os.path.join(search, f) for f in os.listdir(search) if f.lower().endswith('.wav')]
    if wavs:
        log(f"Building profile from {len(wavs)} reference tracks...")
        results = []
        for wav in wavs:
            try:
                audio, sr = sf.read(wav, always_2d=True)
                results.append(_analyze_ref(os.path.basename(wav), audio.astype(np.float64), sr))
                log(f"  Analyzed: {os.path.basename(wav)}")
            except Exception as e: log(f"  Skipped {os.path.basename(wav)}: {e}", "WARN")
        if results:
            avg = {
                "lufs_integrated":   round(float(np.mean([r["lufs"] for r in results])), 2),
                "crest_factor_db":   round(float(np.mean([r["crest"] for r in results])), 2),
                "stereo_width":      round(float(np.mean([r["width"] for r in results])), 3),
                "stereo_correlation":round(float(np.mean([r["corr"]  for r in results])), 3),
                "spectral_bands_rel_1kHz": {
                    k: round(float(np.mean([r["bands"][k] for r in results])), 2)
                    for k in results[0]["bands"]
                }
            }
            try:
                with open(path, 'w') as f: json.dump({"tracks":results,"average":avg}, f, indent=2)
                log(f"Profile saved: {path}")
            except Exception: pass
            return avg
    log("Using built-in underground electronic profile.", "WARN")
    return {"spectral_bands_rel_1kHz":{
        "sub_20_40":14.18,"kick_40_80":26.70,"bass_80_160":17.13,
        "low_mid_160_300":11.32,"mid_300_800":5.96,"upper_800_2k":-1.63,
        "presence_2k_5k":-6.61,"high_5k_10k":-9.72,"air_10k_20k":-18.19}}

def _be(f, P, lo, hi):
    m = (f>=lo)&(f<hi); return float(10*np.log10(np.mean(P[m])+1e-12)) if m.any() else -100.0

def _analyze_ref(name, audio, sr):
    mono  = np.mean(audio, axis=1)
    lufs  = _lufs(audio, sr)
    pk    = 20*np.log10(np.max(np.abs(audio))+1e-12)
    rms   = 20*np.log10(np.sqrt(np.mean(mono**2))+1e-12)
    w,c   = 0.0, 1.0
    if audio.shape[1] >= 2:
        m  = audio[:,0]+audio[:,1]; s = audio[:,0]-audio[:,1]
        w  = float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-9))
        c  = float(np.corrcoef(audio[:,0],audio[:,1])[0,1])
    f_w, P = signal.welch(mono, sr, nperseg=8192, noverlap=4096)
    r1k    = _be(f_w, P, 800, 1200)
    bands  = {
        "sub_20_40":        round(_be(f_w,P,20,40)   -r1k, 2),
        "kick_40_80":       round(_be(f_w,P,40,80)   -r1k, 2),
        "bass_80_160":      round(_be(f_w,P,80,160)  -r1k, 2),
        "low_mid_160_300":  round(_be(f_w,P,160,300) -r1k, 2),
        "mid_300_800":      round(_be(f_w,P,300,800) -r1k, 2),
        "upper_800_2k":     round(_be(f_w,P,800,2000)-r1k, 2),
        "presence_2k_5k":   round(_be(f_w,P,2000,5000)-r1k,2),
        "high_5k_10k":      round(_be(f_w,P,5000,10000)-r1k,2),
        "air_10k_20k":      round(_be(f_w,P,10000,20000)-r1k,2),
    }
    return {"name":name,"lufs":round(lufs,2),"crest":round(pk-rms,2),
            "width":round(w,3),"corr":round(c,3),"bands":bands}


# -----------------------------------------------------------------------------
# AUDIO I/O AND UTILITIES
# -----------------------------------------------------------------------------

def load(path):
    a, sr = sf.read(path, always_2d=True)
    return a.astype(np.float64), sr, sf.info(path)

def save(audio, sr, path, ref_info=None):
    sub = 'PCM_16' if (ref_info and 'PCM_16' in ref_info.subtype) else 'PCM_24'
    sf.write(path, audio, sr, subtype=sub)

def safe_save(audio, sr, path, ref_info=None, label=""):
    """Final clip check before disk write. Strips metadata afterwards."""
    pk = 20*np.log10(np.max(np.abs(audio))+1e-12)
    if pk > TRUE_PEAK_DB:
        log(f"  Pre-save guard [{label}]: {pk:.2f}dBFS corrected.", "WARN")
        audio = peak_guard(audio, 10**(TRUE_PEAK_DB/20.0), label)
    else:
        log(f"  [{label}] peak {pk:.2f}dBFS clean.")
    save(audio, sr, path, ref_info)
    if HAS_MUT:
        try: ID3(path).delete()
        except Exception: pass

def fit(audio, n):
    if audio.shape[0] == n: return audio
    if audio.shape[0] >  n: return audio[:n]
    return np.vstack([audio, np.zeros((n-audio.shape[0], audio.shape[1]))])

def to_mono(a): return np.mean(a, axis=1) if a.ndim > 1 else a

def as_stereo(a):
    if a.ndim == 1: return np.column_stack([a, a])
    if a.shape[1] == 1: return np.column_stack([a[:,0], a[:,0]])
    return a

def peak_guard(audio, ceiling=0.9998, label=""):
    """Hard clip prevention after every stage. Logs when it fires."""
    pk = np.max(np.abs(audio))
    if pk > ceiling:
        g = ceiling / pk
        log(f"  Clip guard [{label}]: {20*np.log10(pk+1e-12):.2f}dBFS -> {20*np.log10(g):.2f}dB", "WARN")
        return audio * g
    return audio

def rms_gain(audio, target_db=-18.0):
    rms = np.sqrt(np.mean(audio**2))
    return audio if rms < 1e-9 else audio * (10**(target_db/20.0) / rms)

def save_quarter(audio, sr, path, ref_info=None):
    save(audio[:audio.shape[0]//4], sr, path, ref_info)

def _lufs(audio, sr):
    """
    Correct EBU R128 integrated LUFS.
    Passes STEREO array directly - never downmix to mono first.
    Mono downmix causes ~3dB under-reading.
    """
    if HAS_LN:
        try: return float(pyln.Meter(sr).integrated_loudness(audio))
        except Exception: pass
    mono = to_mono(audio)
    return float(20*np.log10(np.sqrt(np.mean(mono**2))+1e-12))

def measure_lufs(audio, sr): return _lufs(audio, sr)

def measure_plr(audio, sr):
    lufs = measure_lufs(audio, sr)
    pk   = 20*np.log10(np.max(np.abs(audio))+1e-12)
    return round(pk-lufs, 2), round(lufs, 2), round(pk, 2)

def check_correlation(audio, label=""):
    """Enforce stereo correlation > 0.5. Log warning if violated."""
    if audio.shape[1] < 2: return audio
    corr = float(np.corrcoef(audio[:,0], audio[:,1])[0,1])
    if corr < 0.5:
        log(f"  Correlation {corr:.3f} < 0.5 [{label}] - check stereo field.", "WARN")
    elif corr < 0.7:
        log(f"  Correlation {corr:.3f} < 0.7 [{label}] - borderline.", "INFO")
    return audio

def find_active_section(audio, sr, window_s=0.5, threshold_db=-40.0):
    """
    Find first non-silent section. Used for polarity/BPM detection.
    Avoids using silent intro which corrupts beat tracking.
    Returns start sample index.
    """
    win   = int(window_s * sr)
    thr   = 10**(threshold_db/20.0)
    mono  = to_mono(audio)
    for i in range(0, len(mono)-win, win//2):
        if np.sqrt(np.mean(mono[i:i+win]**2)) > thr:
            return i
    return 0

def avg_spectrum(audio, sr, win=4096, hop=1024):
    f, _, Z = signal.stft(to_mono(audio).astype(np.float32),
                          fs=sr, nperseg=win, noverlap=win-hop, window='hann')
    return f, np.mean(np.abs(Z), axis=1)


# -----------------------------------------------------------------------------
# DSP BUILDING BLOCKS
# ALL EQ uses sosfiltfilt (zero-phase). Dynamics use sosfilt (causal).
# -----------------------------------------------------------------------------

def peaking_sos(hz, db, Q, sr):
    db = np.clip(db, -MAX_EQ_DB, MAX_EQ_DB); A = 10**(db/40.0)
    w0 = 2*np.pi*hz/sr; alp = np.sin(w0)/(2.0*Q)
    b0=1+alp*A; b1=-2*np.cos(w0); b2=1-alp*A
    a0=1+alp/A; a1=-2*np.cos(w0); a2=1-alp/A
    return np.array([[b0/a0,b1/a0,b2/a0,1.0,a1/a0,a2/a0]])

def apply_eq(audio, cuts, sr):
    """Zero-phase EQ using sosfiltfilt. cuts = [(hz, db, Q), ...]"""
    out = audio.copy()
    for hz, db, Q in cuts:
        if hz <= 0 or hz >= sr//2-100: continue
        sos = peaking_sos(hz, db, Q, sr)
        for ch in range(out.shape[1]):
            out[:,ch] = signal.sosfiltfilt(sos, out[:,ch])
    return peak_guard(out, label="eq")

def hp_filter(audio, hz, order, sr):
    """Zero-phase high-pass filter."""
    sos = signal.butter(order, hz, btype='high', fs=sr, output='sos')
    out = audio.copy()
    for ch in range(out.shape[1]): out[:,ch] = signal.sosfiltfilt(sos, out[:,ch])
    return out

def lp_filter(audio, hz, order, sr):
    """Zero-phase low-pass filter."""
    hz  = min(hz, sr//2-200)
    sos = signal.butter(order, hz, btype='low', fs=sr, output='sos')
    out = audio.copy()
    for ch in range(out.shape[1]): out[:,ch] = signal.sosfiltfilt(sos, out[:,ch])
    return out

def underground_eq(audio, sr):
    """
    Underground electronic spectral character.
    Based on confirmed analysis of 6 professional reference tracks.
    Kick 40-80Hz is the dominant region (+26.7dB in references).
    """
    return apply_eq(audio, [
        (30,   1.8, 1.0),   # sub presence
        (60,   2.0, 1.5),   # kick fundamental - most critical
        (90,   1.5, 1.5),   # upper kick / bass body
        (130,  1.0, 2.0),   # bass warmth
        (230,  0.8, 2.0),   # low-mid body
        (400, -1.0, 2.0),   # mud control
        (600, -0.5, 2.0),   # boxy cut
        (3500,-1.2, 2.0),   # presence pull-back
        (7500,-1.5, 2.0),   # high darkening
        (15000,-1.8,2.0),   # air removal
    ], sr)

def profile_eq(audio, sr, profile):
    """Spectral match toward reference profile. Max MAX_EQ_DB per band."""
    bands = profile.get("spectral_bands_rel_1kHz", {})
    if not bands: return audio
    f_s, s_s = avg_spectrum(audio, sr)
    r1k      = np.mean(s_s[(f_s>=800)&(f_s<1200)])
    targets  = [
        (20,  40,  bands.get("sub_20_40",    14.18), 30,    1.0),
        (40,  80,  bands.get("kick_40_80",   26.70), 60,    1.5),
        (80,  160, bands.get("bass_80_160",  17.13), 120,   1.5),
        (160, 300, bands.get("low_mid_160_300",11.32),230,  2.0),
        (2000,5000,bands.get("presence_2k_5k",-6.61),3500,  2.0),
        (5000,10000,bands.get("high_5k_10k", -9.72), 7500,  2.0),
        (10000,20000,bands.get("air_10k_20k",-18.19),15000, 2.0),
    ]
    cuts = []
    for lo, hi, tgt, ctr, Q in targets:
        mask = (f_s>=lo)&(f_s<hi)
        if not mask.any(): continue
        corr = np.clip((tgt-20*np.log10((np.mean(s_s[mask])+1e-12)/(r1k+1e-12)))*0.5,
                       -MAX_EQ_DB, MAX_EQ_DB)
        if abs(corr) > 0.3: cuts.append((ctr, corr, Q))
    return apply_eq(audio, cuts, sr) if cuts else audio

def ref_track_eq(audio, sr, ref_audio, ref_sr):
    """Spectral match toward a reference WAV. Zero-phase STFT approach."""
    if ref_audio is None: return audio
    f_s, s_s = avg_spectrum(audio, sr)
    f_r, s_r = avg_spectrum(ref_audio, ref_sr)
    s_ri = interp1d(f_r, s_r, kind='linear', bounds_error=False, fill_value=s_r[-1])(f_s)
    rdb  = np.clip(20*np.log10((s_ri+1e-12)/(s_s+1e-12)), -MAX_EQ_DB, MAX_EQ_DB)
    out  = audio.copy()
    for ch in range(audio.shape[1]):
        _, _, Z = signal.stft(audio[:,ch], fs=sr, nperseg=4096, noverlap=2048, window='hann')
        _, x   = signal.istft(Z*10**(rdb[:,np.newaxis]/20.0), fs=sr, nperseg=4096, noverlap=2048, window='hann')
        n = audio.shape[0]
        out[:,ch] = x[:n] if len(x)>=n else np.pad(x,(0,n-len(x)))
    return peak_guard(out, label="ref_eq")

def ms_widen(audio, sr, width_pct=4.0):
    """M/S EQ gentle widening. 4% default as per spec."""
    if audio.shape[1] < 2: return audio
    mid  = (audio[:,0]+audio[:,1]) * 0.5
    side = (audio[:,0]-audio[:,1]) * 0.5 * (1.0 + width_pct/100.0)
    out  = np.zeros_like(audio)
    out[:,0] = mid+side; out[:,1] = mid-side
    return check_correlation(peak_guard(out, label="ms_widen"), "ms_widen")

def compressor(audio, sr, thr_db=-18.0, ratio=2.0, att_ms=40.0, rel_ms=200.0):
    """Causal feed-forward RMS compressor. GR capped at MAX_GR_DB."""
    n, nch = audio.shape; thr = 10**(thr_db/20.0)
    att = np.exp(-1.0/(sr*att_ms/1000.0)); rel = np.exp(-1.0/(sr*rel_ms/1000.0))
    min_g = 10**(-MAX_GR_DB/20.0); out = np.zeros_like(audio); g = 1.0
    for i in range(n):
        lvl = np.max(np.abs(audio[i]))
        tgt = max(min_g, thr*(lvl/thr)**(1.0/ratio)/(lvl+1e-12)) if lvl>thr else 1.0
        g   = att*g+(1-att)*tgt if tgt<g else rel*g+(1-rel)*tgt
        out[i] = audio[i]*g
    return peak_guard(out, label="comp")

def multiband_comp(audio, sr):
    """2-band compressor (low + mid). Zero-phase crossover filters."""
    result = np.zeros_like(audio)
    for lo, hi, ratio, att, rel in [(20,120,2.0,50,230),(120,5000,1.5,40,200)]:
        hi = min(hi, sr//2-100)
        if lo >= hi: continue
        lp = signal.butter(4, hi, btype='low',  fs=sr, output='sos')
        hp = signal.butter(4, lo, btype='high', fs=sr, output='sos')
        band = audio.copy()
        for ch in range(audio.shape[1]):
            band[:,ch] = signal.sosfiltfilt(lp, signal.sosfiltfilt(hp, band[:,ch]))
        result += compressor(band, sr, thr_db=-20.0, ratio=ratio, att_ms=att, rel_ms=rel)
    return peak_guard(result, label="multiband")

def tube_saturate(audio, wet=0.08):
    """
    Tube saturation: 8% wet even-harmonic waveshaping.
    Non-destructive - does not hard clip.
    """
    dry  = audio.copy()
    sat  = np.sign(audio) * (1.0 - np.exp(-np.abs(audio) * 2.5))
    out  = dry*(1.0-wet) + sat*wet
    return peak_guard(out, label="tube_sat")

def soft_clip(audio, knee=0.7, ceiling=0.910):
    """
    ONE soft-clip pass for P3 only. Piecewise:
    unity below knee, tanh above, ceiling at 0.910.
    Never called more than once per pipeline run.
    """
    out  = audio.copy()
    mask = np.abs(audio) > knee
    sign = np.sign(audio[mask])
    exc  = (np.abs(audio[mask]) - knee) / (1.0 - knee)
    out[mask] = sign * (knee + (ceiling-knee) * np.tanh(exc))
    return out

def hard_limit(audio, ceiling_db=TRUE_PEAK_DB):
    """Final hard limit - ONE pass at end of P3."""
    ceil = 10**(ceiling_db/20.0)
    pk   = np.max(np.abs(audio))
    return audio * (ceil/pk) if pk > ceil else audio

def noise_floor(audio, sr, level_db=-62.0):
    """Add gentle noise floor - breaks AI periodicity patterns."""
    n, nch = audio.shape; amp = 10**(level_db/20.0); rng = np.random.default_rng(42)
    hp = signal.butter(2, 40,                    btype='high', fs=sr, output='sos')
    lp = signal.butter(2, min(18000,sr//2-200),  btype='low',  fs=sr, output='sos')
    out = np.zeros_like(audio)
    for ch in range(nch):
        x = rng.standard_normal(n)*amp
        x = signal.sosfiltfilt(hp, x); x = signal.sosfiltfilt(lp, x)
        out[:,ch] = x
    return peak_guard(audio+out, label="noise_floor")

def stereo_move(audio, sr, rate_hz=0.07, depth=0.03):
    if audio.shape[1] < 2: return audio
    t = np.arange(audio.shape[0])/sr; lfo = 1.0+depth*np.sin(2.0*np.pi*rate_hz*t)
    mid = (audio[:,0]+audio[:,1])*0.5; side = (audio[:,0]-audio[:,1])*0.5*lfo
    out = np.zeros_like(audio); out[:,0]=mid+side; out[:,1]=mid-side
    return check_correlation(peak_guard(out, label="stereo_move"), "stereo_move")

def mono_sub(audio, sr, xover_hz=100.0):
    """Sub below 100 Hz forced to mono. Zero-phase crossover."""
    if audio.shape[1] < 2: return audio
    lp  = signal.butter(4, xover_hz, btype='low',  fs=sr, output='sos')
    hp  = signal.butter(4, xover_hz, btype='high', fs=sr, output='sos')
    sub = signal.sosfiltfilt(lp, (audio[:,0]+audio[:,1])*0.5)
    out = np.zeros_like(audio)
    for ch in range(audio.shape[1]):
        out[:,ch] = signal.sosfiltfilt(hp, audio[:,ch]) + sub
    return out

def pan(audio, v):
    if audio.shape[1] < 2: return audio
    out = audio.copy()
    if v > 0: out[:,0] *= (1.0-v)
    elif v < 0: out[:,1] *= (1.0+v)
    return out

def limit_lufs(audio, sr, target, ceiling_db=TRUE_PEAK_DB, max_gain_db=14.0):
    """Gain to target LUFS. Stereo measurement. PLR protection."""
    cur = measure_lufs(audio, sr)
    if np.isinf(cur) or np.isnan(cur): return audio
    gain_db = min(target - cur, max_gain_db)
    audio   = audio * 10**(gain_db/20.0)
    ceiling = 10**(ceiling_db/20.0)
    pk      = np.max(np.abs(audio))
    if pk > ceiling: audio = audio*(ceiling/pk)
    plr, lufs_out, pk_out = measure_plr(audio, sr)
    if plr < MIN_PLR: log(f"  PLR {plr:.1f}dB below min {MIN_PLR}dB - dynamics protected.", "WARN")
    elif plr > MAX_PLR: log(f"  PLR {plr:.1f}dB - could be louder.", "INFO")
    return audio


# -----------------------------------------------------------------------------
# STEM-ONLY DSP (never on full mix)
# -----------------------------------------------------------------------------

def noise_gate(audio, sr, threshold_db=-65.0):
    """Noise gate at -65 dB. Causal envelope follower."""
    thr = 10**(threshold_db/20.0)
    att = np.exp(-1.0/(sr*0.010)); rel = np.exp(-1.0/(sr*0.100))
    out = audio.copy(); g = 0.0
    for i in range(audio.shape[0]):
        lvl = np.max(np.abs(audio[i]))
        tgt = 1.0 if lvl > thr else 0.0
        g   = att*g+(1-att)*tgt if tgt > g else rel*g+(1-rel)*tgt
        out[i] = audio[i]*g
    return out

def ai_resonance_remove(audio, sr, max_notches=8):
    """
    STFT scan of first 30s to find AI codec resonances (EnCodec artifacts).
    Notch filter up to 8 per stem, Q=3, depth=-4dB.
    Range: 300 Hz - 16 kHz ONLY.
    NEVER call on full mix - individual stems only.
    """
    seg  = audio[:min(audio.shape[0], sr*30)]
    mono = to_mono(seg).astype(np.float32)
    f, _, Z = signal.stft(mono, fs=sr, nperseg=4096, noverlap=3072, window='hann')
    mag     = np.mean(np.abs(Z), axis=1)
    mask    = (f >= 300) & (f <= min(16000, sr//2-200))
    f_r     = f[mask]; mag_r = mag[mask]
    smooth  = uniform_filter1d(mag_r, size=20)
    peaks   = []
    time_mag = np.abs(Z[mask, :])
    for i in range(5, len(f_r)-5):
        if mag_r[i] > smooth[i] * 2.0:
            cv = float(np.std(time_mag[i,:])/(np.mean(time_mag[i,:])+1e-9))
            if cv < 0.5:
                peaks.append((f_r[i], float(mag_r[i])))
    peaks.sort(key=lambda x: -x[1]); peaks = peaks[:max_notches]
    if not peaks: return audio
    result = audio.copy()
    for freq, _ in peaks:
        sos = peaking_sos(freq, -4.0, 3.0, sr)
        for ch in range(result.shape[1]):
            result[:,ch] = signal.sosfiltfilt(sos, result[:,ch])
        log(f"     Notch: {freq:.0f} Hz Q=3 -4dB")
    return peak_guard(result, label="resonance_notch")

def deess(audio, sr):
    """
    De-esser for vocal stems only.
    6-11 kHz detection, 4.5:1 ratio, -22 dB threshold.
    """
    hp  = signal.butter(4, 6000, btype='high', fs=sr, output='sos')
    det = np.zeros(audio.shape[0])
    for ch in range(audio.shape[1]):
        det += signal.sosfiltfilt(hp, audio[:,ch])**2
    det = np.sqrt(det / audio.shape[1])
    thr  = 10**(-22.0/20.0); ratio = 4.5
    att  = np.exp(-1.0/(sr*0.001)); rel = np.exp(-1.0/(sr*0.050))
    gain = np.ones_like(det); g = 1.0
    for i in range(len(det)):
        lvl = det[i]
        tgt = (thr*(lvl/thr)**(1.0/ratio)/(lvl+1e-12)) if lvl>thr else 1.0
        g   = att*g+(1-att)*tgt if tgt<g else rel*g+(1-rel)*tgt
        gain[i] = g
    hp_sos = signal.butter(4, 6000, btype='high', fs=sr, output='sos')
    lp_sos = signal.butter(4, 6000, btype='low',  fs=sr, output='sos')
    out = audio.copy()
    for ch in range(audio.shape[1]):
        hi = signal.sosfiltfilt(hp_sos, audio[:,ch]) * gain
        lo = signal.sosfiltfilt(lp_sos, audio[:,ch])
        out[:,ch] = lo + hi
    return peak_guard(out, label="deess")

def virtual_analog_strip(audio, sr, console):
    """
    Virtual Analog Channel Strip - last step of P1 per stem.
    Simulates: input transformer -> gain stage -> output transformer.
    Console types: SSL (bass/drums), API (guitar), Neve (piano/vocals/other).
    """
    if console == "SSL":
        # SSL: tight, punchy, even harmonics, slight 6kHz air
        audio = hp_filter(audio, 25,   4, sr)      # input transformer HP
        audio = apply_eq(audio, [(6000, 0.3, 2.0)], sr)   # SSL air
        audio = tube_saturate(audio, wet=0.04)     # even-harmonic warmth
        audio = peak_guard(audio, label="SSL")

    elif console == "API":
        # API: presence at 2.5kHz, 2nd/3rd harmonics, slightly aggressive
        audio = hp_filter(audio, 30,   2, sr)
        audio = apply_eq(audio, [(2500, 0.3, 2.0)], sr)   # API crack
        audio = tube_saturate(audio, wet=0.05)
        audio = peak_guard(audio, label="API")

    else:  # Neve
        # Neve: warm 250Hz body, rich 2nd harmonic, silk top end
        audio = hp_filter(audio, 15,   2, sr)
        audio = apply_eq(audio, [(250, 0.2, 2.0),(8000,-0.2,2.0)], sr)  # Neve weight
        audio = tube_saturate(audio, wet=0.06)
        audio = peak_guard(audio, label="Neve")

    return audio


# -----------------------------------------------------------------------------
# AI FINGERPRINT
# -----------------------------------------------------------------------------

def fingerprint(mono, sr):
    fmax = min(FP_FMAX, sr//2-200)
    f, _, Z = signal.stft(mono, fs=sr, nperseg=4096, noverlap=3072, window='hann')
    avg  = np.mean(np.abs(Z), axis=1)
    mask = (f>=FP_FMIN)&(f<=fmax)
    bf   = np.linspace(FP_FMIN, fmax, FP_BINS)
    s    = interp1d(f[mask], avg[mask], kind='linear', bounds_error=False, fill_value=0.0)(bf)
    lm   = minimum_filter1d(s, size=FP_DWIN); raw = s-lm; pk = raw.max()
    return {"norm":raw/pk if pk>0 else raw.copy(),"raw":raw,"bf":bf,"peak":float(pk)}

def fp_score(fp):
    top8 = np.sort(fp["norm"])[-8:]
    return float(1.0/(1.0+np.exp(-(top8.mean()-0.35)*8.0)))

def save_fp_plot(fp_b, fp_a, path):
    fig, axes = plt.subplots(3,1,figsize=(14,9),facecolor='#0d1117')
    fig.suptitle("AI Artifact Fingerprint Before vs After",color='white',fontsize=12)
    x = np.arange(FP_BINS)
    for ax,d,c,l in [(axes[0],fp_b["norm"],'#f85149','Before'),
                     (axes[1],fp_a["norm"],'#3fb950','After')]:
        ax.set_facecolor('#161b22'); ax.tick_params(colors='#8b949e')
        ax.bar(x,d,color=c,alpha=0.85,width=0.85)
        ax.set_title(l,color=c,fontsize=10); ax.set_ylim(0,1.08)
    delta = fp_a["norm"]-fp_b["norm"]
    axes[2].set_facecolor('#161b22'); axes[2].tick_params(colors='#8b949e')
    axes[2].bar(x,delta,color=['#3fb950' if d<0 else '#f85149' for d in delta],alpha=0.85,width=0.85)
    axes[2].axhline(0,color='#8b949e',lw=0.8)
    axes[2].set_title('Delta (green=improved)',color='#8b949e',fontsize=10)
    plt.tight_layout()
    plt.savefig(path,dpi=120,bbox_inches='tight',facecolor='#0d1117')
    plt.close()


# -----------------------------------------------------------------------------
# LETSSUBMIT
# -----------------------------------------------------------------------------

def letssubmit_check(short_path, api_key):
    if api_key and HAS_REQ:
        try:
            with open(short_path,'rb') as f:
                r = requests.post('https://file.io',files={'file':f},data={'expires':'1d'},timeout=90)
            if r.status_code == 200:
                url = r.json().get('link')
                if url:
                    r2 = requests.post('https://api.letssubmit.com/analyze_song',
                        headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
                        json={'file_url':url}, timeout=180)
                    if r2.status_code == 200:
                        res = r2.json(); log(f"  LetsSubmit: {res}"); return res
        except Exception as e: log(f"  LetsSubmit error: {e}","WARN")
    log(f"  Upload manually: {short_path}")
    webbrowser.open("https://letssubmit.com/ai-music-checker")
    return None


# -----------------------------------------------------------------------------
# P0 - AI IDENTIFICATION REMOVAL
# -----------------------------------------------------------------------------

def p0(song_base, original_wav, paths, ls_key=None):
    section("P0  AI IDENTIFICATION REMOVAL")
    audio, sr, info = load(original_wav)
    n_mix = audio.shape[0]; sname = os.path.basename(song_base)
    rep   = {"pipeline":"P0","song":sname,"duration_s":round(n_mix/sr,2),"sample_rate":sr}

    # Step 1 - Strip all metadata
    log("P0 [1/6] Metadata strip...")
    if HAS_MUT:
        try:
            tags = ID3(original_wav)
            ai   = [k for k in list(tags.keys())
                    if any(w in k.lower() for w in ['suno','udio','ai','generated','encoder'])]
            for k in ai: del tags[k]
            if ai: tags.save(); log(f"  Removed {len(ai)} AI metadata tags.")
        except Exception: pass

    # Step 2 - Ultrasonic AI watermark removal (EnCodec wall at 17-18kHz)
    log("P0 [2/6] Ultrasonic LP @ 18kHz (AI watermark removal)...")
    audio = lp_filter(audio, 18000, 6, sr)

    # Step 3 - Infrasonic HP
    log("P0 [3/6] Infrasonic HP @ 18Hz (DC/infrasonic removal)...")
    audio = hp_filter(audio, 18, 2, sr)

    # Step 4 - Infrasonic scan: if sub-30Hz excess > -10dB, apply HP @ 30Hz
    log("P0 [4/6] Infrasonic scan...")
    mono = to_mono(audio)
    f_w, Pxx = signal.welch(mono, sr, nperseg=min(8192, n_mix//4))
    sub30  = float(10*np.log10(np.mean(Pxx[(f_w>=5)&(f_w<30)])+1e-12))
    mid1k  = float(10*np.log10(np.mean(Pxx[(f_w>=800)&(f_w<1200)])+1e-12))
    excess = sub30 - mid1k
    rep["infrasonic_excess_db"] = round(excess, 1)
    if excess > -10.0:
        log(f"  Infrasonic excess {excess:.1f}dB > -10dB threshold - applying HP @ 30Hz")
        audio = hp_filter(audio, 30, 4, sr)
    else:
        log(f"  Infrasonic check OK ({excess:.1f}dB)")

    # Step 5 - AI fingerprint
    log("P0 [5/6] AI fingerprint analysis...")
    mono  = to_mono(audio)
    start = find_active_section(audio, sr)
    fp    = fingerprint(mono, sr); sc = fp_score(fp)
    rep["ai_score_pct"] = round(sc*100, 1)
    log(f"  Internal AI score: {sc*100:.1f}%  (active section starts at {start/sr:.1f}s)")

    # Step 6 - Shortened file + LetsSubmit + Demucs
    log("P0 [6/6] Shortened file + Demucs stem separation...")
    short_name = f"{sname}_shortened.wav"
    short_song = os.path.join(song_base,"P0_DETECTION","shortened",short_name)
    short_root = os.path.join(paths["shortened"],short_name)
    save_quarter(audio, sr, short_song, info)
    shutil.copy2(short_song, short_root)
    letssubmit_check(short_song, ls_key)

    raw_dir = os.path.join(song_base,"P1_STEMCLEANING","stems_raw")
    stems   = _run_demucs(original_wav, raw_dir, sname)
    if not stems: log("  Demucs failed.", "ERROR"); return None, None, info, sr, n_mix
    for sn, sp in stems.items():
        a, ssr, _ = load(sp)
        sc2 = fp_score(fingerprint(to_mono(a), ssr))
        log(f"  {sn:<12} AI: {sc2*100:.1f}%")
    rep["stems"] = list(stems.keys())
    _report(os.path.join(song_base,"P0_DETECTION","detection_reports","p0_report.json"), rep)
    section("P0 COMPLETE"); return stems, fp, info, sr, n_mix

def _run_demucs(wav, out_dir, song_name):
    r = subprocess.run([sys.executable,"-m","demucs","-n","htdemucs_6s",
                        "--float32","--clip-mode","clamp","--shifts","2","-o",out_dir,wav],
                       capture_output=True, text=True)
    if r.returncode != 0: log(f"  Demucs: {r.stderr[:300]}","ERROR"); return None
    base = os.path.splitext(os.path.basename(wav))[0]
    for cand in [song_name, base]:
        sd = os.path.join(out_dir,"htdemucs_6s",cand)
        if os.path.exists(sd): break
    else: log("  Demucs output folder not found.","ERROR"); return None
    stems = {}
    for sn in ["drums","bass","vocals","guitar","piano","other"]:
        p = os.path.join(sd,f"{sn}.wav")
        if os.path.exists(p): stems[sn]=p
    log(f"  Stems: {list(stems.keys())}"); return stems


# -----------------------------------------------------------------------------
# P1 - STEM CLEANING
# -----------------------------------------------------------------------------

def p1(song_base, stems_raw, mix_audio, sr, mix_info, n_mix):
    section("P1  STEM CLEANING")
    cdir   = os.path.join(song_base,"P1_STEMCLEANING","stems_cleaned")
    cleaned = {}; rep = {"pipeline":"P1","stems":{}}; bpm = None

    for sn, sp in stems_raw.items():
        log(f"P1  [{sn}]")
        stem, ssr, _ = load(sp)
        if ssr != sr:
            log(f"     Resampling {ssr}->{sr}Hz")
            stem = as_stereo(librosa.resample(to_mono(stem).astype(np.float32),
                                              orig_sr=ssr, target_sr=sr))
        stem = fit(stem, n_mix)

        # DC removal
        stem -= np.mean(stem, axis=0)
        # HP @ 5 Hz (DC/infrasonic safety)
        stem = hp_filter(stem, 5, 2, sr)
        # Click/pop repair (cubic spline)
        stem, nc = _remove_clicks_spline(stem)
        # Phase align to original mix
        stem, lag = _phase_align(stem, mix_audio, sr)
        stem = fit(stem, n_mix)
        # Noise gate -65dB
        stem = noise_gate(stem, sr, threshold_db=-65.0)
        # AI resonance removal (stems ONLY - never full mix)
        stem = ai_resonance_remove(stem, sr, max_notches=8)
        # De-essing (vocals only)
        if sn == "vocals":
            stem = deess(stem, sr)
        # Noise floor injection
        stem = noise_floor(stem, sr, level_db=-62.0)
        # Stereo movement
        stem = stereo_move(stem, sr, rate_hz=0.07, depth=0.02)
        # BPM detection (with bandpass pre-filter per spec)
        if bpm is None:
            bp_sos = signal.butter(4, [40, min(4000, sr//2-100)],
                                   btype='band', fs=sr, output='sos')
            mono_bp = signal.sosfiltfilt(bp_sos, to_mono(stem).astype(np.float32))
            t, _  = librosa.beat.beat_track(y=mono_bp, sr=sr, units='time')
            bpm   = float(np.atleast_1d(t)[0]) or 120.0
        # 128-grid quantize
        stem, bpm, ns = _quantize(stem, sr, bpm)
        # Gain stage
        stem = rms_gain(stem, target_db=-18.0)
        # Sub mono at 100Hz
        stem = mono_sub(stem, sr, xover_hz=100.0)
        # Safety ceiling -1 dBFS before console
        stem = peak_guard(stem, ceiling=0.8912, label=f"pre-console-{sn}")
        stem = fit(stem, n_mix)

        # LAST STEP: Virtual Analog Channel Strip
        console = CONSOLE_MAP.get(sn, "Neve")
        stem = virtual_analog_strip(stem, sr, console)
        log(f"     [{console}] console applied")

        stem = peak_guard(stem); stem = fit(stem, n_mix)
        out  = os.path.join(cdir, f"{sn}.wav")
        save(stem, sr, out, mix_info)
        cleaned[sn] = out
        rep["stems"][sn] = {"clicks":nc,"lag_ms":round(lag/sr*1000,2),
                             "bpm":round(bpm or 0,2),"shifts":ns,"console":console}
        log(f"     clicks={nc} lag={lag/sr*1000:.1f}ms bpm={bpm:.1f} shifts={ns}")

    _report(os.path.join(song_base,"P1_STEMCLEANING","alignment_reports","p1_report.json"), rep)
    section("P1 COMPLETE"); return cleaned, bpm

def _remove_clicks_spline(audio, thr=0.97):
    """Click removal with cubic spline interpolation."""
    n, nch = audio.shape; out = audio.copy(); total = 0
    for ch in range(nch):
        d  = out[:,ch]; cl = np.abs(d) > thr
        diff = np.diff(cl.astype(int), prepend=0, append=0)
        for s, e in zip(np.where(diff==1)[0], np.where(diff==-1)[0]):
            if s > 1 and e < n-1:
                pts = [max(0,s-2), s-1, e, min(n-1,e+1)]
                vals = [d[p] for p in pts]
                try:
                    cs  = CubicSpline(pts, vals)
                    d[s:e] = cs(np.arange(s, e))
                except Exception:
                    d[s:e] = np.interp(np.arange(s,e),[s-1,e],[d[s-1],d[e]])
                total += (e-s)
        out[:,ch] = d
    return out, total

def _phase_align(stem, mix, sr):
    ml  = int(sr*0.15); seg = min(stem.shape[0],mix.shape[0],sr*15)
    start = find_active_section(mix, sr)
    xc  = signal.correlate(to_mono(mix)[start:start+seg],
                           to_mono(stem)[start:start+seg], mode='full')
    lag = int(np.clip(signal.correlation_lags(seg,seg,mode='full')[np.argmax(xc)],-ml,ml))
    if lag == 0: return stem, 0
    n, nch = stem.shape
    if lag > 0: return np.vstack([np.zeros((lag,nch)),stem[:-lag]]), lag
    return np.vstack([stem[-lag:],np.zeros((-lag,nch))]), lag

def _quantize(audio, sr, bpm=None):
    n, nch = audio.shape; mono = to_mono(audio).astype(np.float32)
    if not bpm:
        t, _ = librosa.beat.beat_track(y=mono, sr=sr, units='time')
        bpm   = float(np.atleast_1d(t)[0])
    if bpm <= 0 or bpm > 300: return audio, bpm, 0
    cell = (60.0/bpm/GRID_DIV)*sr; maxs = int(cell/2)
    onsets = librosa.onset.onset_detect(y=mono, sr=sr, units='samples',
        hop_length=256, backtrack=True, pre_max=3, post_max=3,
        pre_avg=3, post_avg=5, delta=0.07, wait=10)
    res = audio.copy(); cum = 0; ns = 0
    fo  = np.linspace(1,0,CF_LEN); fi = np.linspace(0,1,CF_LEN)
    for ow in onsets:
        o  = int(ow+cum); sh = int(round(o/cell)*cell)-o
        if o<0 or o>=n or abs(sh)>maxs or sh==0: continue
        pos = max(0, o-CF_LEN//2)
        for ch in range(nch):
            a_ = res[pos:min(n,pos+CF_LEN),ch]; b_ = res[max(0,pos+sh):min(n,pos+sh+CF_LEN),ch]
            bl = min(len(a_),len(b_),CF_LEN)
            if bl >= 4: res[pos:pos+bl,ch] = a_[:bl]*fo[:bl]+b_[:bl]*fi[:bl]
        cum += sh; ns += 1
    return res, bpm, ns


# -----------------------------------------------------------------------------
# P2 - MIXING
# -----------------------------------------------------------------------------

def p2(song_base, cleaned_stems, mix_audio, sr, mix_info,
       n_mix, ref_audio=None, ref_sr=None, profile=None, bpm=120.0):
    section("P2  MIXING")
    spdir  = os.path.join(song_base,"P2_MIXING","stems_processed")
    sname  = os.path.basename(song_base)
    bus    = np.zeros((n_mix,2), dtype=np.float64)
    rep    = {"pipeline":"P2","stems":{}}

    # Pre-compute kick sidechain envelope
    kick_env = None
    if "drums" in cleaned_stems or "kick" in cleaned_stems:
        kick_path = cleaned_stems.get("drums") or cleaned_stems.get("kick")
        kick_audio, _, _ = load(kick_path)
        kick_mono = to_mono(kick_audio)
        # LP filter to isolate kick (below 200Hz)
        lp  = signal.butter(4, 200, btype='low', fs=sr, output='sos')
        kick_lp = signal.sosfiltfilt(lp, kick_mono)
        kick_env = _kick_envelope(kick_lp, sr, bpm)
        log(f"P2  Kick sidechain envelope computed (18ms att, 60% beat release)")

    for sn, sp in cleaned_stems.items():
        log(f"P2  [{sn}]")
        stem = fit(load(sp)[0], n_mix)
        stem = rms_gain(stem, target_db=-18.0)
        stem = apply_eq(stem, _stem_eq_cuts(sn), sr)
        stem = stem * STEM_VOL.get(sn, 0.70)
        stem = pan(stem, STEM_PAN.get(sn, 0.0))
        stem = compressor(stem, sr, thr_db=-18.0, ratio=1.8, att_ms=50.0, rel_ms=200.0)
        stem = tube_saturate(stem, wet=0.04)
        # Apply kick sidechain to non-kick stems (clarity, not pumping)
        if kick_env is not None and sn not in ("drums","kick"):
            stem = _apply_sidechain(stem, kick_env, depth_db=2.0)
        stem = peak_guard(stem); stem = fit(stem, n_mix)
        bus += stem; bus = peak_guard(bus, label="bus_sum")
        save(stem, sr, os.path.join(spdir,f"{sn}_processed.wav"), mix_info)
        rep["stems"][sn] = {"vol":STEM_VOL.get(sn,0.70),"pan":STEM_PAN.get(sn,0.0)}

    # Master bus processing
    bus = apply_eq(bus, [(280,-0.8,2.0),(500,-0.6,1.5)], sr)
    bus = compressor(bus, sr, thr_db=-15.0, ratio=1.3, att_ms=60.0, rel_ms=250.0)
    bus = underground_eq(bus, sr)
    if ref_audio is not None: bus = ref_track_eq(bus, sr, ref_audio, ref_sr)
    elif profile:              bus = profile_eq(bus, sr, profile)
    bus = mono_sub(bus, sr, xover_hz=100.0)
    bus = noise_floor(bus, sr, level_db=-64.0)
    # -6 dBFS peak ceiling
    pk  = np.max(np.abs(bus))
    if pk > 0: bus = bus * (10**(MIX_CEILING_DB/20.0)/pk)
    bus = peak_guard(bus); bus = fit(bus, n_mix)
    bus = check_correlation(bus, "P2_output")

    plr, lufs, pk_db = measure_plr(bus, sr)
    rep.update({"lufs":round(lufs,2),"peak_db":round(pk_db,2),"plr_db":plr})
    log(f"P2  LUFS={lufs:.1f}  Peak={pk_db:.1f}dBFS  PLR={plr:.1f}dB")

    pm = os.path.join(song_base,"P2_MIXING","pre_master",f"{sname}_premix.wav")
    save(bus, sr, pm, mix_info)
    save(np.repeat(np.mean(bus,axis=1,keepdims=True),2,axis=1), sr,
         os.path.join(song_base,"P2_MIXING","mono_check",f"{sname}_mono.wav"), mix_info)
    _report(os.path.join(song_base,"P2_MIXING","mix_reports","p2_report.json"), rep)
    section("P2 COMPLETE"); return pm, bus

def _kick_envelope(kick_mono, sr, bpm):
    """Kick-driven sidechain envelope. 18ms att, 60% of beat duration release."""
    beat_s = 60.0 / max(bpm, 60.0)
    att    = np.exp(-1.0/(sr*0.018))
    rel    = np.exp(-1.0/(sr*beat_s*0.60))
    env    = np.zeros(len(kick_mono)); g = 0.0
    for i in range(len(kick_mono)):
        tgt = abs(kick_mono[i])
        g   = att*g+(1-att)*tgt if tgt>g else rel*g+(1-rel)*tgt
        env[i] = g
    mx = env.max()
    return env/mx if mx > 0 else env

def _apply_sidechain(audio, envelope, depth_db=2.0):
    """Kick-driven ducking. Max 2dB - clarity not pumping."""
    min_g = 10**(-depth_db/20.0)
    gain  = 1.0 - (1.0-min_g)*envelope[:audio.shape[0]]
    gain  = np.clip(gain, min_g, 1.0)
    out   = audio.copy()
    for ch in range(out.shape[1]): out[:,ch] *= gain
    return out

def _stem_eq_cuts(sn):
    return {"kick":[(300,-1.0,2.0),(500,-0.8,1.5)],
            "bass":[(300,-1.0,2.0),(500,-0.8,1.5)],
            "drums":[(200,-0.8,2.0),(3500,-0.8,2.0)],
            "guitar":[(300,-0.6,2.0),(5000,0.5,2.0)],
            "piano":[(300,-0.6,2.0),(5000,0.5,2.0)],
            "other":[(300,-0.6,2.0)],
            "vocals":[(200,-0.8,2.0),(3000,0.5,2.0)]}.get(sn,[])


# -----------------------------------------------------------------------------
# P3 - MASTERING
# -----------------------------------------------------------------------------

def p3(song_base, premix_path, mix_audio, sr, mix_info, n_mix,
       ref_audio=None, ref_sr=None, profile=None,
       genre="underground", collection_dir=None, shortened_root=None):
    section("P3  MASTERING")
    sname      = os.path.basename(song_base)
    target_lufs= GENRE_LUFS.get(genre, GENRE_LUFS["underground"])
    crest_min  = GENRE_CREST_MIN.get(genre, 8.0)
    audio      = fit(load(premix_path)[0], n_mix)
    rep        = {"pipeline":"P3","genre":genre,
                  "targets":{"lufs":target_lufs,"peak_db":TRUE_PEAK_DB,
                              "min_plr":MIN_PLR,"max_plr":MAX_PLR,
                              "min_crest_db":crest_min}}

    plr_in, lufs_in, pk_in = measure_plr(audio, sr)
    rep["input"] = {"lufs":lufs_in,"peak":pk_in,"plr":plr_in}
    log(f"P3  Genre={genre}  Target={target_lufs}LUFS  CrestMin={crest_min}dB")
    log(f"P3  Input: LUFS={lufs_in:.1f}  Peak={pk_in:.1f}dBFS  PLR={plr_in:.1f}dB")
    if pk_in > 0.9999: log("  WARNING: pre-master is clipping.", "WARN")

    log("P3 [1/8] Corrective EQ (zero-phase)...")
    audio = apply_eq(audio,[(40,-1.5,1.5),(280,-1.0,2.0),(500,-0.8,1.5),(3200,-1.0,2.5)],sr)

    log("P3 [2/8] Underground style EQ...")
    audio = underground_eq(audio, sr)

    log("P3 [3/8] Reference spectral match...")
    if ref_audio is not None: audio = ref_track_eq(audio, sr, ref_audio, ref_sr)
    elif profile:              audio = profile_eq(audio, sr, profile)
    else:                      log("  No reference - style EQ only.")

    log("P3 [4/8] M/S widening (4%)...")
    audio = ms_widen(audio, sr, width_pct=4.0)

    log("P3 [5/8] Multiband compression (2 bands: low + mid)...")
    audio = multiband_comp(audio, sr)

    log("P3 [6/8] Master bus compression...")
    audio = compressor(audio, sr, thr_db=-18.0, ratio=1.8, att_ms=60.0, rel_ms=250.0)

    log("P3 [7/8] Tube saturation (8% wet) + stereo refinement...")
    audio = tube_saturate(audio, wet=0.08)
    audio = stereo_move(audio, sr, rate_hz=0.05, depth=0.02)
    audio = mono_sub(audio, sr, xover_hz=100.0)
    audio = noise_floor(audio, sr, level_db=-66.0)

    log(f"P3 [8/8] ONE gain calc + ONE soft-clip + ONE hard limit...")
    # ONE gain calculation
    cur_lufs = measure_lufs(audio, sr)
    gain_db  = min(target_lufs - cur_lufs, 14.0)
    audio    = audio * 10**(gain_db/20.0)
    log(f"  Gain applied: {gain_db:.2f}dB  (measured {cur_lufs:.1f} -> target {target_lufs})")
    # DR check: if crest below minimum, pull back gain to protect dynamics
    rms_cur = 20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)
    pk_cur  = 20*np.log10(np.max(np.abs(audio))+1e-12)
    crest   = pk_cur - rms_cur
    if crest < crest_min:
        pullback = crest_min - crest
        audio    = audio * 10**(-pullback/20.0)
        log(f"  DR protection: crest {crest:.1f}dB < {crest_min}dB - pulling back {pullback:.1f}dB")
    # ONE soft-clip pass
    audio = soft_clip(audio, knee=0.7, ceiling=0.910)
    # ONE hard limit
    audio = hard_limit(audio, ceiling_db=TRUE_PEAK_DB)
    audio = fit(audio, n_mix)

    # QC scan
    plr_out, lufs_out, pk_out = measure_plr(audio, sr)
    rms_out = 20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)
    crest_out = pk_out - rms_out
    clicks  = len(np.where(np.abs(np.diff(to_mono(audio)))>0.3)[0])
    corr    = float(np.corrcoef(audio[:,0],audio[:,1])[0,1]) if audio.shape[1]>=2 else 1.0
    rep["output"] = {"lufs":lufs_out,"peak":pk_out,"plr":plr_out,
                      "crest_db":round(crest_out,2),"correlation":round(corr,3),
                      "qc_clicks":clicks,"plr_ok":MIN_PLR<=plr_out<=MAX_PLR}
    log(f"P3  Output: LUFS={lufs_out:.1f}  Peak={pk_out:.1f}dBTP  PLR={plr_out:.1f}dB  Crest={crest_out:.1f}dB  Corr={corr:.3f}")
    log(f"    PLR {'OK' if MIN_PLR<=plr_out<=MAX_PLR else 'WARN'} | Crest {'OK' if crest_out>=crest_min else 'LOW'} | Clicks: {clicks}")

    master = os.path.join(song_base,"P3_MASTERING","final_master",
                          f"{sname}_master_{target_lufs:.1f}LUFS.wav")
    safe_save(audio, sr, master, mix_info, label="P3-final-master")
    log(f"P3  Master: {master}  [{sr}Hz 24-bit no-dither no-normalize]")

    sf.write(os.path.join(song_base,"P3_MASTERING","streaming",
                          f"{sname}_master_16bit.wav"), audio, sr, subtype='PCM_16')

    short = os.path.join(song_base,"P3_MASTERING","shortened",f"{sname}_master_short.wav")
    save_quarter(audio, sr, short, mix_info)
    if shortened_root:
        shutil.copy2(short, os.path.join(shortened_root,f"{sname}_master_short.wav"))
    letssubmit_check(short, None)

    if collection_dir:
        col = os.path.join(collection_dir, f"{sname}_master.wav")
        shutil.copy2(master, col); log(f"P3  Collection: {col}")

    fp_b = fingerprint(to_mono(load(premix_path)[0]), sr)
    fp_a = fingerprint(to_mono(audio), sr)
    save_fp_plot(fp_b, fp_a,
                 os.path.join(song_base,"P3_MASTERING","mastering_reports",
                              f"{sname}_fingerprint.png"))
    _report(os.path.join(song_base,"P3_MASTERING","mastering_reports","p3_report.json"), rep)
    section("P3 COMPLETE"); return master, audio


# -----------------------------------------------------------------------------
# P4 - MIDI & ABLETON
# -----------------------------------------------------------------------------

def p4(song_base, cleaned_stems, mix_audio, sr, mix_info, n_mix, bpm, master_path):
    section("P4  MIDI & ABLETON")
    sname = os.path.basename(song_base)
    mdir  = os.path.join(song_base,"P4_MIDI","midi_stems")
    adir  = os.path.join(song_base,"P4_MIDI","automation_lanes")
    midi  = {}; rep = {"pipeline":"P4"}

    log("P4  Key detection...")
    key, mode, conf = _detect_key(mix_audio, sr)
    log(f"    {key} {mode} conf={conf:.2f}")
    rep["key"] = {"root":key,"mode":mode,"conf":round(conf,3)}

    if "drums" in cleaned_stems:
        log("P4  Drum MIDI...")
        hits = _classify_drums(cleaned_stems["drums"], sr)
        dp   = os.path.join(mdir,f"{sname}_drums.mid")
        _drum_midi(hits, sr, bpm, dp); midi["drums"] = dp

    for sn in ["guitar","piano","other"]:
        if sn not in cleaned_stems: continue
        mp = os.path.join(mdir,f"{sname}_{sn}.mid")
        if _melodic_midi(cleaned_stems[sn], mp, sn, key, mode, conf): midi[sn]=mp

    for sn in ["bass","vocals"]:
        if sn not in cleaned_stems: continue
        mp = os.path.join(mdir,f"{sname}_{sn}.mid")
        if _mono_midi(cleaned_stems[sn], mp, sn, bpm, key, mode, conf): midi[sn]=mp

    log("P4  Automation lanes...")
    for sn, sp in cleaned_stems.items():
        _automation(sp, sr, bpm, os.path.join(adir,f"{sname}_{sn}_auto.mid"))

    ss = os.path.join(song_base,"P4_MIDI","ableton","samples","stems")
    sm = os.path.join(song_base,"P4_MIDI","ableton","samples","master")
    for sn, sp in cleaned_stems.items(): shutil.copy2(sp,os.path.join(ss,os.path.basename(sp)))
    if master_path and os.path.exists(master_path):
        shutil.copy2(master_path,os.path.join(sm,os.path.basename(master_path)))

    log("P4  Building Ableton Live 12 project...")
    als = _build_als(song_base, sname, cleaned_stems, bpm, midi)
    rep.update({"midi":{k:os.path.basename(v) for k,v in midi.items()},"als":als})
    _report(os.path.join(song_base,"P4_MIDI","midi_reports","p4_report.json"), rep)
    section("P4 COMPLETE"); return midi, als

def _detect_key(audio, sr):
    mono   = to_mono(audio).astype(np.float32)
    chroma = librosa.feature.chroma_cqt(y=mono, sr=sr).mean(axis=1)
    major  = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor  = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes  = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    bs,bk,bm = -np.inf,0,'major'
    for r in range(12):
        for prof, mode in [(major,'major'),(minor,'minor')]:
            sc = np.corrcoef(chroma,np.roll(prof,r))[0,1]
            if sc > bs: bs,bk,bm = sc,r,mode
    return notes[bk], bm, float(bs)

def _scale_pcs(key, mode):
    notes = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    ri    = notes.index(key)
    steps = [0,2,4,5,7,9,11] if mode=='major' else [0,2,3,5,7,8,10]
    return {(ri+s)%12 for s in steps}

def _correct_key(md, key, mode, conf):
    if not HAS_PM or md is None or conf < 0.6: return md
    scale = _scale_pcs(key, mode)
    for inst in md.instruments:
        if inst.is_drum: continue
        for note in inst.notes:
            pc = note.pitch%12
            if pc in scale: continue
            best = min(scale, key=lambda s: min(abs(s-pc),12-abs(s-pc)))
            diff = best-pc
            if abs(diff)>6: diff=diff-12 if diff>0 else diff+12
            note.pitch = int(np.clip(note.pitch+diff,0,127))
    return md

def _classify_drums(path, sr):
    audio,_,_ = load(path); mono = to_mono(audio).astype(np.float32)
    onsets = librosa.onset.onset_detect(y=mono, sr=sr, units='samples',
                                         hop_length=128, backtrack=True, delta=0.05, wait=5)
    res = {"kick":[],"snare":[],"hihat":[],"perc":[]}
    for o in onsets:
        seg = mono[max(0,o-64):min(len(mono),o+2048)]
        if len(seg)<32: continue
        spec = np.abs(np.fft.rfft(seg)); freqs = np.fft.rfftfreq(len(seg),1.0/sr)
        cent = np.sum(freqs*spec)/(np.sum(spec)+1e-9)
        elo  = np.sum(spec[freqs<200]); emid = np.sum(spec[(freqs>=200)&(freqs<2000)])
        ehi  = np.sum(spec[freqs>=2000])
        if cent<200 and elo>emid:        res["kick"].append(int(o))
        elif 200<=cent<2000 and emid>=elo: res["snare"].append(int(o))
        elif cent>=2000 and ehi>emid:    res["hihat"].append(int(o))
        else:                             res["perc"].append(int(o))
    return res

def _drum_midi(hits, sr, bpm, path):
    if not HAS_PM: return
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    inst = pretty_midi.Instrument(program=0,is_drum=True,name="Drums")
    gm   = {"kick":36,"snare":38,"hihat":42,"perc":47}
    for dt, positions in hits.items():
        for pos in positions:
            t = pos/sr; inst.notes.append(pretty_midi.Note(100,gm[dt],t,t+0.1))
    pm.instruments.append(inst); pm.write(path); log(f"    Drums MIDI: {path}")

def _melodic_midi(path, out, stype, key, mode, conf):
    try:
        from basic_pitch.inference import predict
        _, md, _ = predict(path); md = _correct_key(md,key,mode,conf)
        md.write(out); log(f"    {stype} MIDI: {out}"); return True
    except ImportError: log("    basic-pitch not installed.","WARN"); return False
    except Exception as e: log(f"    Basic Pitch ({stype}): {e}","WARN"); return False

def _mono_midi(path, out, stype, bpm, key, mode, conf):
    try:
        import crepe
        audio, sr, _ = load(path); mono = to_mono(audio).astype(np.float32)
        ta, fr, ca, _ = crepe.predict(mono,sr,viterbi=True,step_size=10,verbose=0)
        if not HAS_PM: return False
        pm   = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        inst = pretty_midi.Instrument(program=0,name=stype)
        pn, pt = None, None
        for t, f, c in zip(ta,fr,ca):
            if c<0.5 or f<30:
                if pn is not None: inst.notes.append(pretty_midi.Note(80,pn,pt,t)); pn=None
                continue
            nn = int(np.clip(round(69+12*np.log2(f/440.0)),0,127))
            if pn!=nn:
                if pn is not None: inst.notes.append(pretty_midi.Note(80,pn,pt,t))
                pn,pt = nn,t
        pm.instruments.append(inst); pm = _correct_key(pm,key,mode,conf)
        pm.write(out); log(f"    {stype} MIDI: {out}"); return True
    except ImportError: log("    crepe not installed.","WARN"); return False
    except Exception as e: log(f"    CREPE ({stype}): {e}","WARN"); return False

def _automation(path, sr, bpm, out):
    if not HAS_PM: return
    audio,_,_ = load(path); mono = to_mono(audio).astype(np.float32)
    hop = sr//10; n = len(mono)
    pm  = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    inst = pretty_midi.Instrument(program=0,name="Automation")
    for i in range(0,n-hop,hop):
        v = int(np.clip(np.sqrt(np.mean(mono[i:i+hop]**2))/0.5*127,0,127))
        inst.control_changes.append(pretty_midi.ControlChange(7,v,i/sr))
    cents = librosa.feature.spectral_centroid(y=mono,sr=sr,hop_length=hop)[0]
    cm = cents.max()+1e-9
    for i,c in enumerate(cents):
        inst.control_changes.append(pretty_midi.ControlChange(74,int(np.clip(c/cm*127,0,127)),i*hop/sr))
    if audio.shape[1]>=2:
        side=audio[:,0]-audio[:,1]; mid=audio[:,0]+audio[:,1]+1e-9
        for i in range(0,n-hop,hop):
            w = np.sqrt(np.mean(side[i:i+hop]**2))/np.sqrt(np.mean(mid[i:i+hop]**2)+1e-9)
            inst.control_changes.append(pretty_midi.ControlChange(1,int(np.clip(w*127,0,127)),i/sr))
    pm.instruments.append(inst); pm.write(out)

def _build_als(song_base, sname, cleaned_stems, bpm, midi_files):
    idc = [300]
    def nid(): idc[0]+=1; return idc[0]
    bus_ids = {b:nid() for b in BUS_MEMBERS}; pmix_id = nid()
    def col(n): return ALS_COLOR.get(n,17)
    def u():    return f'<PluginDevice Id="{nid()}"><Name><EffectiveName Value="Utility"/></Name></PluginDevice>'
    def eq8():  return f'<Eq8 Id="{nid()}"><Name><EffectiveName Value="EQ Eight"/></Name></Eq8>'
    def cmp():  return f'<Compressor2 Id="{nid()}"><Name><EffectiveName Value="Compressor"/></Name></Compressor2>'
    def glue(): return f'<GlueCompressor Id="{nid()}"><Name><EffectiveName Value="Glue Compressor"/></Name></GlueCompressor>'
    def sat():  return f'<Saturator Id="{nid()}"><Name><EffectiveName Value="Saturator"/></Name></Saturator>'
    def lim():  return f'<Limiter Id="{nid()}"><Name><EffectiveName Value="Limiter"/></Name></Limiter>'
    def rev():  return f'<Reverb Id="{nid()}"><Name><EffectiveName Value="Reverb"/></Name></Reverb>'
    def dly():  return f'<Delay Id="{nid()}"><Name><EffectiveName Value="Delay"/></Name></Delay>'
    def sw():   return f'<MaxDevice Id="{nid()}"><Name><EffectiveName Value="Swiss Army Meter"/></Name></MaxDevice>'
    def lvl():  return f'<PluginDevice Id="{nid()}"><Name><EffectiveName Value="LEVELS"/></Name></PluginDevice>'
    tc = lambda: u()+eq8()+cmp()+sat()+u()+lim()+sw()
    bc = lambda: u()+eq8()+glue()+u()+lim()
    pc = lambda: u()+eq8()+glue()+eq8()+u()+lim()
    rc = lambda fx: u()+fx+eq8()+u()
    trks = ""
    for sn in cleaned_stems:
        c  = col(STEM_COLOR.get(sn,"grey"))
        bs = next((b for b,m in BUS_MEMBERS.items() if sn in m),"SYNTHS")
        bid= bus_ids.get(bs,pmix_id); tid=nid()
        trks+=f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{sn.upper()}"/></Name><ColorIndex Value="{c}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/GroupMaster/{bid}"/><UpperDisplayString Value="{bs}"/></AudioOutputRouting><Devices>{tc()}</Devices></DeviceChain></AudioTrack>'
        if midi_files.get(sn) and os.path.exists(midi_files[sn]):
            trks+=f'<MidiTrack Id="{nid()}"><Name><EffectiveName Value="{sn.upper()} MIDI"/></Name><ColorIndex Value="{c}"/></MidiTrack>'
    for bn in BUS_MEMBERS:
        c=col(BUS_COLOR.get(bn,"grey"))
        trks+=f'<GroupTrack Id="{bus_ids[bn]}"><Name><EffectiveName Value="{bn}"/></Name><ColorIndex Value="{c}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/GroupMaster/{pmix_id}"/><UpperDisplayString Value="PREMIX"/></AudioOutputRouting><Devices>{bc()}</Devices></DeviceChain></GroupTrack>'
    trks+=f'<GroupTrack Id="{pmix_id}"><Name><EffectiveName Value="PREMIX"/></Name><ColorIndex Value="{col("light_grey")}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/Master"/><UpperDisplayString Value="Master"/></AudioOutputRouting><Devices>{pc()}</Devices></DeviceChain></GroupTrack>'
    rets=""
    for rn,rfx in [("SHORT REVERB",rev()),("LONG REVERB",rev()),("SHORT DELAY",dly()),("LONG DELAY",dly())]:
        rets+=f'<ReturnTrack Id="{nid()}"><Name><EffectiveName Value="{rn}"/></Name><ColorIndex Value="{col("light_grey")}"/><DeviceChain><Devices>{rc(rfx)}</Devices></DeviceChain></ReturnTrack>'
    mst=f'<MasterTrack Id="{nid()}"><Name><EffectiveName Value="Master"/></Name><DeviceChain><Devices>{lvl()}</Devices></DeviceChain></MasterTrack>'
    xml=(f'<?xml version="1.0" encoding="UTF-8"?>'
         f'<Ableton MajorVersion="12" MinorVersion="0" Creator="SunoMaster v{VERSION}">'
         f'<LiveSet><NextPointeeId Value="{idc[0]+100}"/>'
         f'<Tempo><Manual Value="{bpm:.4f}"/></Tempo>'
         f'<Tracks>{trks}</Tracks><ReturnTracks>{rets}</ReturnTracks>{mst}'
         f'</LiveSet></Ableton>')
    als_dir=os.path.join(song_base,"P4_MIDI","ableton")
    als=os.path.join(als_dir,f"{sname}.als")
    with gzip.open(als,'wb') as gf: gf.write(xml.encode('utf-8'))
    log(f"    Ableton project: {als}"); return als


# -----------------------------------------------------------------------------
# P5 - FINAL CLEANUP & AI SCAN
# -----------------------------------------------------------------------------

def p5_final_cleanup(song_base, ls_key=None):
    """
    Post-pipeline sweep of all output WAV files:
    1. Strip ALL metadata from every file (removes AI and Python footprints)
    2. Run internal AI fingerprint on every file
    3. Flag files scoring above 30%
    4. LetsSubmit final check on master shortened file
    """
    section("P5  FINAL CLEANUP & AI SCAN")
    sname  = os.path.basename(song_base)
    rep    = {"pipeline":"P5","song":sname,"files":{}}
    wav_files = []
    for root, dirs, files in os.walk(song_base):
        for fn in files:
            if fn.lower().endswith('.wav'):
                wav_files.append(os.path.join(root, fn))
    log(f"P5  Scanning {len(wav_files)} output WAV files...")
    for wav_path in wav_files:
        rel = os.path.relpath(wav_path, song_base)
        try:
            if HAS_MUT:
                try:
                    from mutagen import File as MF
                    mf = MF(wav_path)
                    if mf is not None: mf.delete(); mf.save()
                except Exception: pass
                try: ID3(wav_path).delete()
                except Exception: pass
            audio, sr, _ = load(wav_path)
            sc = fp_score(fingerprint(to_mono(audio), sr))
            rep["files"][rel] = round(sc*100, 1)
            flag = " <-- REVIEW" if sc > 0.30 else ""
            log(f"  {rel:<55} AI: {sc*100:.1f}%{flag}")
        except Exception as e: log(f"  ERROR {rel}: {e}", "WARN")
    short_master = os.path.join(song_base,"P3_MASTERING","shortened",
                                f"{sname}_master_short.wav")
    if os.path.exists(short_master) and ls_key:
        log("P5  LetsSubmit final check on master...")
        result = letssubmit_check(short_master, ls_key)
        if result: rep["letssubmit_final"] = result
    _report(os.path.join(song_base,"P3_MASTERING","mastering_reports",
                         "p5_cleanup_report.json"), rep)
    section("P5 COMPLETE"); return rep


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser(description=f"SunoMaster v{VERSION}")
    ap.add_argument("--computer", default="1",            help="1=Lenovo 2=ZBook")
    ap.add_argument("--drive",    default="D",            help="ZBook drive letter")
    ap.add_argument("--mode",     default="1",            help="1=single 2=batch")
    ap.add_argument("--song",     default="",             help="Song folder path")
    ap.add_argument("--ref",      default="",             help="Reference WAV path")
    ap.add_argument("--lskey",    default="",             help="LetsSubmit API key")
    ap.add_argument("--genre",    default="underground",  help="Genre for mastering target")
    args = ap.parse_args()

    section(f"SunoMaster v{VERSION}")
    root, machine = select_computer(args)
    paths = build_paths(root)
    ensure_root(paths)
    log(f"Machine: {machine}  Root: {root}")
    log(f"Genre:   {args.genre}  LUFS target: {GENRE_LUFS.get(args.genre,GENRE_LUFS['underground'])}")

    log("Loading reference profile...")
    profile = load_or_build_profile(paths["references"])
    bands   = profile.get("spectral_bands_rel_1kHz", {})
    log(f"  Kick 40-80Hz={bands.get('kick_40_80','?')}dB  "
        f"Air 10-20kHz={bands.get('air_10k_20k','?')}dB  rel 1kHz")

    ls_key = args.lskey.strip() or None
    mode   = args.mode.strip()
    songs  = []

    if mode == "2":
        ref = args.ref.strip().strip('"')
        for e in os.scandir(paths['releases']):
            if e.is_dir():
                wav = find_wav(e.path)
                if wav: songs.append((e.path, wav, ref))
        if not songs: log(f"No songs found in {paths['releases']}", "ERROR"); return
        log(f"Batch mode: {len(songs)} songs found.")
    else:
        folder = args.song.strip().strip('"')
        if not folder: log("No song folder provided.", "ERROR"); return
        if not os.path.isdir(folder): folder = os.path.join(paths['releases'], folder)
        wav = find_wav(folder)
        if not wav: log(f"No WAV in {folder}", "ERROR"); return
        songs.append((folder, wav, args.ref.strip().strip('"')))

    for song_folder, original_wav, ref_path in songs:
        sname     = os.path.basename(song_folder)
        song_base = os.path.join(paths['releases'], sname)
        create_song_folders(song_base)
        section(f"PROCESSING: {sname}")

        ref_audio = ref_sr = None
        if ref_path and os.path.exists(ref_path):
            try:
                ref_audio, ref_sr, _ = load(ref_path)
                log(f"Reference: {os.path.basename(ref_path)}")
            except Exception as e: log(f"Could not load reference: {e}", "WARN")
        else:
            log("No reference track - profile EQ only.", "WARN")

        mix_audio, sr, mix_info = load(original_wav)
        n_mix = mix_audio.shape[0]
        log(f"Original: {os.path.basename(original_wav)}")
        log(f"  {n_mix/sr:.1f}s  {sr}Hz  {mix_audio.shape[1]}ch  {mix_info.subtype}")

        stems_raw, fp_mix, mix_info, sr, n_mix = p0(song_base, original_wav, paths, ls_key)
        if not stems_raw: log(f"P0 failed - skipping {sname}.", "ERROR"); continue

        cleaned_stems, bpm = p1(song_base, stems_raw, mix_audio, sr, mix_info, n_mix)

        premix_path, premix_audio = p2(song_base, cleaned_stems, mix_audio, sr, mix_info,
                                        n_mix, ref_audio, ref_sr, profile, bpm)

        master_path, master_audio = p3(song_base, premix_path, mix_audio, sr, mix_info, n_mix,
                                        ref_audio, ref_sr, profile, genre=args.genre,
                                        collection_dir=paths['collection'],
                                        shortened_root=paths['shortened'])

        midi_files, als_path = p4(song_base, cleaned_stems, mix_audio, sr, mix_info,
                                   n_mix, bpm, master_path)

        p5_final_cleanup(song_base, ls_key)

        log_path = os.path.join(song_base, f"{sname}_pipeline_log.txt")
        save_log(log_path)
        section(f"DONE: {sname}")
        log(f"Master  : {master_path}")
        log(f"Ableton : {als_path}")
        log(f"Log     : {log_path}")

    section("ALL PIPELINES COMPLETE")


if __name__ == '__main__':
    main()
