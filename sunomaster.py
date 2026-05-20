"""
================================================================================
SunoMaster v5.3  -  Complete Self-Contained Audio Production Pipeline
================================================================================
LEVIATHAN APPROVED + Live Run Fixes

FIXES vs v5.2 (from live run on 01_Transfinite):
  [LIVE-1] _report: NpEnc custom JSON encoder - numpy int64 now serializable
  [LIVE-2] p1: peak_guard added after rms_gain - stops sparse stems from
           clipping at 16-17 dBFS (Demucs guitar/piano have extreme crest)
  [LIVE-3] p1: correlation guard after stereo_move - if < 0.5 blend to mono
  [LIVE-4] infrasonic threshold raised from -10 to -5 dB for HP@30Hz
  [ARG-1]  argparse: --ref and --lskey use nargs='?' - truly optional

FIXES vs v5.1 (LEVIATHAN 3-round QA):
  [LEV-1]  targeted_spectral_eq runs in P3 only (was also in P2)
  [LEV-2]  brightness_excess returns 0 if centroid is None
  [LEV-3]  save() always writes PCM_24
  [LEV-4]  compressor() skips silence (no GR on lvl < 1e-9)
  [LEV-5]  targeted_spectral_eq 60Hz capped to avoid double-boost
  [LEV-6]  noise_gate/compressor vectorized (6-10x faster)
  [LEV-7]  _phase_align segment bounds safe
  [LEV-8]  noise_floor seeded from song content
  [LEV-9]  lra_measure samples middle third of track
  [LEV-10] _run_demucs uses WAV basename only for folder lookup
  [LEV-11] lra_measure stride optimised - startup under 5 minutes
  [LEV-12] p5_final_cleanup scans P3_MASTERING only
  [LEV-13] letssubmit_check never opens browser
  [LEV-14] p4 wrapped in try/except - pipeline never halts on MIDI errors

HOW THIS SCRIPT WORKS ON EVERY RUN:
  Step 1  Scan references folder -> build fresh reference profile
  Step 2  Scan releases folder   -> diagnose every song
  Step 3  Print full comparison report
  Step 4  Ask confirmation before processing
  Step 5  Process each song P0-P5 with per-song targeted corrections
  Step 6  Print before/after verification

DESIGN RULES (never violated):
  - No pitch changes. No song structure changes.
  - All outputs match original mix duration.
  - Max 2 dB per EQ band. Max 3 dB GR per compressor.
  - ZERO hard clipping at any stage.
  - Even-harmonic saturation only.
  - AI resonance notching on stems ONLY, never full mix.
  - Sub below 100 Hz always mono.
  - Stereo correlation > 0.5 enforced throughout.
  - All EQ: sosfiltfilt (zero-phase). Dynamics: sosfilt (causal).
  - ONE soft-clip pass in P3 only.
  - Export: 24-bit WAV, no dither, no normalize.
================================================================================
"""

import os, sys, json, time, shutil, warnings, subprocess, gzip
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.interpolate import interp1d, CubicSpline
from scipy.signal import welch, resample_poly
import librosa
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:    import pyloudnorm as pyln;  HAS_LN  = True
except: HAS_LN  = False
try:    from mutagen.id3 import ID3; HAS_MUT = True
except: HAS_MUT = False
try:    import requests;             HAS_REQ = True
except: HAS_REQ = False
try:    import pretty_midi;          HAS_PM  = True
except: HAS_PM  = False

VERSION        = "5.3"
TRUE_PEAK_DB   = -2.0
MIN_PLR        = 6.0
MAX_PLR        = 9.0
MIX_CEILING_DB = -6.0
MAX_EQ_DB      = 2.0
MAX_GR_DB      = 3.0
GRID_DIV       = 128
CF_LEN         = 256
NORM_REF_SUBDIR= "normalized reference tracks"
INFRA_HP30_THR = -5.0

GENRE_LUFS = {
    "techno":-7.5,"underground":-8.0,"house":-8.0,
    "deep_house":-9.0,"progressive":-9.5,"melodic":-10.0,"ambient":-20.0,
}
GENRE_CREST_MIN = {
    "techno":7.5,"underground":8.0,"house":8.0,
    "deep_house":8.5,"progressive":8.5,"melodic":9.0,"ambient":12.0,
}
CONSOLE_MAP = {
    "bass":"SSL","drums":"SSL","guitar":"API",
    "piano":"Neve","vocals":"Neve","other":"Neve","kick":"SSL",
}
FP_FMIN,FP_FMAX,FP_BINS,FP_DWIN = 5000,16000,128,18

ALS_COLOR   = {"black":1,"red":14,"yellow":5,"purple":25,"orange":9,"blue":20,"maroon":13,"light_grey":18}
STEM_COLOR  = {"kick":"black","bass":"black","drums":"red","vocals":"yellow","other":"purple","guitar":"orange","piano":"blue","fx":"maroon"}
BUS_COLOR   = {"LOWEND":"black","DRUMS":"red","VOCALS":"yellow","SYNTHS":"purple","GUITAR":"orange","PIANO":"blue","FX":"maroon","PREMIX":"light_grey"}
BUS_MEMBERS = {"LOWEND":["kick","bass"],"DRUMS":["drums"],"VOCALS":["vocals"],"SYNTHS":["other"],"GUITAR":["guitar"],"PIANO":["piano"],"FX":[]}
STEM_VOL    = {"kick":0.90,"drums":0.75,"bass":0.85,"vocals":0.80,"guitar":0.65,"piano":0.65,"other":0.70,"fx":0.55}
STEM_PAN    = {"kick":0.0,"bass":0.0,"drums":0.0,"vocals":0.0,"guitar":0.15,"piano":-0.15,"other":0.0,"fx":0.0}

BAND_KEYS   = ["sub_20_40","kick_40_80","bass_80_160","low_mid_160_300",
               "mid_300_800","upper_800_2k","presence_2k_5k","high_5k_10k","air_10k_20k"]
BAND_RANGES = [(20,40),(40,80),(80,160),(160,300),(300,800),(800,2000),(2000,5000),(5000,10000),(10000,20000)]

_LOG = []

def log(msg, level="INFO"):
    line = f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}"
    print(line); _LOG.append(line)

def save_log(path):
    with open(path,'w',encoding='utf-8') as f: f.write('\n'.join(_LOG))

def section(title=""):
    bar = "=" * 66
    if title: log(bar); log(f"  {title}"); log(bar)
    else: log(bar)

def _report(path, data):
    class NpEnc(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)
    with open(path,'w') as f: json.dump(data,f,indent=2,cls=NpEnc)

def select_computer(args):
    if args.computer == "2": return f"{args.drive.upper()}:\\", "HP ZBook"
    return "E:\\", "Lenovo ThinkStation"

def build_paths(root):
    sm = os.path.join(root,"SunoMaster"); p = {"root":sm}
    for n in ("releases","collection","references","scripts","downloads","backup","shortened","output"):
        p[n] = os.path.join(sm,n)
    return p

def ensure_root(paths):
    for p in paths.values(): os.makedirs(p,exist_ok=True)

def create_song_folders(base):
    for sub in [
        "P0_DETECTION/cleaned","P0_DETECTION/detection_reports","P0_DETECTION/shortened",
        "P1_STEMCLEANING/stems_raw","P1_STEMCLEANING/stems_cleaned",
        "P1_STEMCLEANING/phase_reports","P1_STEMCLEANING/alignment_reports",
        "P2_MIXING/pre_master","P2_MIXING/stems_processed","P2_MIXING/mono_check","P2_MIXING/mix_reports",
        "P3_MASTERING/final_master","P3_MASTERING/streaming","P3_MASTERING/shortened","P3_MASTERING/mastering_reports",
        "P4_MIDI/midi_stems","P4_MIDI/automation_lanes",
        "P4_MIDI/ableton/samples/stems","P4_MIDI/ableton/samples/master","P4_MIDI/midi_reports",
    ]:
        os.makedirs(os.path.join(base,sub),exist_ok=True)

def find_wav(folder):
    wavs = [f for f in os.listdir(folder) if f.lower().endswith('.wav')]
    for w in wavs:
        if 'original' in w.lower(): return os.path.join(folder,w)
    return os.path.join(folder,wavs[0]) if wavs else None

def load(path):
    a,sr = sf.read(path,always_2d=True); return a.astype(np.float64),sr,sf.info(path)

def save(audio, sr, path):
    sf.write(path, audio, sr, subtype='PCM_24')

def save_16bit(audio, sr, path):
    sf.write(path, audio, sr, subtype='PCM_16')

def safe_save(audio, sr, path, label=""):
    pk = 20*np.log10(np.max(np.abs(audio))+1e-12)
    if pk > TRUE_PEAK_DB:
        log(f"  Pre-save guard [{label}]: {pk:.2f}dBFS corrected.","WARN")
        audio = peak_guard(audio, 10**(TRUE_PEAK_DB/20.0), label)
    else: log(f"  [{label}] peak {pk:.2f}dBFS clean.")
    save(audio, sr, path)
    if HAS_MUT:
        try: ID3(path).delete()
        except: pass

def fit(audio,n):
    if audio.shape[0]==n: return audio
    if audio.shape[0]>n: return audio[:n]
    return np.vstack([audio,np.zeros((n-audio.shape[0],audio.shape[1]))])

def to_mono(a): return np.mean(a,axis=1) if a.ndim>1 else a

def as_stereo(a):
    if a.ndim==1: return np.column_stack([a,a])
    if a.shape[1]==1: return np.column_stack([a[:,0],a[:,0]])
    return a

def peak_guard(audio, ceiling=0.9998, label=""):
    pk = np.max(np.abs(audio))
    if pk > ceiling:
        g = ceiling/pk
        log(f"  Clip guard [{label}]: {20*np.log10(pk+1e-12):.2f}dBFS","WARN")
        return audio*g
    return audio

def rms_gain(audio, target_db=-18.0):
    rms = np.sqrt(np.mean(audio**2))
    return audio if rms<1e-9 else audio*(10**(target_db/20.0)/rms)

def save_quarter(audio, sr, path):
    save(audio[:audio.shape[0]//4], sr, path)

def _lufs(audio, sr):
    if HAS_LN:
        try: return float(pyln.Meter(sr).integrated_loudness(audio))
        except: pass
    return float(20*np.log10(np.sqrt(np.mean(audio**2))+1e-12))

def measure_lufs(audio, sr): return _lufs(audio, sr)

def measure_plr(audio, sr):
    lufs = measure_lufs(audio,sr); pk = 20*np.log10(np.max(np.abs(audio))+1e-12)
    return round(pk-lufs,2), round(lufs,2), round(pk,2)

def true_peak(audio):
    try:
        up = resample_poly(audio,4,1)
        return round(float(20*np.log10(np.max(np.abs(up))+1e-12)),3)
    except:
        return round(float(20*np.log10(np.max(np.abs(audio))+1e-12)),3)

def lra_measure(audio, sr):
    if not HAS_LN: return None
    m = pyln.Meter(sr); win = int(3*sr)
    src = audio
    if len(audio) > 60*sr:
        mid = len(audio)//3
        src = audio[mid:mid+60*sr]
    vals = []
    for i in range(0, len(src)-win, win):
        try:
            v = m.integrated_loudness(src[i:i+win])
            if not(np.isinf(v) or np.isnan(v)): vals.append(v)
        except: pass
    if len(vals) < 4: return None
    return round(float(np.percentile(vals,95)-np.percentile(vals,10)),2)

def lufs_shortterm(audio, sr):
    if not HAS_LN: return None
    m = pyln.Meter(sr); win = int(3*sr); vals = []
    for i in range(0, len(audio)-win, win):
        try:
            v = m.integrated_loudness(audio[i:i+win])
            if not(np.isinf(v) or np.isnan(v)): vals.append(v)
        except: pass
    return round(float(max(vals)),2) if vals else None

def check_correlation(audio, label=""):
    if audio.shape[1]<2: return audio
    corr = float(np.corrcoef(audio[:,0],audio[:,1])[0,1])
    if corr<0.5: log(f"  Correlation {corr:.3f} < 0.5 [{label}]","WARN")
    elif corr<0.7: log(f"  Correlation {corr:.3f} < 0.7 [{label}]","INFO")
    return audio

def fix_correlation(audio, target=0.5):
    if audio.shape[1]<2: return audio
    corr = float(np.corrcoef(audio[:,0],audio[:,1])[0,1])
    if corr >= target: return audio
    mono = to_mono(audio); blend = min(1.0, (target-corr)/target)
    out = np.zeros_like(audio)
    out[:,0] = audio[:,0]*(1-blend) + mono*blend
    out[:,1] = audio[:,1]*(1-blend) + mono*blend
    log(f"  Correlation fixed: {corr:.3f} -> {float(np.corrcoef(out[:,0],out[:,1])[0,1]):.3f}")
    return out

def find_active(audio, sr, threshold_db=-40.0):
    win = int(0.5*sr); thr = 10**(threshold_db/20.0); mono = to_mono(audio)
    for i in range(0, len(mono)-win, win//2):
        if np.sqrt(np.mean(mono[i:i+win]**2)) > thr: return i
    return 0

def avg_spectrum(audio, sr, win=4096, hop=1024):
    f,_,Z = signal.stft(to_mono(audio).astype(np.float32),fs=sr,nperseg=win,noverlap=win-hop,window='hann')
    return f, np.mean(np.abs(Z),axis=1)

def _band_energy(f, P, lo, hi):
    m = (f>=lo)&(f<hi)
    return float(10*np.log10(np.mean(P[m])+1e-12)) if m.any() else -100.0

def measure_bands(mono, sr):
    f,P = welch(mono,sr,nperseg=min(8192,len(mono)//4),window='hann')
    ref = _band_energy(f,P,800,1200)
    return {k:round(_band_energy(f,P,lo,hi)-ref,2) for k,(lo,hi) in zip(BAND_KEYS,BAND_RANGES)}, ref

def diagnose_audio(audio, sr, name=""):
    mono = to_mono(audio); n = audio.shape[0]
    diag = {"name":name,"duration_s":round(n/sr,1),"sample_rate":sr,"channels":audio.shape[1]}
    diag["lufs"]        = _lufs(audio,sr)
    diag["lufs_st"]     = lufs_shortterm(audio,sr)
    diag["lra"]         = lra_measure(audio,sr)
    diag["true_peak"]   = true_peak(audio)
    diag["sample_peak"] = round(float(20*np.log10(np.max(np.abs(audio))+1e-12)),3)
    diag["rms_db"]      = round(float(20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)),3)
    diag["crest"]       = round(diag["true_peak"]-diag["rms_db"],2)
    diag["plr"]         = round(diag["true_peak"]-diag["lufs"],2)
    f,P = welch(mono,sr,nperseg=min(8192,n//4),window='hann')
    ref1k = _band_energy(f,P,800,1200)
    diag["infrasonic_excess"] = round(_band_energy(f,P,5,30)-ref1k,1)
    diag["ultrasonic_level"]  = round(_band_energy(f,P,16000,min(20000,sr//2-100))-ref1k,1)
    if audio.shape[1]>=2:
        m=audio[:,0]+audio[:,1]; s=audio[:,0]-audio[:,1]
        diag["stereo_width"] = round(float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-9)),4)
        diag["correlation"]  = round(float(np.corrcoef(audio[:,0],audio[:,1])[0,1]),4)
        lp = signal.butter(4,120,btype='low',fs=sr,output='sos')
        sub_side=signal.sosfiltfilt(lp,s); sub_mid=signal.sosfiltfilt(lp,m)
        diag["sub_leak"] = round(float(np.sqrt(np.mean(sub_side**2))/(np.sqrt(np.mean(sub_mid**2))+1e-9)),5)
    else:
        diag["stereo_width"]=0.0; diag["correlation"]=1.0; diag["sub_leak"]=0.0
    bands, ref_level = measure_bands(mono,sr)
    diag["bands"] = bands; diag["ref_level_dBFS"] = round(ref_level,2)
    try:
        bp  = signal.butter(4,[40,min(4000,sr//2-100)],btype='band',fs=sr,output='sos')
        mbp = signal.sosfiltfilt(bp,mono.astype(np.float32))
        t,_ = librosa.beat.beat_track(y=mbp.astype(np.float32),sr=sr,units='time')
        diag["bpm"] = round(float(np.atleast_1d(t)[0]),1)
    except: diag["bpm"] = None
    try:
        ch  = librosa.feature.chroma_cqt(y=mono.astype(np.float32),sr=sr).mean(axis=1)
        maj = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
        mn  = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        nts = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        bs,bk,bm = -np.inf,0,'major'
        for r in range(12):
            for p,md in [(maj,'major'),(mn,'minor')]:
                sc=np.corrcoef(ch,np.roll(p,r))[0,1]
                if sc>bs: bs,bk,bm=sc,r,md
        diag["key"] = f"{nts[bk]} {bm} (conf {bs:.2f})"
    except: diag["key"] = None
    try:
        diag["centroid"] = round(float(np.mean(librosa.feature.spectral_centroid(
            y=mono.astype(np.float32),sr=sr))),0)
    except: diag["centroid"] = None
    return diag

def build_reference_profile(ref_dir):
    profile_path = os.path.join(ref_dir,"reference_profile.json")
    norm_dir = os.path.join(ref_dir,NORM_REF_SUBDIR)
    search = norm_dir if os.path.exists(norm_dir) and any(
        f.lower().endswith('.wav') for f in os.listdir(norm_dir)) else ref_dir
    wavs = [os.path.join(search,f) for f in os.listdir(search) if f.lower().endswith('.wav')]
    if not wavs: log("No reference WAVs found - using built-in profile.","WARN"); return _builtin_profile()
    log(f"Building fresh reference profile from {len(wavs)} tracks...")
    tracks = []
    for wav in sorted(wavs):
        try:
            audio,sr = sf.read(wav,always_2d=True); audio=audio.astype(np.float64)
            d = diagnose_audio(audio,sr,os.path.basename(wav)); tracks.append(d)
            log(f"  {os.path.basename(wav)[:50]}: LUFS={d['lufs']:.2f} Kick={d['bands']['kick_40_80']:+.1f}dB")
        except Exception as e: log(f"  Skipped {os.path.basename(wav)}: {e}","WARN")
    if not tracks: return _builtin_profile()
    avg = {}
    for k in ["lufs","true_peak","crest","plr","stereo_width","correlation","sub_leak","centroid"]:
        vals = [t[k] for t in tracks if t.get(k) is not None]
        avg[k] = round(float(np.mean(vals)),4) if vals else 0.0
    lra_vals = [t["lra"] for t in tracks if t.get("lra") is not None]
    avg["lra"] = round(float(np.mean(lra_vals)),4) if lra_vals else 4.66
    avg["bands"] = {}
    for bk in BAND_KEYS:
        vals = [t["bands"][bk] for t in tracks if bk in t.get("bands",{})]
        avg["bands"][bk] = round(float(np.mean(vals)),2) if vals else 0.0
    profile = {"tracks":tracks,"average":avg,"source":search,
               "built":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    try:
        with open(profile_path,'w') as f: json.dump(profile,f,indent=2)
        log(f"Reference profile saved: {profile_path}")
    except Exception as e: log(f"Could not save profile: {e}","WARN")
    return avg

def _builtin_profile():
    log("Using built-in underground profile (confirmed from 6 professional masters).","WARN")
    return {
        "lufs":-8.119,"true_peak":0.063,"crest":8.975,"plr":8.182,
        "lra":4.657,"stereo_width":0.1865,"correlation":0.9288,"sub_leak":0.0317,"centroid":2947.0,
        "bands":{"sub_20_40":14.18,"kick_40_80":26.70,"bass_80_160":17.13,
                 "low_mid_160_300":11.32,"mid_300_800":5.96,"upper_800_2k":-1.63,
                 "presence_2k_5k":-6.61,"high_5k_10k":-9.72,"air_10k_20k":-18.19}
    }

def derive_corrections(song_diag, ref_avg):
    c = {}
    bd = song_diag["bands"]; rb = ref_avg["bands"]
    c["band_corrections"] = {k:round(rb[k]-bd[k],2) for k in BAND_KEYS}
    c["kick_deficit"]      = round(rb["kick_40_80"]-bd["kick_40_80"],2)
    c["sub_deficit"]       = round(rb["sub_20_40"]-bd["sub_20_40"],2)
    c["air_excess"]        = round(bd["air_10k_20k"]-rb["air_10k_20k"],2)
    c["presence_excess"]   = round(bd["presence_2k_5k"]-rb["presence_2k_5k"],2)
    song_cen = song_diag.get("centroid") or ref_avg.get("centroid") or 2947
    ref_cen  = ref_avg.get("centroid") or 2947
    c["brightness_excess"] = round(float(song_cen - ref_cen), 0)
    c["needs_hp30hz"]        = song_diag["infrasonic_excess"] > INFRA_HP30_THR
    c["infrasonic_severity"] = song_diag["infrasonic_excess"]
    c["sub_too_wide"]        = song_diag["sub_leak"] > 0.05
    c["corr_low"]            = song_diag["correlation"] < 0.90
    c["lufs_deficit"]        = round((ref_avg.get("lufs") or -8.12) - song_diag["lufs"],2)
    return c

def print_diagnostics_report(songs_diag, ref_avg):
    SEP = "=" * 76
    print(f"\n{SEP}")
    print(f"  DIAGNOSTIC REPORT: YOUR SONGS vs PROFESSIONAL REFERENCE AVERAGE")
    print(SEP)
    print(f"  Reference: {ref_avg.get('lufs',-8.12):.2f} LUFS | Kick {ref_avg['bands']['kick_40_80']:+.2f}dB | Air {ref_avg['bands']['air_10k_20k']:+.2f}dB | Centroid {ref_avg.get('centroid',2947):.0f}Hz")
    print(SEP)
    print(f"  {'Song':<38} {'LUFS':>6} {'Crest':>6} {'PLR':>6} {'Kick':>7} {'Air':>7} {'Infra':>7} {'Ult':>7}")
    print(f"  {'REFERENCE AVERAGE':<38} {ref_avg.get('lufs',-8.12):>6.1f} {ref_avg.get('crest',8.97):>6.1f} {ref_avg.get('plr',8.18):>6.1f} {ref_avg['bands']['kick_40_80']:>+7.1f} {ref_avg['bands']['air_10k_20k']:>+7.1f} {'N/A':>7} {'N/A':>7}")
    print("  "+"-"*74)
    for d in songs_diag:
        flags = []
        if d["infrasonic_excess"]>INFRA_HP30_THR: flags.append("INFRA")
        if d.get("ultrasonic_level",0)>-25: flags.append("CODEC")
        if d["correlation"]<0.90: flags.append("CORR")
        if d["sub_leak"]>0.05: flags.append("SUB")
        flag_str = " ["+",".join(flags)+"]" if flags else ""
        print(f"  {d['name'][:38]:<38} {d['lufs']:>6.1f} {d['crest']:>6.1f} {d['plr']:>6.1f} "
              f"{d['bands']['kick_40_80']:>+7.1f} {d['bands']['air_10k_20k']:>+7.1f} "
              f"{d['infrasonic_excess']:>+7.1f} {d.get('ultrasonic_level',0):>+7.1f}{flag_str}")
    print(f"\n{SEP}")
    all_infrared = [d for d in songs_diag if d["infrasonic_excess"]>INFRA_HP30_THR]
    if all_infrared:
        print(f"  INFRASONIC AI ARTEFACTS: {len(all_infrared)}/{len(songs_diag)} songs -> HP@30Hz will be applied")
        for d in all_infrared:
            sev = "CRITICAL" if d["infrasonic_excess"]>0 else "ELEVATED"
            print(f"    {d['name']}: {d['infrasonic_excess']:+.1f}dB [{sev}]")
    kick_issues = [(d,ref_avg['bands']['kick_40_80']-d['bands']['kick_40_80'])
                   for d in songs_diag if ref_avg['bands']['kick_40_80']-d['bands']['kick_40_80']>2]
    if kick_issues:
        print(f"  KICK DEFICIT 40-80Hz:")
        for d,deficit in sorted(kick_issues,key=lambda x:-x[1]):
            sev = "CRITICAL" if deficit>7 else "HIGH" if deficit>4 else "MODERATE"
            print(f"    {d['name']}: {deficit:+.1f}dB [{sev}]")
    print(SEP)

def peaking_sos(hz, db, Q, sr):
    db=np.clip(db,-MAX_EQ_DB,MAX_EQ_DB); A=10**(db/40.0)
    w0=2*np.pi*hz/sr; alp=np.sin(w0)/(2.0*Q)
    b0=1+alp*A; b1=-2*np.cos(w0); b2=1-alp*A
    a0=1+alp/A; a1=-2*np.cos(w0); a2=1-alp/A
    return np.array([[b0/a0,b1/a0,b2/a0,1.0,a1/a0,a2/a0]])

def apply_eq(audio, cuts, sr):
    out = audio.copy()
    for hz,db,Q in cuts:
        if hz<=0 or hz>=sr//2-100: continue
        sos = peaking_sos(hz,db,Q,sr)
        for ch in range(out.shape[1]): out[:,ch]=signal.sosfiltfilt(sos,out[:,ch])
    return peak_guard(out,label="eq")

def hp_filter(audio, hz, order, sr):
    sos = signal.butter(order,hz,btype='high',fs=sr,output='sos')
    out = audio.copy()
    for ch in range(out.shape[1]): out[:,ch]=signal.sosfiltfilt(sos,out[:,ch])
    return out

def lp_filter(audio, hz, order, sr):
    hz = min(hz,sr//2-200)
    sos = signal.butter(order,hz,btype='low',fs=sr,output='sos')
    out = audio.copy()
    for ch in range(out.shape[1]): out[:,ch]=signal.sosfiltfilt(sos,out[:,ch])
    return out

def underground_eq(audio, sr):
    return apply_eq(audio,[
        (30,1.8,1.0),(60,2.0,1.5),(90,1.5,1.5),(130,1.0,2.0),(230,0.8,2.0),
        (400,-1.0,2.0),(600,-0.5,2.0),(3500,-1.2,2.0),(7500,-1.5,2.0),(15000,-1.8,2.0),
    ],sr)

def targeted_spectral_eq(audio, sr, corrections, ref_avg):
    cuts = []
    bk_def = corrections.get("kick_deficit",0)
    if bk_def > 0.5:
        for hz,portion,headroom in [(50,0.4,0.0),(60,0.5,1.0),(70,0.3,0.0)]:
            db = min(bk_def*portion, MAX_EQ_DB-headroom)
            if db > 0.3: cuts.append((hz,db,2.0))
    sb_def = corrections.get("sub_deficit",0)
    if sb_def > 1.0: cuts.append((30,min(sb_def*0.4,MAX_EQ_DB),1.5))
    air_exc = corrections.get("air_excess",0)
    if air_exc > 1.0: cuts.append((15000,-min(air_exc*0.5,MAX_EQ_DB),2.0))
    if air_exc > 2.0: cuts.append((12000,-min(air_exc*0.3,MAX_EQ_DB),2.0))
    pres_exc = corrections.get("presence_excess",0)
    if pres_exc > 1.0: cuts.append((3500,-min(pres_exc*0.4,MAX_EQ_DB),2.0))
    bright = corrections.get("brightness_excess",0)
    if bright > 1000: cuts.append((8000,-min(bright/1000*0.8,MAX_EQ_DB),2.0))
    return apply_eq(audio,cuts,sr) if cuts else audio

def profile_eq(audio, sr, ref_avg):
    bands = ref_avg.get("bands",{}); f_s,s_s = avg_spectrum(audio,sr)
    r1k = np.mean(s_s[(f_s>=800)&(f_s<1200)]); cuts = []
    targets = [(20,40,bands.get("sub_20_40",14.18),30,1.0),
               (40,80,bands.get("kick_40_80",26.70),60,1.5),
               (80,160,bands.get("bass_80_160",17.13),120,1.5),
               (160,300,bands.get("low_mid_160_300",11.32),230,2.0),
               (2000,5000,bands.get("presence_2k_5k",-6.61),3500,2.0),
               (5000,10000,bands.get("high_5k_10k",-9.72),7500,2.0),
               (10000,20000,bands.get("air_10k_20k",-18.19),15000,2.0)]
    for lo,hi,tgt,ctr,Q in targets:
        mask=(f_s>=lo)&(f_s<hi)
        if not mask.any(): continue
        corr=np.clip((tgt-20*np.log10((np.mean(s_s[mask])+1e-12)/(r1k+1e-12)))*0.5,-MAX_EQ_DB,MAX_EQ_DB)
        if abs(corr)>0.3: cuts.append((ctr,corr,Q))
    return apply_eq(audio,cuts,sr) if cuts else audio

def ref_track_eq(audio, sr, ref_audio, ref_sr):
    if ref_audio is None: return audio
    f_s,s_s = avg_spectrum(audio,sr); f_r,s_r = avg_spectrum(ref_audio,ref_sr)
    s_ri = interp1d(f_r,s_r,kind='linear',bounds_error=False,fill_value=s_r[-1])(f_s)
    rdb  = np.clip(20*np.log10((s_ri+1e-12)/(s_s+1e-12)),-MAX_EQ_DB,MAX_EQ_DB)
    out  = audio.copy()
    for ch in range(audio.shape[1]):
        _,_,Z = signal.stft(audio[:,ch],fs=sr,nperseg=4096,noverlap=2048,window='hann')
        _,x  = signal.istft(Z*10**(rdb[:,np.newaxis]/20.0),fs=sr,nperseg=4096,noverlap=2048,window='hann')
        n = audio.shape[0]; out[:,ch] = x[:n] if len(x)>=n else np.pad(x,(0,n-len(x)))
    return peak_guard(out,label="ref_eq")

def ms_widen(audio, sr, width_pct=4.0):
    if audio.shape[1]<2: return audio
    mid=(audio[:,0]+audio[:,1])*0.5; side=(audio[:,0]-audio[:,1])*0.5*(1.0+width_pct/100.0)
    out=np.zeros_like(audio); out[:,0]=mid+side; out[:,1]=mid-side
    return check_correlation(peak_guard(out,label="ms_widen"),"ms_widen")

def compressor(audio, sr, thr_db=-18.0, ratio=2.0, att_ms=40.0, rel_ms=200.0):
    n,nch = audio.shape; thr = 10**(thr_db/20.0)
    att = np.exp(-1.0/(sr*att_ms/1000.0)); rel = np.exp(-1.0/(sr*rel_ms/1000.0))
    min_g = 10**(-MAX_GR_DB/20.0)
    lvl = np.max(np.abs(audio),axis=1)
    gain = np.ones(n); g = 1.0
    for i in range(n):
        if lvl[i] < 1e-9: gain[i] = g = 1.0; continue
        tgt = max(min_g,thr*(lvl[i]/thr)**(1.0/ratio)/(lvl[i]+1e-12)) if lvl[i]>thr else 1.0
        g = att*g+(1-att)*tgt if tgt<g else rel*g+(1-rel)*tgt
        gain[i] = g
    return peak_guard(audio*gain[:,np.newaxis],label="comp")

def multiband_comp(audio, sr):
    result = np.zeros_like(audio)
    for lo,hi,ratio,att,rel in [(20,120,2.0,50,230),(120,5000,1.5,40,200)]:
        hi = min(hi,sr//2-100)
        if lo>=hi: continue
        lp = signal.butter(4,hi,btype='low',fs=sr,output='sos')
        hp = signal.butter(4,lo,btype='high',fs=sr,output='sos')
        band = audio.copy()
        for ch in range(audio.shape[1]):
            band[:,ch] = signal.sosfiltfilt(lp,signal.sosfiltfilt(hp,band[:,ch]))
        result += compressor(band,sr,thr_db=-20.0,ratio=ratio,att_ms=att,rel_ms=rel)
    return peak_guard(result,label="multiband")

def tube_saturate(audio, wet=0.08):
    dry = audio.copy(); sat = np.sign(audio)*(1.0-np.exp(-np.abs(audio)*2.5))
    return peak_guard(dry*(1.0-wet)+sat*wet,label="tube_sat")

def soft_clip(audio, knee=0.7, ceiling=0.910):
    out = audio.copy(); mask = np.abs(audio)>knee; sign = np.sign(audio[mask])
    exc = (np.abs(audio[mask])-knee)/(1.0-knee)
    out[mask] = sign*(knee+(ceiling-knee)*np.tanh(exc)); return out

def hard_limit(audio, ceiling_db=TRUE_PEAK_DB):
    ceil = 10**(ceiling_db/20.0); pk = np.max(np.abs(audio))
    return audio*(ceil/pk) if pk>ceil else audio

def noise_floor(audio, sr, level_db=-62.0):
    n,nch = audio.shape; amp = 10**(level_db/20.0)
    seed = abs(hash((n,nch,round(amp,6)))) % (2**31)
    rng  = np.random.default_rng(seed)
    hp = signal.butter(2,40,btype='high',fs=sr,output='sos')
    lp = signal.butter(2,min(18000,sr//2-200),btype='low',fs=sr,output='sos')
    out = np.zeros_like(audio)
    for ch in range(nch):
        x = rng.standard_normal(n)*amp
        x = signal.sosfiltfilt(hp,x); x = signal.sosfiltfilt(lp,x); out[:,ch]=x
    return peak_guard(audio+out,label="noise_floor")

def stereo_move(audio, sr, rate_hz=0.07, depth=0.03):
    if audio.shape[1]<2: return audio
    t = np.arange(audio.shape[0])/sr; lfo = 1.0+depth*np.sin(2.0*np.pi*rate_hz*t)
    mid=(audio[:,0]+audio[:,1])*0.5; side=(audio[:,0]-audio[:,1])*0.5*lfo
    out=np.zeros_like(audio); out[:,0]=mid+side; out[:,1]=mid-side
    out = fix_correlation(out, target=0.5)
    return peak_guard(out,label="stereo_move")

def mono_sub(audio, sr, xover_hz=100.0):
    if audio.shape[1]<2: return audio
    lp = signal.butter(4,xover_hz,btype='low',fs=sr,output='sos')
    hp = signal.butter(4,xover_hz,btype='high',fs=sr,output='sos')
    sub = signal.sosfiltfilt(lp,(audio[:,0]+audio[:,1])*0.5)
    out = np.zeros_like(audio)
    for ch in range(audio.shape[1]): out[:,ch]=signal.sosfiltfilt(hp,audio[:,ch])+sub
    return out

def pan(audio, v):
    if audio.shape[1]<2: return audio
    out = audio.copy()
    if v>0: out[:,0]*=(1.0-v)
    elif v<0: out[:,1]*=(1.0+v)
    return out

def limit_lufs(audio, sr, target, ceiling_db=TRUE_PEAK_DB, max_gain_db=14.0):
    cur = measure_lufs(audio,sr)
    if np.isinf(cur) or np.isnan(cur): return audio
    gain_db = min(target-cur,max_gain_db); audio = audio*10**(gain_db/20.0)
    ceiling = 10**(ceiling_db/20.0); pk = np.max(np.abs(audio))
    if pk>ceiling: audio = audio*(ceiling/pk)
    plr,_,_ = measure_plr(audio,sr)
    if plr<MIN_PLR: log(f"  PLR {plr:.1f}dB below min {MIN_PLR}dB","WARN")
    return audio

def noise_gate(audio, sr, threshold_db=-65.0):
    thr = 10**(threshold_db/20.0)
    att = np.exp(-1.0/(sr*0.010)); rel = np.exp(-1.0/(sr*0.100))
    lvl = np.max(np.abs(audio),axis=1)
    gain = np.zeros(audio.shape[0]); g = 0.0
    for i in range(len(lvl)):
        tgt = 1.0 if lvl[i]>thr else 0.0
        g = att*g+(1-att)*tgt if tgt>g else rel*g+(1-rel)*tgt
        gain[i] = g
    return audio*gain[:,np.newaxis]

def ai_resonance_remove(audio, sr, max_notches=8):
    seg = audio[:min(audio.shape[0],sr*30)]; mono = to_mono(seg).astype(np.float32)
    f,_,Z = signal.stft(mono,fs=sr,nperseg=4096,noverlap=3072,window='hann')
    mag = np.mean(np.abs(Z),axis=1); mask = (f>=300)&(f<=min(16000,sr//2-200))
    f_r=f[mask]; mag_r=mag[mask]; smooth=uniform_filter1d(mag_r,size=20)
    time_mag=np.abs(Z[mask,:]); peaks=[]
    for i in range(5,len(f_r)-5):
        if mag_r[i]>smooth[i]*2.0:
            cv=float(np.std(time_mag[i,:])/(np.mean(time_mag[i,:])+1e-9))
            if cv<0.5: peaks.append((f_r[i],float(mag_r[i])))
    peaks.sort(key=lambda x:-x[1]); peaks=peaks[:max_notches]
    if not peaks: return audio
    result=audio.copy()
    for freq,_ in peaks:
        sos=peaking_sos(freq,-4.0,3.0,sr)
        for ch in range(result.shape[1]): result[:,ch]=signal.sosfiltfilt(sos,result[:,ch])
        log(f"     Notch: {freq:.0f}Hz Q=3 -4dB")
    return peak_guard(result,label="resonance_notch")

def deess(audio, sr):
    hp = signal.butter(4,6000,btype='high',fs=sr,output='sos')
    det = np.zeros(audio.shape[0])
    for ch in range(audio.shape[1]): det+=signal.sosfiltfilt(hp,audio[:,ch])**2
    det=np.sqrt(det/audio.shape[1]); thr=10**(-22.0/20.0); ratio=4.5
    att=np.exp(-1.0/(sr*0.001)); rel=np.exp(-1.0/(sr*0.050))
    gain=np.ones_like(det); g=1.0
    for i in range(len(det)):
        lvl=det[i]; tgt=(thr*(lvl/thr)**(1.0/ratio)/(lvl+1e-12)) if lvl>thr else 1.0
        g=att*g+(1-att)*tgt if tgt<g else rel*g+(1-rel)*tgt; gain[i]=g
    hp_sos=signal.butter(4,6000,btype='high',fs=sr,output='sos')
    lp_sos=signal.butter(4,6000,btype='low',fs=sr,output='sos')
    out=audio.copy()
    for ch in range(audio.shape[1]):
        hi=signal.sosfiltfilt(hp_sos,audio[:,ch])*gain
        lo=signal.sosfiltfilt(lp_sos,audio[:,ch]); out[:,ch]=lo+hi
    return peak_guard(out,label="deess")

def virtual_analog_strip(audio, sr, console):
    if console=="SSL":
        audio=hp_filter(audio,25,4,sr); audio=apply_eq(audio,[(6000,0.3,2.0)],sr)
        audio=tube_saturate(audio,wet=0.04)
    elif console=="API":
        audio=hp_filter(audio,30,2,sr); audio=apply_eq(audio,[(2500,0.3,2.0)],sr)
        audio=tube_saturate(audio,wet=0.05)
    else:
        audio=hp_filter(audio,15,2,sr); audio=apply_eq(audio,[(250,0.2,2.0),(8000,-0.2,2.0)],sr)
        audio=tube_saturate(audio,wet=0.06)
    return peak_guard(audio,label=f"console_{console}")

def fingerprint(mono, sr):
    fmax = min(FP_FMAX,sr//2-200)
    f,_,Z = signal.stft(mono,fs=sr,nperseg=4096,noverlap=3072,window='hann')
    avg = np.mean(np.abs(Z),axis=1); mask = (f>=FP_FMIN)&(f<=fmax)
    bf  = np.linspace(FP_FMIN,fmax,FP_BINS)
    s   = interp1d(f[mask],avg[mask],kind='linear',bounds_error=False,fill_value=0.0)(bf)
    lm  = minimum_filter1d(s,size=FP_DWIN); raw=s-lm; pk=raw.max()
    return {"norm":raw/pk if pk>0 else raw.copy(),"raw":raw,"bf":bf,"peak":float(pk)}

def fp_score(fp):
    top8 = np.sort(fp["norm"])[-8:]
    return float(1.0/(1.0+np.exp(-(top8.mean()-0.35)*8.0)))

def save_fp_plot(fp_b, fp_a, path):
    fig,axes=plt.subplots(3,1,figsize=(14,9),facecolor='#0d1117')
    fig.suptitle("AI Fingerprint Before vs After",color='white',fontsize=12)
    x=np.arange(FP_BINS)
    for ax,d,c,l in [(axes[0],fp_b["norm"],'#f85149','Before'),(axes[1],fp_a["norm"],'#3fb950','After')]:
        ax.set_facecolor('#161b22'); ax.tick_params(colors='#8b949e')
        ax.bar(x,d,color=c,alpha=0.85,width=0.85); ax.set_title(l,color=c,fontsize=10); ax.set_ylim(0,1.08)
    delta=fp_a["norm"]-fp_b["norm"]; axes[2].set_facecolor('#161b22'); axes[2].tick_params(colors='#8b949e')
    axes[2].bar(x,delta,color=['#3fb950' if d<0 else '#f85149' for d in delta],alpha=0.85,width=0.85)
    axes[2].axhline(0,color='#8b949e',lw=0.8); axes[2].set_title('Delta (green=improved)',color='#8b949e',fontsize=10)
    plt.tight_layout(); plt.savefig(path,dpi=120,bbox_inches='tight',facecolor='#0d1117'); plt.close()

def letssubmit_check(short_path, api_key):
    if api_key and HAS_REQ:
        try:
            with open(short_path,'rb') as f:
                r=requests.post('https://file.io',files={'file':f},data={'expires':'1d'},timeout=90)
            if r.status_code==200:
                url=r.json().get('link')
                if url:
                    r2=requests.post('https://api.letssubmit.com/analyze_song',
                        headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
                        json={'file_url':url},timeout=180)
                    if r2.status_code==200: res=r2.json(); log(f"  LetsSubmit: {res}"); return res
        except Exception as e: log(f"  LetsSubmit error: {e}","WARN")
    log(f"  Manual check: {short_path}")
    return None

def p0(song_base, original_wav, paths, ls_key, corrections):
    section("P0  AI IDENTIFICATION REMOVAL")
    audio,sr,info = load(original_wav); n_mix=audio.shape[0]; sname=os.path.basename(song_base)
    rep = {"pipeline":"P0","song":sname,"sample_rate":sr}
    log("P0 [1/6] Metadata strip...")
    if HAS_MUT:
        try:
            tags=ID3(original_wav)
            ai=[k for k in list(tags.keys()) if any(w in k.lower() for w in ['suno','udio','ai','generated','encoder'])]
            for k in ai: del tags[k]
            if ai: tags.save(); log(f"  Removed {len(ai)} AI metadata tags.")
        except: pass
    log("P0 [2/6] LP@18kHz (AI EnCodec watermark removal)...")
    audio = lp_filter(audio,18000,6,sr)
    log("P0 [3/6] HP@18Hz (infrasonic removal)...")
    audio = hp_filter(audio,18,2,sr)
    log(f"P0 [4/6] Infrasonic scan ({corrections['infrasonic_severity']:+.1f}dB, threshold {INFRA_HP30_THR}dB)...")
    if corrections.get("needs_hp30hz",False):
        log(f"  Infrasonic exceeds threshold - applying HP@30Hz")
        audio = hp_filter(audio,30,4,sr)
    else:
        log(f"  Infrasonic OK - no additional HP needed")
    log("P0 [5/6] AI fingerprint scan...")
    mono=to_mono(audio); fp=fingerprint(mono,sr); sc=fp_score(fp)
    rep["ai_score_pct"]=round(sc*100,1)
    log(f"  Internal AI score: {sc*100:.1f}%")
    log("P0 [6/6] Shortened file + Demucs stem separation...")
    short_name=f"{sname}_shortened.wav"
    short_song=os.path.join(song_base,"P0_DETECTION","shortened",short_name)
    short_root=os.path.join(paths["shortened"],short_name)
    save_quarter(audio,sr,short_song); shutil.copy2(short_song,short_root)
    letssubmit_check(short_song,ls_key)
    raw_dir=os.path.join(song_base,"P1_STEMCLEANING","stems_raw")
    stems=_run_demucs(original_wav,raw_dir)
    if not stems: log("  Demucs failed.","ERROR"); return None,None,info,sr,n_mix
    for sn,sp in stems.items():
        a,ssr,_=load(sp); sc2=fp_score(fingerprint(to_mono(a),ssr))
        log(f"  {sn:<12} AI: {sc2*100:.1f}%")
    rep["stems"]=list(stems.keys())
    _report(os.path.join(song_base,"P0_DETECTION","detection_reports","p0_report.json"),rep)
    section("P0 COMPLETE"); return stems,fp,info,sr,n_mix

def _run_demucs(wav, out_dir):
    r=subprocess.run([sys.executable,"-m","demucs","-n","htdemucs_6s",
                      "--float32","--clip-mode","clamp","--shifts","2","-o",out_dir,wav],
                     capture_output=True,text=True)
    if r.returncode!=0: log(f"  Demucs: {r.stderr[:300]}","ERROR"); return None
    base = os.path.splitext(os.path.basename(wav))[0]
    sd = os.path.join(out_dir,"htdemucs_6s",base)
    if not os.path.exists(sd): log(f"  Demucs output not found: {sd}","ERROR"); return None
    stems={}
    for sn in ["drums","bass","vocals","guitar","piano","other"]:
        p=os.path.join(sd,f"{sn}.wav")
        if os.path.exists(p): stems[sn]=p
    log(f"  Stems: {list(stems.keys())}"); return stems

def p1(song_base, stems_raw, mix_audio, sr, mix_info, n_mix):
    section("P1  STEM CLEANING")
    cdir=os.path.join(song_base,"P1_STEMCLEANING","stems_cleaned")
    cleaned={}; rep={"pipeline":"P1","stems":{}}; bpm=None
    for sn,sp in stems_raw.items():
        log(f"P1  [{sn}]")
        stem,ssr,_=load(sp)
        if ssr!=sr:
            log(f"     Resampling {ssr}->{sr}Hz")
            stem=as_stereo(librosa.resample(to_mono(stem).astype(np.float32),orig_sr=ssr,target_sr=sr))
        stem=fit(stem,n_mix)
        stem-=np.mean(stem,axis=0)
        stem=hp_filter(stem,5,2,sr)
        stem,nc=_remove_clicks_spline(stem)
        stem,lag=_phase_align(stem,mix_audio,sr)
        stem=fit(stem,n_mix)
        stem=noise_gate(stem,sr,-65.0)
        stem=ai_resonance_remove(stem,sr,8)
        if sn=="vocals": stem=deess(stem,sr)
        stem=noise_floor(stem,sr,-62.0)
        stem=stereo_move(stem,sr,0.07,0.02)
        if bpm is None:
            bp=signal.butter(4,[40,min(4000,sr//2-100)],btype='band',fs=sr,output='sos')
            mbp=signal.sosfiltfilt(bp,to_mono(stem).astype(np.float32))
            t,_=librosa.beat.beat_track(y=mbp.astype(np.float32),sr=sr,units='time')
            bpm=float(np.atleast_1d(t)[0]) or 120.0
        stem,bpm,ns=_quantize(stem,sr,bpm)
        stem=rms_gain(stem,-18.0)
        stem=peak_guard(stem,0.8912,f"post-rms-{sn}")
        stem=mono_sub(stem,sr,100.0)
        stem=peak_guard(stem,0.8912,f"pre-console-{sn}")
        stem=fit(stem,n_mix)
        console=CONSOLE_MAP.get(sn,"Neve")
        stem=virtual_analog_strip(stem,sr,console)
        log(f"     [{console}] clicks={int(nc)} lag={lag/sr*1000:.1f}ms bpm={bpm:.1f} shifts={int(ns)}")
        stem=peak_guard(stem); stem=fit(stem,n_mix)
        out=os.path.join(cdir,f"{sn}.wav"); save(stem,sr,out)
        cleaned[sn]=out
        rep["stems"][sn]={"clicks":int(nc),"lag_ms":round(float(lag/sr*1000),2),
                          "bpm":round(float(bpm or 0),2),"shifts":int(ns),"console":console}
    _report(os.path.join(song_base,"P1_STEMCLEANING","alignment_reports","p1_report.json"),rep)
    section("P1 COMPLETE"); return cleaned,bpm

def _remove_clicks_spline(audio, thr=0.97):
    n,nch=audio.shape; out=audio.copy(); total=0
    for ch in range(nch):
        d=out[:,ch]; cl=np.abs(d)>thr; diff=np.diff(cl.astype(int),prepend=0,append=0)
        for s,e in zip(np.where(diff==1)[0],np.where(diff==-1)[0]):
            if s>1 and e<n-1:
                pts=[max(0,s-2),s-1,e,min(n-1,e+1)]; vals=[d[p] for p in pts]
                try:
                    cs=CubicSpline(pts,vals); d[s:e]=cs(np.arange(s,e))
                except: d[s:e]=np.interp(np.arange(s,e),[s-1,e],[d[s-1],d[e]])
                total+=(e-s)
        out[:,ch]=d
    return out, int(total)

def _phase_align(stem, mix, sr):
    start = find_active(mix,sr); ml = int(sr*0.15)
    seg = min(stem.shape[0]-start, mix.shape[0]-start, sr*15)
    if seg <= 0: return stem, 0
    xc  = signal.correlate(to_mono(mix)[start:start+seg],to_mono(stem)[start:start+seg],mode='full')
    lag = int(np.clip(signal.correlation_lags(seg,seg,mode='full')[np.argmax(xc)],-ml,ml))
    if lag==0: return stem, 0
    n,nch=stem.shape
    if lag>0: return np.vstack([np.zeros((lag,nch)),stem[:-lag]]), lag
    return np.vstack([stem[-lag:],np.zeros((-lag,nch))]), lag

def _quantize(audio, sr, bpm=None):
    n,nch=audio.shape; mono=to_mono(audio).astype(np.float32)
    if not bpm:
        t,_=librosa.beat.beat_track(y=mono,sr=sr,units='time'); bpm=float(np.atleast_1d(t)[0])
    if bpm<=0 or bpm>300: return audio,bpm,0
    cell=(60.0/bpm/GRID_DIV)*sr; maxs=int(cell/2)
    onsets=librosa.onset.onset_detect(y=mono,sr=sr,units='samples',hop_length=256,
        backtrack=True,pre_max=3,post_max=3,pre_avg=3,post_avg=5,delta=0.07,wait=10)
    res=audio.copy(); cum=0; ns=0; fo=np.linspace(1,0,CF_LEN); fi=np.linspace(0,1,CF_LEN)
    for ow in onsets:
        o=int(ow+cum); sh=int(round(o/cell)*cell)-o
        if o<0 or o>=n or abs(sh)>maxs or sh==0: continue
        pos=max(0,o-CF_LEN//2)
        for ch in range(nch):
            a_=res[pos:min(n,pos+CF_LEN),ch]; b_=res[max(0,pos+sh):min(n,pos+sh+CF_LEN),ch]
            bl=min(len(a_),len(b_),CF_LEN)
            if bl>=4: res[pos:pos+bl,ch]=a_[:bl]*fo[:bl]+b_[:bl]*fi[:bl]
        cum+=sh; ns+=1
    return res, bpm, int(ns)

def p2(song_base, cleaned_stems, mix_audio, sr, mix_info, n_mix,
       ref_audio, ref_sr, ref_avg, corrections, bpm):
    section("P2  MIXING")
    spdir=os.path.join(song_base,"P2_MIXING","stems_processed")
    sname=os.path.basename(song_base); bus=np.zeros((n_mix,2)); rep={"pipeline":"P2","stems":{}}
    kick_env=None
    kick_src=cleaned_stems.get("drums") or cleaned_stems.get("kick")
    if kick_src:
        ka,_,_=load(kick_src); km=to_mono(ka)
        lp=signal.butter(4,200,btype='low',fs=sr,output='sos')
        kick_lp=signal.sosfiltfilt(lp,km); kick_env=_kick_envelope(kick_lp,sr,bpm)
        log(f"P2  Kick sidechain active (18ms att, 60% beat release @ {bpm:.1f}BPM)")
    for sn,sp in cleaned_stems.items():
        log(f"P2  [{sn}]")
        stem=fit(load(sp)[0],n_mix); stem=rms_gain(stem,-18.0)
        stem=apply_eq(stem,_stem_eq_cuts(sn),sr)
        stem=stem*STEM_VOL.get(sn,0.70); stem=pan(stem,STEM_PAN.get(sn,0.0))
        stem=compressor(stem,sr,-18.0,1.8,50.0,200.0); stem=tube_saturate(stem,0.04)
        if kick_env is not None and sn not in ("drums","kick"):
            stem=_apply_sidechain(stem,kick_env,2.0)
        stem=peak_guard(stem); stem=fit(stem,n_mix)
        bus+=stem; bus=peak_guard(bus,label="bus_sum")
        save(stem,sr,os.path.join(spdir,f"{sn}_processed.wav"))
        rep["stems"][sn]={"vol":STEM_VOL.get(sn,0.70),"pan":STEM_PAN.get(sn,0.0)}
    bus=apply_eq(bus,[(280,-0.8,2.0),(500,-0.6,1.5)],sr)
    bus=compressor(bus,sr,-15.0,1.3,60.0,250.0)
    bus=underground_eq(bus,sr)
    if ref_audio is not None: bus=ref_track_eq(bus,sr,ref_audio,ref_sr)
    else: bus=profile_eq(bus,sr,ref_avg)
    bus=mono_sub(bus,sr,100.0); bus=noise_floor(bus,sr,-64.0)
    pk=np.max(np.abs(bus))
    if pk>0: bus=bus*(10**(MIX_CEILING_DB/20.0)/pk)
    bus=peak_guard(bus); bus=fit(bus,n_mix); bus=check_correlation(bus,"P2_output")
    plr,lufs,pk_db=measure_plr(bus,sr)
    rep.update({"lufs":round(lufs,2),"peak_db":round(pk_db,2),"plr_db":plr})
    log(f"P2  LUFS={lufs:.1f} Peak={pk_db:.1f}dBFS PLR={plr:.1f}dB")
    pm=os.path.join(song_base,"P2_MIXING","pre_master",f"{sname}_premix.wav"); save(bus,sr,pm)
    save(np.repeat(np.mean(bus,axis=1,keepdims=True),2,axis=1),sr,
         os.path.join(song_base,"P2_MIXING","mono_check",f"{sname}_mono.wav"))
    _report(os.path.join(song_base,"P2_MIXING","mix_reports","p2_report.json"),rep)
    section("P2 COMPLETE"); return pm,bus

def _kick_envelope(km, sr, bpm):
    beat_s=60.0/max(bpm,60.0); att=np.exp(-1.0/(sr*0.018)); rel=np.exp(-1.0/(sr*beat_s*0.60))
    env=np.zeros(len(km)); g=0.0
    for i in range(len(km)):
        tgt=abs(km[i]); g=att*g+(1-att)*tgt if tgt>g else rel*g+(1-rel)*tgt; env[i]=g
    mx=env.max(); return env/mx if mx>0 else env

def _apply_sidechain(audio, envelope, depth_db=2.0):
    min_g=10**(-depth_db/20.0); gain=1.0-(1.0-min_g)*envelope[:audio.shape[0]]
    gain=np.clip(gain,min_g,1.0); return audio*gain[:,np.newaxis]

def _stem_eq_cuts(sn):
    return {"kick":[(300,-1.0,2.0),(500,-0.8,1.5)],"bass":[(300,-1.0,2.0),(500,-0.8,1.5)],
            "drums":[(200,-0.8,2.0),(3500,-0.8,2.0)],"guitar":[(300,-0.6,2.0),(5000,0.5,2.0)],
            "piano":[(300,-0.6,2.0),(5000,0.5,2.0)],"other":[(300,-0.6,2.0)],
            "vocals":[(200,-0.8,2.0),(3000,0.5,2.0)]}.get(sn,[])

def p3(song_base, premix_path, mix_audio, sr, mix_info, n_mix,
       ref_audio, ref_sr, ref_avg, corrections, genre, collection_dir, shortened_root):
    section("P3  MASTERING")
    sname=os.path.basename(song_base)
    target_lufs=GENRE_LUFS.get(genre,GENRE_LUFS["underground"])
    crest_min=GENRE_CREST_MIN.get(genre,8.0)
    audio=fit(load(premix_path)[0],n_mix)
    rep={"pipeline":"P3","genre":genre,"targets":{"lufs":target_lufs,"peak":TRUE_PEAK_DB}}
    plr_in,lufs_in,pk_in=measure_plr(audio,sr)
    log(f"P3  Genre={genre} Target={target_lufs}LUFS CrestMin={crest_min}dB")
    log(f"P3  Input: LUFS={lufs_in:.1f} Peak={pk_in:.1f}dBFS PLR={plr_in:.1f}dB")
    log("P3 [1/8] Corrective EQ...")
    audio=apply_eq(audio,[(40,-1.5,1.5),(280,-1.0,2.0),(500,-0.8,1.5),(3200,-1.0,2.5)],sr)
    log("P3 [2/8] Underground style EQ...")
    audio=underground_eq(audio,sr)
    log("P3 [3/8] Per-song targeted corrections (P3 only)...")
    audio=targeted_spectral_eq(audio,sr,corrections,ref_avg)
    log(f"  kick={corrections.get('kick_deficit',0):+.1f}dB sub={corrections.get('sub_deficit',0):+.1f}dB "
        f"air={corrections.get('air_excess',0):+.1f}dB brightness={corrections.get('brightness_excess',0):+.0f}Hz")
    log("P3 [4/8] Reference spectral match...")
    if ref_audio is not None: audio=ref_track_eq(audio,sr,ref_audio,ref_sr)
    else: audio=profile_eq(audio,sr,ref_avg)
    log("P3 [5/8] M/S widening (4%) + multiband compression...")
    audio=ms_widen(audio,sr,4.0); audio=multiband_comp(audio,sr)
    log("P3 [6/8] Master bus compression + tube saturation (8% wet)...")
    audio=compressor(audio,sr,-18.0,1.8,60.0,250.0); audio=tube_saturate(audio,0.08)
    log("P3 [7/8] Stereo refinement + sub mono + noise floor...")
    audio=stereo_move(audio,sr,0.05,0.02); audio=mono_sub(audio,sr,100.0)
    audio=noise_floor(audio,sr,-66.0)
    log("P3 [8/8] ONE gain calc -> ONE soft-clip -> ONE hard limit...")
    cur_lufs=measure_lufs(audio,sr); gain_db=min(target_lufs-cur_lufs,14.0)
    audio=audio*10**(gain_db/20.0)
    log(f"  Gain: {gain_db:.2f}dB  ({cur_lufs:.1f} -> {target_lufs})")
    rms_cur=20*np.log10(np.sqrt(np.mean(audio**2))+1e-12)
    pk_cur=20*np.log10(np.max(np.abs(audio))+1e-12); crest=pk_cur-rms_cur
    if crest<crest_min:
        pullback=crest_min-crest; audio=audio*10**(-pullback/20.0)
        log(f"  DR protection: pulled back {pullback:.1f}dB")
    audio=soft_clip(audio,0.7,0.910); audio=hard_limit(audio,TRUE_PEAK_DB); audio=fit(audio,n_mix)
    plr_out,lufs_out,pk_out=measure_plr(audio,sr)
    rms_out=20*np.log10(np.sqrt(np.mean(audio**2))+1e-12); crest_out=round(pk_out-rms_out,2)
    corr_out=round(float(np.corrcoef(audio[:,0],audio[:,1])[0,1]),3) if audio.shape[1]>=2 else 1.0
    rep["output"]={"lufs":round(lufs_out,2),"peak":round(pk_out,2),"plr":round(plr_out,2),
                   "crest":crest_out,"correlation":corr_out}
    log(f"P3  Output: LUFS={lufs_out:.1f} Peak={pk_out:.1f}dBTP PLR={plr_out:.1f}dB Crest={crest_out:.1f}dB Corr={corr_out:.3f}")
    master=os.path.join(song_base,"P3_MASTERING","final_master",f"{sname}_master_{target_lufs:.1f}LUFS.wav")
    safe_save(audio,sr,master,label="final-master")
    log(f"P3  Master: {master} [{sr}Hz 24-bit no-dither no-normalize]")
    save_16bit(audio,sr,os.path.join(song_base,"P3_MASTERING","streaming",f"{sname}_master_16bit.wav"))
    short=os.path.join(song_base,"P3_MASTERING","shortened",f"{sname}_master_short.wav")
    save_quarter(audio,sr,short)
    if shortened_root: shutil.copy2(short,os.path.join(shortened_root,f"{sname}_master_short.wav"))
    letssubmit_check(short,None)
    if collection_dir:
        col=os.path.join(collection_dir,f"{sname}_master.wav"); shutil.copy2(master,col)
        log(f"P3  Collection: {col}")
    fp_b=fingerprint(to_mono(load(premix_path)[0]),sr); fp_a=fingerprint(to_mono(audio),sr)
    save_fp_plot(fp_b,fp_a,os.path.join(song_base,"P3_MASTERING","mastering_reports",f"{sname}_fingerprint.png"))
    _report(os.path.join(song_base,"P3_MASTERING","mastering_reports","p3_report.json"),rep)
    section("P3 COMPLETE"); return master,audio,rep["output"]

def p4(song_base, cleaned_stems, mix_audio, sr, mix_info, n_mix, bpm, master_path):
    section("P4  MIDI & ABLETON"); sname=os.path.basename(song_base)
    mdir=os.path.join(song_base,"P4_MIDI","midi_stems"); adir=os.path.join(song_base,"P4_MIDI","automation_lanes")
    midi={}; rep={"pipeline":"P4"}
    try:
        ch=librosa.feature.chroma_cqt(y=to_mono(mix_audio).astype(np.float32),sr=sr).mean(axis=1)
        maj=[6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
        mn=[6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        nts=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        bs,bk,bm=-np.inf,0,'major'
        for r in range(12):
            for p,md in [(maj,'major'),(mn,'minor')]:
                sc=np.corrcoef(ch,np.roll(p,r))[0,1]
                if sc>bs: bs,bk,bm=sc,r,md
        key=nts[bk]; mode=bm; conf=float(bs)
    except: key='C'; mode='minor'; conf=0.5
    log(f"P4  Key: {key} {mode} conf={conf:.2f}")
    if "drums" in cleaned_stems:
        try:
            hits=_classify_drums(cleaned_stems["drums"],sr); dp=os.path.join(mdir,f"{sname}_drums.mid")
            _drum_midi(hits,sr,bpm,dp); midi["drums"]=dp
        except Exception as e: log(f"  Drum MIDI failed: {e}","WARN")
    for sn in ["guitar","piano","other"]:
        if sn not in cleaned_stems: continue
        try:
            mp=os.path.join(mdir,f"{sname}_{sn}.mid")
            if _melodic_midi(cleaned_stems[sn],mp,sn,key,mode,conf): midi[sn]=mp
        except Exception as e: log(f"  {sn} MIDI failed: {e}","WARN")
    for sn in ["bass","vocals"]:
        if sn not in cleaned_stems: continue
        try:
            mp=os.path.join(mdir,f"{sname}_{sn}.mid")
            if _mono_midi(cleaned_stems[sn],mp,sn,bpm,key,mode,conf): midi[sn]=mp
        except Exception as e: log(f"  {sn} MIDI failed: {e}","WARN")
    for sn,sp in cleaned_stems.items():
        try: _automation(sp,sr,bpm,os.path.join(adir,f"{sname}_{sn}_auto.mid"))
        except: pass
    ss=os.path.join(song_base,"P4_MIDI","ableton","samples","stems")
    sm=os.path.join(song_base,"P4_MIDI","ableton","samples","master")
    for sn,sp in cleaned_stems.items():
        try: shutil.copy2(sp,os.path.join(ss,os.path.basename(sp)))
        except: pass
    if master_path and os.path.exists(master_path):
        try: shutil.copy2(master_path,os.path.join(sm,os.path.basename(master_path)))
        except: pass
    try:
        als=_build_als(song_base,sname,cleaned_stems,bpm,midi)
        rep.update({"midi":{k:os.path.basename(v) for k,v in midi.items()},"als":als})
    except Exception as e:
        log(f"  Ableton .als build failed: {e}  (pipeline continues)","WARN")
        rep["als_error"]=str(e)
    _report(os.path.join(song_base,"P4_MIDI","midi_reports","p4_report.json"),rep)
    section("P4 COMPLETE"); return midi, rep.get("als","")

def _classify_drums(path,sr):
    audio,_,_=load(path); mono=to_mono(audio).astype(np.float32)
    onsets=librosa.onset.onset_detect(y=mono,sr=sr,units='samples',hop_length=128,backtrack=True,delta=0.05,wait=5)
    res={"kick":[],"snare":[],"hihat":[],"perc":[]}
    for o in onsets:
        seg=mono[max(0,o-64):min(len(mono),o+2048)]
        if len(seg)<32: continue
        spec=np.abs(np.fft.rfft(seg)); freqs=np.fft.rfftfreq(len(seg),1.0/sr)
        cent=np.sum(freqs*spec)/(np.sum(spec)+1e-9)
        elo=np.sum(spec[freqs<200]); emid=np.sum(spec[(freqs>=200)&(freqs<2000)]); ehi=np.sum(spec[freqs>=2000])
        if cent<200 and elo>emid: res["kick"].append(int(o))
        elif 200<=cent<2000 and emid>=elo: res["snare"].append(int(o))
        elif cent>=2000 and ehi>emid: res["hihat"].append(int(o))
        else: res["perc"].append(int(o))
    return res

def _drum_midi(hits,sr,bpm,path):
    if not HAS_PM: return
    pm=pretty_midi.PrettyMIDI(initial_tempo=bpm); inst=pretty_midi.Instrument(program=0,is_drum=True,name="Drums")
    gm={"kick":36,"snare":38,"hihat":42,"perc":47}
    for dt,positions in hits.items():
        for pos in positions: t=pos/sr; inst.notes.append(pretty_midi.Note(100,gm[dt],t,t+0.1))
    pm.instruments.append(inst); pm.write(path)

def _scale_pcs(key,mode):
    nts=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']; ri=nts.index(key)
    steps=[0,2,4,5,7,9,11] if mode=='major' else [0,2,3,5,7,8,10]
    return {(ri+s)%12 for s in steps}

def _correct_key(md,key,mode,conf):
    if not HAS_PM or md is None or conf<0.6: return md
    scale=_scale_pcs(key,mode)
    for inst in md.instruments:
        if inst.is_drum: continue
        for note in inst.notes:
            pc=note.pitch%12
            if pc in scale: continue
            best=min(scale,key=lambda s:min(abs(s-pc),12-abs(s-pc))); diff=best-pc
            if abs(diff)>6: diff=diff-12 if diff>0 else diff+12
            note.pitch=int(np.clip(note.pitch+diff,0,127))
    return md

def _melodic_midi(path,out,stype,key,mode,conf):
    try:
        from basic_pitch.inference import predict
        _,md,_=predict(path); md=_correct_key(md,key,mode,conf); md.write(out)
        log(f"    {stype} MIDI: {out}"); return True
    except ImportError: log("    basic-pitch not installed.","WARN"); return False
    except Exception as e: log(f"    Basic Pitch ({stype}): {e}","WARN"); return False

def _mono_midi(path,out,stype,bpm,key,mode,conf):
    try:
        import crepe; audio,sr,_=load(path); mono=to_mono(audio).astype(np.float32)
        ta,fr,ca,_=crepe.predict(mono,sr,viterbi=True,step_size=10,verbose=0)
        if not HAS_PM: return False
        pm=pretty_midi.PrettyMIDI(initial_tempo=bpm); inst=pretty_midi.Instrument(program=0,name=stype)
        pn,pt=None,None
        for t,f,c in zip(ta,fr,ca):
            if c<0.5 or f<30:
                if pn is not None: inst.notes.append(pretty_midi.Note(80,pn,pt,t)); pn=None
                continue
            nn=int(np.clip(round(69+12*np.log2(f/440.0)),0,127))
            if pn!=nn:
                if pn is not None: inst.notes.append(pretty_midi.Note(80,pn,pt,t))
                pn,pt=nn,t
        pm.instruments.append(inst); pm=_correct_key(pm,key,mode,conf); pm.write(out)
        log(f"    {stype} MIDI: {out}"); return True
    except ImportError: log("    crepe not installed.","WARN"); return False
    except Exception as e: log(f"    CREPE ({stype}): {e}","WARN"); return False

def _automation(path,sr,bpm,out):
    if not HAS_PM: return
    audio,_,_=load(path); mono=to_mono(audio).astype(np.float32); hop=sr//10; n=len(mono)
    pm=pretty_midi.PrettyMIDI(initial_tempo=bpm); inst=pretty_midi.Instrument(program=0,name="Automation")
    for i in range(0,n-hop,hop):
        v=int(np.clip(np.sqrt(np.mean(mono[i:i+hop]**2))/0.5*127,0,127))
        inst.control_changes.append(pretty_midi.ControlChange(7,v,i/sr))
    cents=librosa.feature.spectral_centroid(y=mono,sr=sr,hop_length=hop)[0]; cm=cents.max()+1e-9
    for i,c in enumerate(cents): inst.control_changes.append(pretty_midi.ControlChange(74,int(np.clip(c/cm*127,0,127)),i*hop/sr))
    if audio.shape[1]>=2:
        side=audio[:,0]-audio[:,1]; mid=audio[:,0]+audio[:,1]+1e-9
        for i in range(0,n-hop,hop):
            w=np.sqrt(np.mean(side[i:i+hop]**2))/np.sqrt(np.mean(mid[i:i+hop]**2)+1e-9)
            inst.control_changes.append(pretty_midi.ControlChange(1,int(np.clip(w*127,0,127)),i/sr))
    pm.instruments.append(inst); pm.write(out)

def _build_als(song_base,sname,cleaned_stems,bpm,midi_files):
    idc=[300]
    def nid(): idc[0]+=1; return idc[0]
    bus_ids={b:nid() for b in BUS_MEMBERS}; pmix_id=nid()
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
    tc=lambda:u()+eq8()+cmp()+sat()+u()+lim()+sw()
    bc=lambda:u()+eq8()+glue()+u()+lim()
    pc=lambda:u()+eq8()+glue()+eq8()+u()+lim()
    rc=lambda fx:u()+fx+eq8()+u()
    lg=col("light_grey"); trks=""
    for sn in cleaned_stems:
        c=col(STEM_COLOR.get(sn,"grey")); bs=next((b for b,m in BUS_MEMBERS.items() if sn in m),"SYNTHS")
        bid=bus_ids.get(bs,pmix_id); tid=nid()
        trks+=f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{sn.upper()}"/></Name><ColorIndex Value="{c}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/GroupMaster/{bid}"/><UpperDisplayString Value="{bs}"/></AudioOutputRouting><Devices>{tc()}</Devices></DeviceChain></AudioTrack>'
        if midi_files.get(sn) and os.path.exists(midi_files[sn]):
            trks+=f'<MidiTrack Id="{nid()}"><Name><EffectiveName Value="{sn.upper()} MIDI"/></Name><ColorIndex Value="{c}"/></MidiTrack>'
    for bn in BUS_MEMBERS:
        c=col(BUS_COLOR.get(bn,"grey"))
        trks+=f'<GroupTrack Id="{bus_ids[bn]}"><Name><EffectiveName Value="{bn}"/></Name><ColorIndex Value="{c}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/GroupMaster/{pmix_id}"/><UpperDisplayString Value="PREMIX"/></AudioOutputRouting><Devices>{bc()}</Devices></DeviceChain></GroupTrack>'
    trks+=f'<GroupTrack Id="{pmix_id}"><Name><EffectiveName Value="PREMIX"/></Name><ColorIndex Value="{lg}"/><DeviceChain><AudioOutputRouting><Target Value="AudioIn/Master"/><UpperDisplayString Value="Master"/></AudioOutputRouting><Devices>{pc()}</Devices></DeviceChain></GroupTrack>'
    rets=""
    for rn,rfx in [("SHORT REVERB",rev()),("LONG REVERB",rev()),("SHORT DELAY",dly()),("LONG DELAY",dly())]:
        rets+=f'<ReturnTrack Id="{nid()}"><Name><EffectiveName Value="{rn}"/></Name><ColorIndex Value="{lg}"/><DeviceChain><Devices>{rc(rfx)}</Devices></DeviceChain></ReturnTrack>'
    mst=f'<MasterTrack Id="{nid()}"><Name><EffectiveName Value="Master"/></Name><DeviceChain><Devices>{lvl()}</Devices></DeviceChain></MasterTrack>'
    xml=(f'<?xml version="1.0" encoding="UTF-8"?>'
         f'<Ableton MajorVersion="12" MinorVersion="0" Creator="SunoMaster v{VERSION}">'
         f'<LiveSet><NextPointeeId Value="{idc[0]+100}"/><Tempo><Manual Value="{bpm:.4f}"/></Tempo>'
         f'<Tracks>{trks}</Tracks><ReturnTracks>{rets}</ReturnTracks>{mst}</LiveSet></Ableton>')
    als_dir=os.path.join(song_base,"P4_MIDI","ableton"); als=os.path.join(als_dir,f"{sname}.als")
    with gzip.open(als,'wb') as gf: gf.write(xml.encode('utf-8'))
    log(f"    Ableton project: {als}"); return als

def p5_final_cleanup(song_base, ls_key, song_diag_before, ref_avg):
    section("P5  FINAL CLEANUP & VERIFICATION")
    sname=os.path.basename(song_base); rep={"pipeline":"P5","song":sname,"files":{}}
    master_dir=os.path.join(song_base,"P3_MASTERING")
    wav_files=[]
    for root,dirs,files in os.walk(master_dir):
        for fn in files:
            if fn.lower().endswith('.wav'): wav_files.append(os.path.join(root,fn))
    log(f"P5  Scanning {len(wav_files)} master output files (metadata strip + AI scan)...")
    for wav_path in wav_files:
        rel=os.path.relpath(wav_path,song_base)
        try:
            if HAS_MUT:
                try:
                    from mutagen import File as MF; mf=MF(wav_path)
                    if mf is not None: mf.delete(); mf.save()
                except: pass
                try: ID3(wav_path).delete()
                except: pass
            audio,sr,_=load(wav_path); sc=fp_score(fingerprint(to_mono(audio),sr))
            rep["files"][rel]=round(sc*100,1); flag=" <-- REVIEW" if sc>0.30 else ""
            log(f"  {rel:<55} AI:{sc*100:.1f}%{flag}")
        except Exception as e: log(f"  ERROR {rel}: {e}","WARN")
    master_path=None
    for root,dirs,files in os.walk(os.path.join(song_base,"P3_MASTERING","final_master")):
        for fn in files:
            if fn.lower().endswith('.wav'): master_path=os.path.join(root,fn)
    if master_path:
        try:
            audio,sr,_=load(master_path); song_diag_after=diagnose_audio(audio,sr,sname)
            log(f"\nP5  BEFORE vs AFTER - {sname}:")
            for k,label in [("lufs","LUFS"),("crest","Crest"),("plr","PLR"),("correlation","Corr")]:
                before=song_diag_before.get(k,0); after=song_diag_after.get(k,0); ref_val=ref_avg.get(k,0)
                log(f"  {label:<12}: {before:>8.3f} -> {after:>8.3f}  (ref {ref_val:>8.3f})")
            for bk,label in [("kick_40_80","Kick 40-80Hz"),("air_10k_20k","Air 10-20kHz")]:
                before=song_diag_before["bands"][bk]; after=song_diag_after["bands"][bk]; ref_val=ref_avg["bands"][bk]
                log(f"  {label:<12}: {before:>+8.2f} -> {after:>+8.2f}  (ref {ref_val:>+8.2f})")
            rep["verification"]={"before":song_diag_before,"after":song_diag_after}
        except Exception as e: log(f"  Verification error: {e}","WARN")
    _report(os.path.join(song_base,"P3_MASTERING","mastering_reports","p5_cleanup_report.json"),rep)
    section("P5 COMPLETE"); return rep

def main():
    import argparse
    ap=argparse.ArgumentParser(description=f"SunoMaster v{VERSION}")
    ap.add_argument("--computer",     default="1")
    ap.add_argument("--drive",        default="D")
    ap.add_argument("--mode",         default="1")
    ap.add_argument("--song",         default="")
    ap.add_argument("--ref",          nargs='?', const='', default='')
    ap.add_argument("--lskey",        nargs='?', const='', default='')
    ap.add_argument("--genre",        default="underground")
    ap.add_argument("--skip-confirm", action="store_true")
    args=ap.parse_args()

    section(f"SunoMaster v{VERSION} - LEVIATHAN APPROVED")
    root,machine=select_computer(args)
    paths=build_paths(root); ensure_root(paths)
    log(f"Machine: {machine}  Root: {root}  Genre: {args.genre}")

    section("STEP 1: REFERENCE ANALYSIS")
    ref_avg=build_reference_profile(paths["references"])
    log(f"Profile: LUFS={ref_avg.get('lufs',-8.12):.2f} Kick={ref_avg['bands']['kick_40_80']:+.2f}dB Centroid={ref_avg.get('centroid',2947):.0f}Hz")

    ref_audio=ref_sr=None
    ref_path=(args.ref or '').strip().strip('"')
    if ref_path and os.path.exists(ref_path):
        try: ref_audio,ref_sr,_=load(ref_path); log(f"Reference WAV: {os.path.basename(ref_path)}")
        except Exception as e: log(f"Could not load reference WAV: {e}","WARN")

    ls_key=(args.lskey or '').strip() or None
    mode=args.mode.strip(); songs_to_process=[]
    if mode=="2":
        for e in sorted(os.scandir(paths['releases']),key=lambda x:x.name):
            if e.is_dir():
                wav=find_wav(e.path)
                if wav: songs_to_process.append((e.path,wav))
    else:
        folder=args.song.strip().strip('"')
        if not folder: log("No song folder provided.","ERROR"); return
        if not os.path.isdir(folder): folder=os.path.join(paths['releases'],folder)
        wav=find_wav(folder)
        if not wav: log(f"No WAV found in {folder}","ERROR"); return
        songs_to_process.append((folder,wav))
    if not songs_to_process: log("No songs found.","ERROR"); return

    section("STEP 2: SONG DIAGNOSTICS")
    all_diags=[]
    for song_folder,wav_path in songs_to_process:
        log(f"Diagnosing: {os.path.basename(song_folder)}")
        try:
            audio,sr,info=load(wav_path)
            d=diagnose_audio(audio,sr,os.path.basename(song_folder))
            d["wav_path"]=wav_path; d["song_folder"]=song_folder
            all_diags.append(d)
            log(f"  LUFS={d['lufs']:.2f} Kick={d['bands']['kick_40_80']:+.2f}dB Infra={d['infrasonic_excess']:+.1f}dB Centroid={d.get('centroid',0):.0f}Hz")
        except Exception as e: log(f"  ERROR diagnosing {song_folder}: {e}","ERROR")
    if not all_diags: log("Diagnosis failed for all songs.","ERROR"); return

    section("STEP 3: COMPARISON REPORT")
    print_diagnostics_report(all_diags,ref_avg)

    if not args.skip_confirm:
        print(f"\n  Ready to process {len(all_diags)} song(s) through P0-P5.")
        print(f"  Genre: {args.genre} | Target: {GENRE_LUFS.get(args.genre,-8.0)} LUFS | Ceiling: {TRUE_PEAK_DB} dBTP")
        ans=input("  Proceed? (y/n): ").strip().lower()
        if ans!='y': print("  Cancelled."); return

    final_results=[]; manual_check_files=[]
    for song_diag in all_diags:
        song_folder=song_diag["song_folder"]; wav_path=song_diag["wav_path"]
        sname=os.path.basename(song_folder)
        song_base=os.path.join(paths['releases'],sname)
        create_song_folders(song_base)
        corrections=derive_corrections(song_diag,ref_avg)
        log(f"\nCorrections for {sname}:")
        log(f"  kick={corrections['kick_deficit']:+.1f}dB sub={corrections['sub_deficit']:+.1f}dB "
            f"air={corrections['air_excess']:+.1f}dB brightness={corrections['brightness_excess']:+.0f}Hz")
        log(f"  needs_hp30hz={corrections['needs_hp30hz']} ({corrections['infrasonic_severity']:+.1f}dB vs {INFRA_HP30_THR}dB threshold)")

        section(f"PROCESSING: {sname}")
        mix_audio,sr,mix_info=load(wav_path); n_mix=mix_audio.shape[0]
        log(f"Original: {os.path.basename(wav_path)} [{sr}Hz {mix_audio.shape[1]}ch {n_mix/sr:.1f}s]")

        stems_raw,fp_mix,mix_info,sr,n_mix=p0(song_base,wav_path,paths,ls_key,corrections)
        if not stems_raw: log(f"P0 failed - skipping {sname}.","ERROR"); continue

        cleaned_stems,bpm=p1(song_base,stems_raw,mix_audio,sr,mix_info,n_mix)
        premix_path,premix_audio=p2(song_base,cleaned_stems,mix_audio,sr,mix_info,
                                     n_mix,ref_audio,ref_sr,ref_avg,corrections,bpm)
        master_path,master_audio,p3_out=p3(song_base,premix_path,mix_audio,sr,mix_info,n_mix,
                                            ref_audio,ref_sr,ref_avg,corrections,args.genre,
                                            paths['collection'],paths['shortened'])
        midi_files,als_path=p4(song_base,cleaned_stems,mix_audio,sr,mix_info,n_mix,bpm,master_path)
        p5_final_cleanup(song_base,ls_key,song_diag,ref_avg)

        log_path=os.path.join(song_base,f"{sname}_pipeline_log.txt"); save_log(log_path)
        final_results.append({"song":sname,"master":master_path,"als":als_path,
                               "before":song_diag,"p3_output":p3_out})
        short_for_check=os.path.join(paths['shortened'],f"{sname}_master_short.wav")
        if os.path.exists(short_for_check): manual_check_files.append(short_for_check)
        section(f"DONE: {sname}")
        log(f"Master  : {master_path}")
        log(f"Ableton : {als_path}")
        log(f"Log     : {log_path}")

    section("STEP 4: FINAL SUMMARY")
    print(f"\n  {'='*66}")
    print(f"  {'Song':<40} {'Before LUFS':>12} {'After LUFS':>11}")
    print(f"  {'Reference average':<40} {ref_avg.get('lufs',-8.12):>12.1f}")
    print(f"  {'-'*63}")
    for r in final_results:
        print(f"  {r['song']:<40} {r['before'].get('lufs',0):>12.1f} {r['p3_output'].get('lufs',0):>11.1f}")
    print(f"  {'='*66}")

    if manual_check_files and not ls_key:
        print(f"\n  LETSSUBMIT - upload these to https://letssubmit.com/ai-music-checker")
        for f in manual_check_files: print(f"    {f}")

    section(f"ALL PIPELINES COMPLETE - SunoMaster v{VERSION}")

if __name__=='__main__':
    main()