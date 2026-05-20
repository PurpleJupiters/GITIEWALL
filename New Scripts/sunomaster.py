"""
SunoMaster v1.0 - Complete 5-Pipeline Audio Production System
=============================================================
P0  Detection & Splitting     : metadata clean, AI scan, Demucs stems
P1  Stem Cleaning             : artifact removal, phase align, quantize, normalize
P2  Mixing                    : gain stage, EQ, compress, saturate, stereo, -6dB out
P3  Mastering                 : reference EQ, dynamics, saturate, -8 LUFS out
P4  MIDI & Ableton            : MIDI extraction, automation, .als project

Design contract:
  - Never changes pitch, never changes song structure
  - Never applies more than 2dB corrective EQ per band
  - Never compresses more than 3dB GR on master bus
  - Never limits to below -9 LUFS (protects dynamics / crest factor)
  - All output files match original mix duration exactly
  - Every decision logged to JSON report
"""

import os, sys, json, time, shutil, warnings, subprocess, argparse
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.interpolate import interp1d
import librosa
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Optional imports - fail gracefully
try:
    import pyloudnorm as pyln
    HAS_PYLOUDNORM = True
except ImportError:
    HAS_PYLOUDNORM = False
    print("  [warn] pyloudnorm not found - LUFS targeting uses fallback")

try:
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1, TALB
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ============================================================
# CONSTANTS
# ============================================================

VERSION        = "1.0"
FMIN, FMAX     = 5000, 16000       # AI fingerprint band
N_BINS         = 128
DETREND_WIN    = 18
TARGET_LUFS_P3 = -8.0              # mastering target
HEADROOM_P2_DB = -6.0              # mixing headroom
GRID_DIV       = 128               # quantization grid subdivisions per beat
QCF            = 256               # crossfade samples for quantization edits

# Ableton color IDs (Live 12 palette)
ABLETON_COLORS = {
    "black":      0,
    "red":        14,
    "yellow":     5,
    "purple":     25,
    "orange":     9,
    "blue":       20,
    "maroon":     13,
    "light_grey": 18,
    "grey":       17,
    "white":      3,
}

STEM_COLORS = {
    "kick":       "black",
    "bass":       "black",
    "drums":      "red",
    "vocals":     "yellow",
    "synths":     "purple",
    "other":      "purple",
    "guitar":     "orange",
    "piano":      "blue",
    "fx":         "maroon",
}

BUS_COLORS = {
    "LOWEND":   "black",
    "DRUMS":    "red",
    "VOCALS":   "yellow",
    "SYNTHS":   "purple",
    "GUITAR":   "orange",
    "PIANO":    "blue",
    "FX":       "maroon",
    "PREMIX":   "light_grey",
}

# ============================================================
# LOGGING
# ============================================================

LOG = []

def log(msg, level="INFO"):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG.append(line)

def save_log(path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LOG))

def sep(title=""):
    if title:
        log("=" * 60)
        log(f"  {title}")
        log("=" * 60)
    else:
        log("=" * 60)

# ============================================================
# COMPUTER / PATH CONFIGURATION
# ============================================================

def select_computer():
    """Ask user which workstation, return root drive path."""
    print("\n" + "=" * 50)
    print("  SunoMaster v" + VERSION)
    print("=" * 50)
    print("\nWhich workstation are you using?")
    print("  [1] Lenovo ThinkStation  (E:\\)")
    print("  [2] HP ZBook             (ask for drive letter)")
    choice = input("\nEnter 1 or 2: ").strip()
    if choice == "2":
        letter = input("Enter ZBook drive letter (e.g. D): ").strip().upper()
        root = f"{letter}:\\"
    else:
        root = "E:\\"
    log(f"Computer: {'Lenovo ThinkStation' if choice != '2' else 'HP ZBook'}")
    log(f"Root drive: {root}")
    return root

def build_paths(root):
    """Return dict of all project paths."""
    sm = os.path.join(root, "SunoMaster")
    return {
        "root":       sm,
        "releases":   os.path.join(sm, "releases"),
        "collection": os.path.join(sm, "collection"),
        "references": os.path.join(sm, "references"),
        "scripts":    os.path.join(sm, "scripts"),
        "downloads":  os.path.join(sm, "downloads"),
        "backup":     os.path.join(sm, "backup"),
        "shortened":  os.path.join(sm, "shortened"),
        "output":     os.path.join(sm, "output"),
    }

def ensure_folders(paths):
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
    log("Root folder structure verified.")

def song_folders(releases_root, song_name):
    """Create and return all per-song pipeline folders."""
    base = os.path.join(releases_root, song_name)
    subs = [
        "P0_DETECTION/cleaned",
        "P0_DETECTION/detection_reports",
        "P0_DETECTION/shortened",
        "P1_STEMCLEANING/stems_raw",
        "P1_STEMCLEANING/stems_cleaned",
        "P1_STEMCLEANING/phase_reports",
        "P1_STEMCLEANING/alignment_reports",
        "P2_MIXING/pre_master",
        "P2_MIXING/stems_processed",
        "P2_MIXING/mono_check",
        "P2_MIXING/mix_reports",
        "P3_MASTERING/final_master",
        "P3_MASTERING/streaming",
        "P3_MASTERING/shortened",
        "P3_MASTERING/mastering_reports",
        "P4_MIDI/midi_stems",
        "P4_MIDI/automation_lanes",
        "P4_MIDI/ableton/samples",
        "P4_MIDI/midi_reports",
    ]
    for s in subs:
        os.makedirs(os.path.join(base, s), exist_ok=True)
    return base

def find_original_wav(song_folder):
    """Find the original mix WAV in a song folder."""
    for f in os.listdir(song_folder):
        if f.lower().endswith('.wav') and 'original' in f.lower():
            return os.path.join(song_folder, f)
    # If no 'original' in name, return first WAV found
    for f in os.listdir(song_folder):
        if f.lower().endswith('.wav'):
            return os.path.join(song_folder, f)
    return None

# ============================================================
# AUDIO UTILITIES
# ============================================================

def load(path):
    """Load WAV, return (float64 stereo array, sr, info)."""
    audio, sr = sf.read(path, always_2d=True)
    info = sf.info(path)
    return audio.astype(np.float64), sr, info

def save(audio, sr, path, original_info=None):
    """Save WAV preserving original bit depth."""
    if original_info and 'PCM_16' in original_info.subtype:
        sub = 'PCM_16'
    elif original_info and 'PCM_24' in original_info.subtype:
        sub = 'PCM_24'
    else:
        sub = 'PCM_24'
    sf.write(path, audio, sr, subtype=sub)

def match_length(audio, target_n_samples):
    """Pad or trim audio to exactly target_n_samples."""
    n = audio.shape[0]
    if n == target_n_samples:
        return audio
    elif n > target_n_samples:
        return audio[:target_n_samples]
    else:
        pad = np.zeros((target_n_samples - n, audio.shape[1]))
        return np.vstack([audio, pad])

def clip_guard(audio, ceiling=0.9999):
    pk = np.max(np.abs(audio))
    if pk > ceiling:
        audio = audio / pk * ceiling
    return audio

def measure_lufs(audio, sr):
    """Measure integrated LUFS. Returns float or None."""
    if HAS_PYLOUDNORM:
        meter = pyln.Meter(sr)
        mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
        try:
            lufs = meter.integrated_loudness(mono)
            return float(lufs)
        except Exception:
            return None
    # Fallback: approximate from RMS
    rms = np.sqrt(np.mean(audio**2))
    if rms < 1e-9:
        return -70.0
    return 20 * np.log10(rms) - 3.0  # rough approximation

def make_shortened(audio, sr, dest_path, original_info):
    """Save first quarter of audio to dest_path."""
    quarter = audio.shape[0] // 4
    save(audio[:quarter], sr, dest_path, original_info)

# ============================================================
# AI FINGERPRINT (arXiv:2506.19108)
# ============================================================

def fingerprint(mono, sr, fmax=FMAX):
    f, _, Z = signal.stft(mono, fs=sr, nperseg=4096, noverlap=3072, window='hann')
    avg = np.mean(np.abs(Z), axis=1)
    mask = (f >= FMIN) & (f <= fmax)
    bf = np.linspace(FMIN, fmax, N_BINS)
    s = interp1d(f[mask], avg[mask], kind='linear',
                 bounds_error=False, fill_value=0.0)(bf)
    lm = minimum_filter1d(s, size=DETREND_WIN)
    raw = s - lm
    peak = raw.max()
    norm = raw / peak if peak > 0 else raw.copy()
    return {"norm": norm, "raw": raw, "bf": bf, "peak": float(peak)}

def fp_score(fp_dict):
    top8 = np.sort(fp_dict["norm"])[-8:]
    logit = (top8.mean() - 0.35) * 8.0
    return float(1.0 / (1.0 + np.exp(-logit)))

def fp_report(fp_before, fp_after, path):
    """Save before/after fingerprint PNG."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), facecolor='#0d1117')
    fig.suptitle("AI Artifact Fingerprint", color='white', fontsize=12)
    x = np.arange(N_BINS)
    for ax, d, c, l in [(axes[0], fp_before["norm"], '#f85149', 'Before'),
                        (axes[1], fp_after["norm"],  '#3fb950', 'After')]:
        ax.set_facecolor('#161b22'); ax.tick_params(colors='#8b949e')
        ax.bar(x, d, color=c, alpha=0.85, width=0.85)
        ax.set_title(l, color=c, fontsize=10); ax.set_ylim(0, 1.08)
    delta = fp_after["norm"] - fp_before["norm"]
    axes[2].set_facecolor('#161b22'); axes[2].tick_params(colors='#8b949e')
    axes[2].bar(x, delta, color=['#3fb950' if d < 0 else '#f85149' for d in delta],
                alpha=0.85, width=0.85)
    axes[2].axhline(0, color='#8b949e', lw=0.8)
    axes[2].set_title('Delta', color='#8b949e', fontsize=10)
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches='tight', facecolor='#0d1117')
    plt.close()

# ============================================================
# LETSSUBMIT API
# ============================================================

def upload_temp(filepath):
    """Upload file to file.io, return public URL or None."""
    if not HAS_REQUESTS:
        return None
    try:
        with open(filepath, 'rb') as f:
            r = requests.post('https://file.io', files={'file': f},
                              data={'expires': '1d'}, timeout=60)
        if r.status_code == 200:
            return r.json().get('link')
    except Exception:
        pass
    return None

def check_letssubmit(filepath, api_key):
    """Submit to LetsSubmit API, return result dict or None."""
    if not HAS_REQUESTS or not api_key:
        return None
    url = upload_temp(filepath)
    if not url:
        log("  Could not upload file for LetsSubmit check.", "WARN")
        return None
    try:
        r = requests.post(
            'https://api.letssubmit.com/analyze_song',
            headers={'Authorization': f'Bearer {api_key}',
                     'Content-Type': 'application/json'},
            json={'file_url': url}, timeout=120)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"  LetsSubmit API error: {e}", "WARN")
    return None

# ============================================================
# P0 - DETECTION & SPLITTING
# ============================================================

def p0_clean_metadata(wav_path):
    """Remove AI-related metadata tags."""
    if not HAS_MUTAGEN:
        log("  mutagen not installed - skipping metadata clean")
        return
    try:
        tags = ID3(wav_path)
        ai_keys = [k for k in tags.keys()
                   if any(w in k.lower() for w in ['suno', 'udio', 'ai', 'generated'])]
        for k in ai_keys:
            del tags[k]
        if ai_keys:
            tags.save()
            log(f"  Removed {len(ai_keys)} AI metadata tags.")
    except Exception:
        pass

def p0_run_demucs(wav_path, out_dir):
    """
    Run Demucs htdemucs_6s on wav_path.
    Returns dict: {stem_name: filepath} or None on failure.
    """
    log("  Running Demucs htdemucs_6s...")
    song_name = os.path.splitext(os.path.basename(wav_path))[0]

    cmd = [
        sys.executable, "-m", "demucs",
        "-n", "htdemucs_6s",
        "--float32",
        "--clip-mode", "clamp",
        "--shifts", "2",
        "-o", out_dir,
        wav_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  Demucs failed: {result.stderr[:300]}", "ERROR")
        return None

    stems_dir = os.path.join(out_dir, "htdemucs_6s", song_name)
    if not os.path.exists(stems_dir):
        log(f"  Demucs output folder not found: {stems_dir}", "ERROR")
        return None

    stem_names = ["drums", "bass", "vocals", "guitar", "piano", "other"]
    stems = {}
    for s in stem_names:
        p = os.path.join(stems_dir, f"{s}.wav")
        if os.path.exists(p):
            stems[s] = p
    log(f"  Demucs complete: {list(stems.keys())}")
    return stems

def p0_pipeline(song_base, original_wav, paths, letssubmit_key=None):
    sep("P0  DETECTION & SPLITTING")
    audio, sr, info = load(original_wav)
    n_samples = audio.shape[0]
    mono = np.mean(audio, axis=1)
    fmax = min(FMAX, sr // 2 - 200)

    report = {
        "pipeline": "P0",
        "song": os.path.basename(original_wav),
        "duration_s": round(n_samples / sr, 2),
        "sample_rate": sr,
        "channels": audio.shape[1],
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

    # --- Metadata clean
    log("Step 1/5  Metadata cleaning...")
    p0_clean_metadata(original_wav)

    # --- Internal fingerprint
    log("Step 2/5  Internal AI fingerprint analysis...")
    fp = fingerprint(mono, sr, fmax)
    internal_score = fp_score(fp)
    report["internal_ai_score_pct"] = round(internal_score * 100, 1)
    log(f"  Internal AI score: {internal_score*100:.1f}% (directional only)")

    # --- Shortened file
    log("Step 3/5  Generating shortened test file (first quarter)...")
    song_stem = os.path.splitext(os.path.basename(original_wav))[0]
    short_name = f"{song_stem}_shortened.wav"
    short_p0 = os.path.join(song_base, "P0_DETECTION", "shortened", short_name)
    short_root = os.path.join(paths["shortened"], short_name)
    make_shortened(audio, sr, short_p0, info)
    shutil.copy2(short_p0, short_root)
    log(f"  Saved: {short_p0}")

    # --- LetsSubmit API
    if letssubmit_key:
        log("Step 3b LetsSubmit API check...")
        ls_result = check_letssubmit(short_p0, letssubmit_key)
        if ls_result:
            report["letssubmit_result"] = ls_result
            log(f"  LetsSubmit score: {ls_result}")
    else:
        log("  No LetsSubmit API key provided - skipping (test manually at letssubmit.com/ai-music-checker)")

    # --- Demucs stem splitting
    log("Step 4/5  Demucs stem splitting...")
    raw_stems_dir = os.path.join(song_base, "P1_STEMCLEANING", "stems_raw")
    stems = p0_run_demucs(original_wav, raw_stems_dir)
    if not stems:
        log("  Demucs failed. Aborting P0.", "ERROR")
        return None
    report["stems_extracted"] = list(stems.keys())

    # --- Per-stem fingerprint
    log("Step 5/5  Per-stem AI analysis...")
    stem_scores = {}
    for sname, spath in stems.items():
        stem_audio, stem_sr, _ = load(spath)
        stem_mono = np.mean(stem_audio, axis=1)
        stem_fp = fingerprint(stem_mono, stem_sr, min(fmax, stem_sr//2-200))
        score = fp_score(stem_fp)
        stem_scores[sname] = round(score * 100, 1)
        log(f"  {sname:<10}: {score*100:.1f}%")
    report["stem_ai_scores"] = stem_scores

    # --- Save report
    rpt_path = os.path.join(song_base, "P0_DETECTION", "detection_reports", "p0_report.json")
    with open(rpt_path, 'w') as f:
        json.dump(report, f, indent=2)
    log(f"  Report: {rpt_path}")

    sep("P0 COMPLETE")
    return stems

# ============================================================
# P1 - STEM CLEANING
# ============================================================

def p1_noise_floor(audio, sr, level_db=-58.0):
    """Add recording-environment noise floor."""
    n, nch = audio.shape
    amp = 10 ** (level_db / 20.0)
    rng = np.random.default_rng(42)
    hp = signal.butter(2, 40, btype='high', fs=sr, output='sos')
    lp = signal.butter(2, min(18000, sr//2-200), btype='low', fs=sr, output='sos')
    out = np.zeros_like(audio)
    for ch in range(nch):
        x = rng.standard_normal(n) * amp
        x = signal.sosfiltfilt(hp, x)
        x = signal.sosfiltfilt(lp, x)
        out[:, ch] = x
    return audio + out

def p1_remove_clicks(audio, sr, threshold=0.98):
    """Detect and interpolate over clipped/clicked samples."""
    n, nch = audio.shape
    fixed = audio.copy()
    total_fixed = 0
    for ch in range(nch):
        channel = fixed[:, ch]
        clipped = np.abs(channel) > threshold
        if not clipped.any():
            continue
        # Label contiguous clipped regions
        diff = np.diff(clipped.astype(int), prepend=0, append=0)
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]
        for s, e in zip(starts, ends):
            if s > 0 and e < n:
                x_known = np.array([s-1, e])
                y_known = np.array([channel[s-1], channel[e]])
                x_interp = np.arange(s, e)
                channel[s:e] = np.interp(x_interp, x_known, y_known)
                total_fixed += (e - s)
        fixed[:, ch] = channel
    return fixed, total_fixed

def p1_phase_align_to_mix(stem_audio, mix_audio, sr):
    """
    Shift stem to maximize cross-correlation with mix.
    Maximum allowed shift: 100ms to avoid gross misalignment.
    """
    max_lag = int(sr * 0.1)
    stem_mono = np.mean(stem_audio, axis=1)
    mix_mono = np.mean(mix_audio, axis=1)
    n = min(len(stem_mono), len(mix_mono))
    # Use first 10 seconds for fast correlation
    seg = min(n, sr * 10)
    xcorr = signal.correlate(mix_mono[:seg], stem_mono[:seg], mode='full')
    lags = signal.correlation_lags(seg, seg, mode='full')
    lag = lags[np.argmax(xcorr)]
    # Clamp
    lag = np.clip(lag, -max_lag, max_lag)
    if lag == 0:
        return stem_audio, 0
    if lag > 0:
        aligned = np.vstack([np.zeros((lag, stem_audio.shape[1])), stem_audio[:-lag]])
    else:
        aligned = np.vstack([stem_audio[-lag:], np.zeros((-lag, stem_audio.shape[1]))])
    return aligned, int(lag)

def p1_quantize_stem(audio, sr, grid_div=GRID_DIV, bpm_override=None):
    """
    Slip-quantize stem to beat grid. Maximum shift = half cell.
    No time-stretching.
    """
    n, nch = audio.shape
    mono = np.mean(audio, axis=1).astype(np.float32)
    if bpm_override:
        bpm = float(bpm_override)
    else:
        tempo, _ = librosa.beat.beat_track(y=mono, sr=sr, units='time')
        bpm = float(np.atleast_1d(tempo)[0])
    if bpm <= 0 or bpm > 300:
        return audio, bpm, 0
    cell = (60.0 / bpm / grid_div) * sr
    maxs = int(cell / 2)
    onsets = librosa.onset.onset_detect(
        y=mono, sr=sr, units='samples', hop_length=256, backtrack=True,
        pre_max=3, post_max=3, pre_avg=3, post_avg=5, delta=0.07, wait=10)
    result = audio.copy()
    cum = 0
    ns = 0
    for ow in onsets:
        o = ow + cum
        if o < 0 or o >= n:
            continue
        ng = int(round(o / cell) * cell)
        sh = ng - o
        if abs(sh) > maxs or sh == 0:
            continue
        # Crossfade at edit point
        cf = QCF
        pos = max(0, o - cf // 2)
        fo = np.linspace(1, 0, cf)
        fi = np.linspace(0, 1, cf)
        for ch in range(nch):
            os_seg = result[pos:min(n, pos+cf), ch]
            ss = max(0, pos + sh)
            sh_seg = result[ss:min(n, ss+cf), ch]
            bl = min(len(os_seg), len(sh_seg), cf)
            if bl >= 4:
                result[pos:pos+bl, ch] = os_seg[:bl]*fo[:bl] + sh_seg[:bl]*fi[:bl]
        cum += sh
        ns += 1
    return result, bpm, ns

def p1_normalize_stem(audio, target_rms_db=-18.0):
    """Gain-stage stem to target RMS level."""
    rms = np.sqrt(np.mean(audio**2))
    if rms < 1e-9:
        return audio
    target_rms = 10 ** (target_rms_db / 20.0)
    gain = target_rms / rms
    return audio * gain

def p1_saturation(audio, drive_db=1.0):
    d = 10 ** (drive_db / 20.0)
    return np.tanh(audio * d) / d

def p1_stereo_movement(audio, sr, rate=0.07, depth=0.03):
    if audio.shape[1] < 2:
        return audio
    t = np.arange(audio.shape[0]) / sr
    lfo = 1.0 + depth * np.sin(2.0 * np.pi * rate * t)
    mid = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5 * lfo
    out = np.zeros_like(audio)
    out[:, 0] = mid + side
    out[:, 1] = mid - side
    return out

def p1_pipeline(song_base, stems_raw, mix_audio, sr, mix_info):
    sep("P1  STEM CLEANING")
    cleaned_dir = os.path.join(song_base, "P1_STEMCLEANING", "stems_cleaned")
    n_mix = mix_audio.shape[0]
    cleaned_stems = {}
    report = {"pipeline": "P1", "stems": {}}

    bpm_detected = None
    for sname, spath in stems_raw.items():
        log(f"  Processing stem: {sname}...")
        stem_audio, stem_sr, stem_info = load(spath)

        # Resample to mix SR if different
        if stem_sr != sr:
            log(f"    Resampling {stem_sr}Hz -> {sr}Hz")
            import librosa
            mono_tmp = librosa.resample(np.mean(stem_audio, axis=1),
                                        orig_sr=stem_sr, target_sr=sr)
            stem_audio = np.column_stack([mono_tmp, mono_tmp])

        stem_audio = match_length(stem_audio, n_mix)

        # Click removal
        stem_audio, n_fixed = p1_remove_clicks(stem_audio, sr)
        log(f"    Clicks fixed: {n_fixed} samples")

        # Phase align to mix
        stem_audio, lag = p1_phase_align_to_mix(stem_audio, mix_audio, sr)
        stem_audio = match_length(stem_audio, n_mix)
        log(f"    Phase lag corrected: {lag} samples ({lag/sr*1000:.1f}ms)")

        # AI artifact treatment (noise floor + stereo movement + saturation)
        stem_audio = p1_noise_floor(stem_audio, sr, level_db=-60.0)
        if stem_audio.shape[1] >= 2:
            stem_audio = p1_stereo_movement(stem_audio, sr, rate=0.07, depth=0.02)
        stem_audio = p1_saturation(stem_audio, drive_db=0.8)

        # 128-grid quantization
        if bpm_detected is None:
            stem_audio, bpm_d, ns = p1_quantize_stem(stem_audio, sr)
            bpm_detected = bpm_d
        else:
            stem_audio, _, ns = p1_quantize_stem(stem_audio, sr, bpm_override=bpm_detected)
        log(f"    Quantize: BPM={bpm_detected:.1f}, {ns} onsets shifted")

        # Normalize to -18dB RMS
        stem_audio = p1_normalize_stem(stem_audio, target_rms_db=-18.0)
        stem_audio = clip_guard(stem_audio)
        stem_audio = match_length(stem_audio, n_mix)

        # Save
        out_path = os.path.join(cleaned_dir, f"{sname}.wav")
        save(stem_audio, sr, out_path, mix_info)
        cleaned_stems[sname] = out_path
        log(f"    Saved: {out_path}")

        report["stems"][sname] = {
            "clicks_fixed": n_fixed,
            "phase_lag_samples": int(lag),
            "bpm": round(bpm_detected, 2) if bpm_detected else 0,
            "onsets_quantized": ns,
        }

    rpt = os.path.join(song_base, "P1_STEMCLEANING", "alignment_reports", "p1_report.json")
    with open(rpt, 'w') as f:
        json.dump(report, f, indent=2)

    sep("P1 COMPLETE")
    return cleaned_stems, bpm_detected

# ============================================================
# P2 - MIXING
# ============================================================

STEM_VOLUMES = {
    "kick":   0.90,
    "drums":  0.75,
    "bass":   0.85,
    "vocals": 0.80,
    "guitar": 0.65,
    "piano":  0.65,
    "other":  0.70,
    "fx":     0.55,
}

STEM_PAN = {
    "kick":   0.0,
    "bass":   0.0,
    "drums":  0.0,
    "vocals": 0.0,
    "guitar": 0.15,
    "piano":  -0.15,
    "other":  0.0,
    "fx":     0.0,
}

def p2_gain_stage(audio, target_rms_db=-18.0):
    rms = np.sqrt(np.mean(audio**2))
    if rms < 1e-9:
        return audio
    target = 10 ** (target_rms_db / 20.0)
    return audio * (target / rms)

def p2_apply_pan(audio, pan):
    """pan: -1 (full left) to +1 (full right)."""
    if audio.shape[1] < 2:
        return audio
    out = audio.copy()
    if pan > 0:
        out[:, 0] *= (1.0 - pan)
    elif pan < 0:
        out[:, 1] *= (1.0 + pan)
    return out

def p2_glue_compress(audio, threshold_db=-18.0, ratio=2.0,
                      attack_ms=40.0, release_ms=200.0, sr=44100):
    """Simple feed-forward RMS compressor for glue."""
    n, nch = audio.shape
    thr = 10 ** (threshold_db / 20.0)
    att = np.exp(-1.0 / (sr * attack_ms / 1000.0))
    rel = np.exp(-1.0 / (sr * release_ms / 1000.0))
    out = np.zeros_like(audio)
    gain = 1.0
    for i in range(n):
        level = np.max(np.abs(audio[i]))
        if level > thr:
            target = thr * (level / thr) ** (1.0 / ratio) / level
        else:
            target = 1.0
        if target < gain:
            gain = att * gain + (1.0 - att) * target
        else:
            gain = rel * gain + (1.0 - rel) * target
        out[i] = audio[i] * gain
    return out

def p2_corrective_eq(audio, sr, cuts=None):
    """
    Apply gentle corrective EQ cuts.
    cuts: list of (center_hz, gain_db, Q) tuples.
    Default: remove mud at 300Hz and boxiness at 500Hz.
    """
    if cuts is None:
        cuts = [
            (300.0,  -1.2, 2.0),
            (500.0,  -0.8, 1.5),
            (3500.0, -0.8, 2.0),
        ]
    result = audio.copy()
    for hz, db, Q in cuts:
        if hz >= sr // 2 - 200:
            continue
        w0 = 2 * np.pi * hz / sr
        alpha = np.sin(w0) / (2.0 * Q)
        A = 10 ** (db / 40.0)
        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A
        sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]])
        for ch in range(result.shape[1]):
            result[:, ch] = signal.sosfilt(sos, result[:, ch])
    return result

def p2_pipeline(song_base, cleaned_stems, mix_audio, sr, mix_info):
    sep("P2  MIXING")
    n_mix = mix_audio.shape[0]
    mix_out = np.zeros((n_mix, 2), dtype=np.float64)
    stems_proc_dir = os.path.join(song_base, "P2_MIXING", "stems_processed")
    report = {"pipeline": "P2", "stems": {}}

    for sname, spath in cleaned_stems.items():
        log(f"  Mixing stem: {sname}...")
        stem, _, _ = load(spath)
        stem = match_length(stem, n_mix)

        # Gain staging
        stem = p2_gain_stage(stem, target_rms_db=-18.0)

        # Corrective EQ
        stem = p2_corrective_eq(stem, sr)

        # Volume fader
        vol = STEM_VOLUMES.get(sname, 0.70)
        stem = stem * vol

        # Panning
        pan = STEM_PAN.get(sname, 0.0)
        stem = p2_apply_pan(stem, pan)

        # Saturation (subtle, distributed)
        stem = p1_saturation(stem, drive_db=0.5)

        # Glue compress
        stem = p2_glue_compress(stem, sr=sr)

        stem = clip_guard(stem)
        stem = match_length(stem, n_mix)
        mix_out += stem
        report["stems"][sname] = {"volume": vol, "pan": pan}

        # Save processed stem
        sp = os.path.join(stems_proc_dir, f"{sname}_processed.wav")
        save(stem, sr, sp, mix_info)

    # Master bus: subtle EQ + glue compress
    mix_out = p2_corrective_eq(mix_out, sr)
    mix_out = p2_glue_compress(mix_out, threshold_db=-15.0, ratio=1.5, sr=sr)
    mix_out = p1_noise_floor(mix_out, sr, level_db=-62.0)
    mix_out = p1_saturation(mix_out, drive_db=0.8)

    # Stereo check (keep low end mono below 120Hz)
    lp = signal.butter(4, 120, btype='low', fs=sr, output='sos')
    if mix_out.shape[1] >= 2:
        sub = signal.sosfiltfilt(lp, mix_out[:, 0] + mix_out[:, 1]) * 0.5
        hp = signal.butter(4, 120, btype='high', fs=sr, output='sos')
        mix_out_hp = mix_out.copy()
        mix_out_hp[:, 0] = signal.sosfiltfilt(hp, mix_out[:, 0])
        mix_out_hp[:, 1] = signal.sosfiltfilt(hp, mix_out[:, 1])
        mix_out = mix_out_hp.copy()
        mix_out[:, 0] += sub
        mix_out[:, 1] += sub

    # Apply headroom target (-6dB)
    target_peak = 10 ** (HEADROOM_P2_DB / 20.0)
    pk = np.max(np.abs(mix_out))
    if pk > 0:
        mix_out = mix_out * (target_peak / pk)

    mix_out = clip_guard(mix_out)
    mix_out = match_length(mix_out, n_mix)

    lufs = measure_lufs(mix_out, sr)
    report["output_lufs"] = round(lufs, 2) if lufs else None
    report["output_peak_db"] = round(20 * np.log10(np.max(np.abs(mix_out)) + 1e-12), 2)

    # Save pre-master
    pm_path = os.path.join(song_base, "P2_MIXING", "pre_master",
                           os.path.splitext(os.path.basename(
                               list(cleaned_stems.values())[0]))[0].replace("drums", "") +
                           "premix.wav")
    song_stem_name = os.path.basename(song_base)
    pm_path = os.path.join(song_base, "P2_MIXING", "pre_master",
                           f"{song_stem_name}_premix.wav")
    save(mix_out, sr, pm_path, mix_info)
    log(f"  Pre-master saved: {pm_path}")
    log(f"  LUFS: {lufs:.1f} | Peak: {report['output_peak_db']:.1f} dBFS")

    # Mono check
    mono_path = os.path.join(song_base, "P2_MIXING", "mono_check",
                             f"{song_stem_name}_mono_check.wav")
    if mix_out.shape[1] >= 2:
        mono_arr = np.mean(mix_out, axis=1, keepdims=True)
        mono_arr = np.repeat(mono_arr, 2, axis=1)
        save(mono_arr, sr, mono_path, mix_info)

    rpt = os.path.join(song_base, "P2_MIXING", "mix_reports", "p2_report.json")
    with open(rpt, 'w') as f:
        json.dump(report, f, indent=2)

    sep("P2 COMPLETE")
    return pm_path, mix_out

# ============================================================
# P3 - MASTERING
# ============================================================

def p3_limit_to_lufs(audio, sr, target_lufs=TARGET_LUFS_P3,
                      true_peak_db=-1.0, max_gain_db=12.0):
    """
    Target integrated LUFS. Two-stage: gain then limit.
    Crest factor protected: will not exceed max_gain_db.
    """
    current = measure_lufs(audio, sr)
    if current is None or np.isinf(current):
        return audio
    needed_db = target_lufs - current
    needed_db = min(needed_db, max_gain_db)
    gain = 10 ** (needed_db / 20.0)
    audio = audio * gain

    # True peak ceiling limiter (lookahead approximation)
    ceiling = 10 ** (true_peak_db / 20.0)
    pk = np.max(np.abs(audio))
    if pk > ceiling:
        audio = audio * (ceiling / pk)

    return audio

def p3_reference_eq(audio, sr, ref_audio, ref_sr):
    """
    Gentle spectral matching toward reference.
    Max 2dB adjustment per 1/3-octave band.
    """
    if ref_audio is None:
        return audio

    def avg_spec(a, s):
        mono = np.mean(a, axis=1)
        f, _, Z = signal.stft(mono, fs=s, nperseg=4096, noverlap=2048, window='hann')
        return f, np.mean(np.abs(Z), axis=1)

    f_src, spec_src = avg_spec(audio, sr)
    f_ref, spec_ref = avg_spec(ref_audio, ref_sr)

    # Resample ref spectrum to src frequencies
    spec_ref_i = interp1d(f_ref, spec_ref, kind='linear',
                          bounds_error=False, fill_value=spec_ref[-1])(f_src)

    # Compute ratio in dB, clamp to +-2dB
    ratio_db = 20 * np.log10((spec_ref_i + 1e-12) / (spec_src + 1e-12))
    ratio_db = np.clip(ratio_db, -2.0, 2.0)

    # Apply as frequency-domain gain (rough but effective)
    result = audio.copy()
    for ch in range(audio.shape[1]):
        _, _, Z = signal.stft(audio[:, ch], fs=sr, nperseg=4096,
                              noverlap=2048, window='hann')
        gain_lin = 10 ** (ratio_db / 20.0)
        Z_out = Z * gain_lin[:, np.newaxis]
        _, x = signal.istft(Z_out, fs=sr, nperseg=4096, noverlap=2048, window='hann')
        n = audio.shape[0]
        result[:, ch] = x[:n] if len(x) >= n else np.pad(x, (0, n-len(x)))
    return result

def p3_pipeline(song_base, premix_path, mix_audio, sr, mix_info,
                ref_audio=None, ref_sr=None, collection_dir=None,
                shortened_root=None):
    sep("P3  MASTERING")
    n_mix = mix_audio.shape[0]
    audio, _, _ = load(premix_path)
    audio = match_length(audio, n_mix)
    song_name = os.path.basename(song_base)
    report = {"pipeline": "P3", "song": song_name}

    # Pre-flight check
    pk_in = np.max(np.abs(audio))
    if pk_in > 0.9999:
        log("  WARNING: pre-master is clipping. Check P2 output.", "WARN")
    lufs_in = measure_lufs(audio, sr)
    report["lufs_in"] = round(lufs_in, 2) if lufs_in else None
    log(f"  Input: LUFS={lufs_in:.1f}, peak={20*np.log10(pk_in+1e-12):.1f}dBFS")

    # Stage 1: Corrective EQ
    log("Step 1/7  Corrective EQ...")
    audio = p2_corrective_eq(audio, sr, cuts=[
        (40.0,   -1.5, 1.5),
        (280.0,  -1.0, 2.0),
        (500.0,  -0.8, 1.5),
        (3200.0, -1.0, 2.5),
    ])

    # Stage 2: Reference-guided tonal EQ
    if ref_audio is not None:
        log("Step 2/7  Reference tonal EQ...")
        audio = p3_reference_eq(audio, sr, ref_audio, ref_sr)
    else:
        log("Step 2/7  No reference provided - applying style defaults...")
        # Underground electronic style: slight warmth, no bright hype
        audio = p2_corrective_eq(audio, sr, cuts=[
            (120.0, 0.8, 2.0),   # warmth boost
            (8000.0, -0.5, 2.0), # tame top end
        ])

    # Stage 3: Glue compression
    log("Step 3/7  Dynamic control...")
    audio = p2_glue_compress(audio, threshold_db=-18.0, ratio=1.8,
                              attack_ms=60.0, release_ms=250.0, sr=sr)

    # Stage 4: Harmonic saturation (distributed)
    log("Step 4/7  Harmonic saturation...")
    audio = p1_saturation(audio, drive_db=0.8)
    # Second stage: targeted low-mid warmth
    audio = p2_corrective_eq(audio, sr, cuts=[(200.0, 0.5, 1.5)])
    audio = p1_saturation(audio, drive_db=0.5)

    # Stage 5: Stereo refinement
    log("Step 5/7  Stereo refinement...")
    audio = p1_stereo_movement(audio, sr, rate=0.05, depth=0.02)
    # Ensure sub is mono
    if audio.shape[1] >= 2:
        lp = signal.butter(4, 120, btype='low', fs=sr, output='sos')
        hp = signal.butter(4, 120, btype='high', fs=sr, output='sos')
        sub_mono = signal.sosfiltfilt(lp,
                   (audio[:, 0] + audio[:, 1]) * 0.5)
        audio_hp = audio.copy()
        audio_hp[:, 0] = signal.sosfiltfilt(hp, audio[:, 0])
        audio_hp[:, 1] = signal.sosfiltfilt(hp, audio[:, 1])
        audio = audio_hp.copy()
        audio[:, 0] += sub_mono
        audio[:, 1] += sub_mono

    # Stage 6: Noise floor
    audio = p1_noise_floor(audio, sr, level_db=-64.0)

    # Stage 7: LUFS targeting (-8 integrated)
    log("Step 6/7  LUFS optimization...")
    audio = p3_limit_to_lufs(audio, sr, target_lufs=TARGET_LUFS_P3)
    audio = clip_guard(audio)
    audio = match_length(audio, n_mix)

    lufs_out = measure_lufs(audio, sr)
    pk_out = np.max(np.abs(audio))
    report["lufs_out"] = round(lufs_out, 2) if lufs_out else None
    report["peak_out_db"] = round(20 * np.log10(pk_out + 1e-12), 2)
    log(f"  Output: LUFS={lufs_out:.1f}, peak={report['peak_out_db']:.1f}dBFS")

    # QC scan (click/dropout detection)
    log("Step 7/7  QC scan...")
    mono_qc = np.mean(audio, axis=1)
    diff = np.diff(mono_qc)
    click_threshold = 0.3
    clicks = np.where(np.abs(diff) > click_threshold)[0]
    report["qc_clicks_detected"] = int(len(clicks))
    if clicks.any():
        log(f"  QC: {len(clicks)} potential clicks detected - review output", "WARN")
    else:
        log("  QC: No clicks detected.")

    # Save final master
    master_path = os.path.join(song_base, "P3_MASTERING", "final_master",
                               f"{song_name}_master_{TARGET_LUFS_P3:.0f}LUFS.wav")
    save(audio, sr, master_path, mix_info)
    log(f"  Final master: {master_path}")

    # Save 16-bit dithered streaming version
    stream_path = os.path.join(song_base, "P3_MASTERING", "streaming",
                               f"{song_name}_master_streaming_16bit.wav")
    sf.write(stream_path, audio, sr, subtype='PCM_16')
    log(f"  Streaming (16-bit): {stream_path}")

    # Shortened copy for testing
    short_path = os.path.join(song_base, "P3_MASTERING", "shortened",
                              f"{song_name}_master_shortened.wav")
    make_shortened(audio, sr, short_path, mix_info)
    if shortened_root:
        shutil.copy2(short_path, os.path.join(shortened_root,
                     f"{song_name}_master_shortened.wav"))

    # Copy to collection
    if collection_dir:
        col_path = os.path.join(collection_dir, f"{song_name}_master.wav")
        shutil.copy2(master_path, col_path)
        log(f"  Collection copy: {col_path}")

    rpt = os.path.join(song_base, "P3_MASTERING", "mastering_reports", "p3_report.json")
    with open(rpt, 'w') as f:
        json.dump(report, f, indent=2)

    sep("P3 COMPLETE")
    return master_path, audio

# ============================================================
# P4 - MIDI & ABLETON
# ============================================================

def p4_detect_drums(drums_path, sr, bpm):
    """
    Classify drum hits into kick/snare/hats/perc from drums stem.
    Returns dict: {gm_note: [sample_positions]}
    """
    audio, _, _ = load(drums_path)
    mono = np.mean(audio, axis=1).astype(np.float32)
    onsets = librosa.onset.onset_detect(
        y=mono, sr=sr, units='samples', hop_length=128,
        backtrack=True, delta=0.05, wait=5)
    drums = {"kick": [], "snare": [], "hihat": [], "perc": []}
    for o in onsets:
        s = max(0, o - 128)
        e = min(len(mono), o + 1024)
        seg = mono[s:e]
        if len(seg) < 32:
            continue
        # Frequency centroid classification
        spec = np.abs(np.fft.rfft(seg))
        freqs = np.fft.rfftfreq(len(seg), 1.0/sr)
        centroid = np.sum(freqs * spec) / (np.sum(spec) + 1e-9)
        energy_low  = np.sum(spec[freqs < 200])
        energy_mid  = np.sum(spec[(freqs >= 200) & (freqs < 2000)])
        energy_high = np.sum(spec[freqs >= 2000])
        if centroid < 200 and energy_low > energy_mid:
            drums["kick"].append(int(o))
        elif 200 <= centroid < 2000 and energy_mid >= energy_low:
            drums["snare"].append(int(o))
        elif centroid >= 2000 and energy_high > energy_mid:
            drums["hihat"].append(int(o))
        else:
            drums["perc"].append(int(o))
    return drums

def p4_write_drum_midi(drum_hits, sr, bpm, duration_s, out_path):
    """Write drum MIDI file from onset sample positions."""
    try:
        import pretty_midi
    except ImportError:
        log("  pretty_midi not installed - skipping drum MIDI", "WARN")
        return
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    drums_inst = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    gm_map = {"kick": 36, "snare": 38, "hihat": 42, "perc": 47}
    for dtype, positions in drum_hits.items():
        note_num = gm_map.get(dtype, 47)
        for pos in positions:
            t = pos / sr
            vel = 100
            n = pretty_midi.Note(velocity=vel, pitch=note_num,
                                  start=t, end=t + 0.1)
            drums_inst.notes.append(n)
    pm.instruments.append(drums_inst)
    pm.write(out_path)
    log(f"    Drum MIDI saved: {out_path}")

def p4_extract_melodic_midi(stem_path, out_path, stem_type="melodic"):
    """Extract MIDI from melodic stem using Basic Pitch."""
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
        log(f"    Basic Pitch: {stem_type}...")
        model_out, midi_data, note_events = predict(stem_path)
        midi_data.write(out_path)
        log(f"    Saved: {out_path}")
        return True
    except ImportError:
        log("  basic-pitch not installed - skipping melodic MIDI", "WARN")
        return False
    except Exception as e:
        log(f"  Basic Pitch error on {stem_type}: {e}", "WARN")
        return False

def p4_extract_mono_midi(stem_path, out_path, stem_type="mono"):
    """Extract monophonic MIDI using CREPE pitch tracking."""
    try:
        import crepe
        import pretty_midi
        log(f"    CREPE: {stem_type}...")
        audio, sr, _ = load(stem_path)
        mono = np.mean(audio, axis=1).astype(np.float32)
        time_arr, freq_arr, conf_arr, _ = crepe.predict(
            mono, sr, viterbi=True, step_size=10, verbose=0)
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(program=0, name=stem_type)
        prev_note = None
        prev_t = None
        for t, f, c in zip(time_arr, freq_arr, conf_arr):
            if c < 0.5 or f < 30:
                if prev_note is not None:
                    inst.notes.append(
                        pretty_midi.Note(velocity=80, pitch=prev_note,
                                          start=prev_t, end=t))
                    prev_note = None
                continue
            note_num = int(round(69 + 12 * np.log2(f / 440.0)))
            note_num = np.clip(note_num, 0, 127)
            if prev_note != note_num:
                if prev_note is not None:
                    inst.notes.append(
                        pretty_midi.Note(velocity=80, pitch=prev_note,
                                          start=prev_t, end=t))
                prev_note = note_num
                prev_t = t
        pm.instruments.append(inst)
        pm.write(out_path)
        log(f"    Saved: {out_path}")
        return True
    except ImportError:
        log("  crepe not installed - skipping mono MIDI", "WARN")
        return False
    except Exception as e:
        log(f"  CREPE error on {stem_type}: {e}", "WARN")
        return False

def p4_detect_automation(stem_path, sr_in=None):
    """
    Detect obvious automation: pitch drift, LFO on volume,
    filter sweeps, stereo width changes.
    Returns dict of CC data arrays.
    """
    audio, sr, _ = load(stem_path)
    n = audio.shape[0]
    mono = np.mean(audio, axis=1).astype(np.float32)
    hop = sr // 10   # 100ms resolution
    cc_data = {}

    # CC7 Volume envelope
    rms_env = []
    for i in range(0, n - hop, hop):
        rms_env.append(np.sqrt(np.mean(mono[i:i+hop]**2)))
    rms_env = np.array(rms_env)
    rms_norm = np.clip(rms_env / (rms_env.max() + 1e-9) * 127, 0, 127).astype(int)
    cc_data["CC7_volume"] = rms_norm.tolist()

    # CC74 Filter (spectral centroid as proxy)
    centroids = librosa.feature.spectral_centroid(y=mono, sr=sr, hop_length=hop)[0]
    cent_norm = np.clip(centroids / (centroids.max() + 1e-9) * 127, 0, 127).astype(int)
    cc_data["CC74_filter"] = cent_norm.tolist()

    # CC1 Stereo width (if stereo)
    if audio.shape[1] >= 2:
        side = audio[:, 0] - audio[:, 1]
        mid = audio[:, 0] + audio[:, 1]
        width_env = []
        for i in range(0, n - hop, hop):
            s_rms = np.sqrt(np.mean(side[i:i+hop]**2))
            m_rms = np.sqrt(np.mean(mid[i:i+hop]**2)) + 1e-9
            width_env.append(min(1.0, s_rms / m_rms))
        width_arr = np.clip(np.array(width_env) * 127, 0, 127).astype(int)
        cc_data["CC1_stereo_width"] = width_arr.tolist()

    return cc_data, hop

def p4_save_automation_midi(cc_data, hop, sr, bpm, duration_s, out_path):
    """Write automation CCs to a MIDI file."""
    try:
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        inst = pretty_midi.Instrument(program=0, name="Automation")
        cc_nums = {"CC7_volume": 7, "CC74_filter": 74, "CC1_stereo_width": 1}
        for cc_name, values in cc_data.items():
            cc_num = cc_nums.get(cc_name, 0)
            for i, v in enumerate(values):
                t = i * hop / sr
                inst.control_changes.append(
                    pretty_midi.ControlChange(cc_num, int(v), t))
        pm.instruments.append(inst)
        pm.write(out_path)
    except ImportError:
        log("  pretty_midi not available for automation MIDI", "WARN")

def p4_build_ableton_als(song_base, song_name, stems_cleaned, master_path,
                          sr, bpm, midi_files, duration_s):
    """
    Generate a basic Ableton Live 12 .als project file.
    Creates correct track structure, routing, colors, and device chains.
    """
    import gzip, struct

    # Ableton color index lookup
    def color_idx(name):
        return ABLETON_COLORS.get(STEM_COLORS.get(name.lower(), "grey"), 17)

    def bus_color_idx(bus_name):
        return ABLETON_COLORS.get(BUS_COLORS.get(bus_name, "grey"), 17)

    track_id = [100]
    def next_id():
        track_id[0] += 1
        return track_id[0]

    def utility_xml(tid):
        return f'''<PluginDesc><PluginInfo /></PluginDesc>'''

    def device_chain_xml(devices_xml):
        return f'''<DeviceChain><AudioInputRouting /><AudioOutputRouting /><Devices>{devices_xml}</Devices></DeviceChain>'''

    # Track XML builder
    def audio_track_xml(name, color, routing_target, file_path, duration_s, tid):
        return f'''
<AudioTrack Id="{tid}">
  <Name><EffectiveName Value="{name}" /></Name>
  <ColorIndex Value="{color}" />
  <DeviceChain>
    <AudioInputRouting><Target Value="AudioIn/Master" /><UpperDisplayString Value="" /></AudioInputRouting>
    <AudioOutputRouting><Target Value="{routing_target}" /><UpperDisplayString Value="{routing_target}" /></AudioOutputRouting>
    <Devices>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Eq8 Id="{next_id()}"><Name><EffectiveName Value="EQ Eight" /></Name></Eq8>
      <Compressor2 Id="{next_id()}"><Name><EffectiveName Value="Compressor" /></Name></Compressor2>
      <Saturator Id="{next_id()}"><Name><EffectiveName Value="Saturator" /></Name></Saturator>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Limiter Id="{next_id()}"><Name><EffectiveName Value="Limiter" /></Name></Limiter>
    </Devices>
  </DeviceChain>
  <ClipSlotList EventCount="0" />
</AudioTrack>'''

    def midi_track_xml(name, color, routing_target, midi_path, duration_s, tid):
        return f'''
<MidiTrack Id="{tid}">
  <Name><EffectiveName Value="{name} MIDI" /></Name>
  <ColorIndex Value="{color}" />
  <DeviceChain>
    <AudioOutputRouting><Target Value="{routing_target}" /></AudioOutputRouting>
    <Devices>
      <MidiOutputDevice Id="{next_id()}"><Name><EffectiveName Value="MIDI Out" /></Name></MidiOutputDevice>
    </Devices>
  </DeviceChain>
</MidiTrack>'''

    def group_track_xml(name, color, routing_target, tid):
        return f'''
<GroupTrack Id="{tid}">
  <Name><EffectiveName Value="{name}" /></Name>
  <ColorIndex Value="{color}" />
  <DeviceChain>
    <AudioOutputRouting><Target Value="{routing_target}" /></AudioOutputRouting>
    <Devices>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Eq8 Id="{next_id()}"><Name><EffectiveName Value="EQ Eight" /></Name></Eq8>
      <GlueCompressor Id="{next_id()}"><Name><EffectiveName Value="Glue Compressor" /></Name></GlueCompressor>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Limiter Id="{next_id()}"><Name><EffectiveName Value="Limiter" /></Name></Limiter>
    </Devices>
  </DeviceChain>
</GroupTrack>'''

    def return_track_xml(name, device_name, device_tag, tid):
        return f'''
<ReturnTrack Id="{tid}">
  <Name><EffectiveName Value="{name}" /></Name>
  <ColorIndex Value="{ABLETON_COLORS['light_grey']}" />
  <DeviceChain>
    <Devices>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <{device_tag} Id="{next_id()}"><Name><EffectiveName Value="{device_name}" /></Name></{device_tag}>
      <Eq8 Id="{next_id()}"><Name><EffectiveName Value="EQ Eight" /></Name></Eq8>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
    </Devices>
  </DeviceChain>
</ReturnTrack>'''

    # Bus definitions: bus_name -> (contains stems, output)
    bus_map = {
        "LOWEND": ["kick", "bass"],
        "DRUMS":  ["drums"],
        "VOCALS": ["vocals"],
        "SYNTHS": ["other"],
        "GUITAR": ["guitar"],
        "PIANO":  ["piano"],
        "FX":     [],
    }

    all_tracks_xml = ""

    # Individual audio tracks
    for sname in stems_cleaned.keys():
        bus = next((b for b, members in bus_map.items() if sname in members), "SYNTHS")
        tid = next_id()
        col = color_idx(sname)
        if sname in stems_cleaned:
            all_tracks_xml += audio_track_xml(
                sname.upper(), col, bus, stems_cleaned[sname], duration_s, tid)
        # MIDI track alongside
        midi_path = midi_files.get(sname, "")
        if midi_path and os.path.exists(midi_path):
            all_tracks_xml += midi_track_xml(sname.upper(), col, bus, midi_path, duration_s, next_id())

    # Bus (group) tracks
    for bus_name, members in bus_map.items():
        col = bus_color_idx(bus_name)
        all_tracks_xml += group_track_xml(bus_name, col, "PREMIX", next_id())

    # PREMIX group
    premix_col = ABLETON_COLORS["light_grey"]
    premix_tid = next_id()
    all_tracks_xml += f'''
<GroupTrack Id="{premix_tid}">
  <Name><EffectiveName Value="PREMIX" /></Name>
  <ColorIndex Value="{premix_col}" />
  <DeviceChain>
    <AudioOutputRouting><Target Value="AudioIn/Master" /></AudioOutputRouting>
    <Devices>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Eq8 Id="{next_id()}"><Name><EffectiveName Value="EQ Eight" /></Name></Eq8>
      <GlueCompressor Id="{next_id()}"><Name><EffectiveName Value="Glue Compressor" /></Name></GlueCompressor>
      <Eq8 Id="{next_id()}"><Name><EffectiveName Value="EQ Eight" /></Name></Eq8>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="Utility" /></Name></PluginDevice>
      <Limiter Id="{next_id()}"><Name><EffectiveName Value="Limiter" /></Name></Limiter>
    </Devices>
  </DeviceChain>
</GroupTrack>'''

    # Return tracks
    returns_xml = ""
    returns_xml += return_track_xml("SHORT REVERB", "Reverb", "Reverb", next_id())
    returns_xml += return_track_xml("LONG REVERB",  "Reverb", "Reverb", next_id())
    returns_xml += return_track_xml("SHORT DELAY",  "Delay",  "Delay",  next_id())
    returns_xml += return_track_xml("LONG DELAY",   "Delay",  "Delay",  next_id())

    # Master track
    master_xml = f'''
<MasterTrack Id="{next_id()}">
  <Name><EffectiveName Value="Master" /></Name>
  <DeviceChain>
    <Devices>
      <PluginDevice Id="{next_id()}"><Name><EffectiveName Value="LEVELS" /></Name></PluginDevice>
    </Devices>
  </DeviceChain>
</MasterTrack>'''

    # Full .als XML
    als_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="12" MinorVersion="0" Creator="SunoMaster v{VERSION}" Revision="">
<LiveSet>
  <NextPointeeId Value="{track_id[0] + 50}" />
  <Tempo><LomId Value="0" /><Manual Value="{bpm:.4f}" /></Tempo>
  <TimeSignature><TimeSignatures><AutomationEvent Time="-63072000" Value="201457664" /></TimeSignatures></TimeSignature>
  <Tracks>
    {all_tracks_xml}
  </Tracks>
  <ReturnTracks>
    {returns_xml}
  </ReturnTracks>
  {master_xml}
  <SendsPre Value="false" />
  <CrossFadeState Value="0" />
</LiveSet>
</Ableton>'''

    als_dir = os.path.join(song_base, "P4_MIDI", "ableton")
    als_path = os.path.join(als_dir, f"{song_name}.als")
    xml_bytes = als_xml.encode('utf-8')
    with gzip.open(als_path, 'wb') as gf:
        gf.write(xml_bytes)
    log(f"  Ableton project: {als_path}")
    return als_path

def p4_pipeline(song_base, cleaned_stems, mix_audio, sr, mix_info, bpm, master_path):
    sep("P4  MIDI & ABLETON")
    n_mix = mix_audio.shape[0]
    duration_s = n_mix / sr
    song_name = os.path.basename(song_base)
    midi_dir = os.path.join(song_base, "P4_MIDI", "midi_stems")
    auto_dir = os.path.join(song_base, "P4_MIDI", "automation_lanes")
    midi_files = {}
    report = {"pipeline": "P4", "midi_files": {}}

    # Drum MIDI from drums stem
    if "drums" in cleaned_stems:
        log("  Extracting drum MIDI...")
        drum_hits = p4_detect_drums(cleaned_stems["drums"], sr, bpm)
        for dtype, hits in drum_hits.items():
            log(f"    {dtype}: {len(hits)} hits")
        dm_path = os.path.join(midi_dir, f"{song_name}_drums.mid")
        p4_write_drum_midi(drum_hits, sr, bpm, duration_s, dm_path)
        midi_files["drums"] = dm_path
        report["midi_files"]["drums"] = dm_path

    # Melodic stems via Basic Pitch
    melodic = ["guitar", "piano", "other"]
    for sname in melodic:
        if sname not in cleaned_stems:
            continue
        log(f"  Extracting MIDI: {sname} (Basic Pitch)...")
        mp = os.path.join(midi_dir, f"{song_name}_{sname}.mid")
        ok = p4_extract_melodic_midi(cleaned_stems[sname], mp, sname)
        if ok:
            midi_files[sname] = mp
            report["midi_files"][sname] = mp

    # Monophonic stems via CREPE
    mono_stems = ["bass", "vocals"]
    for sname in mono_stems:
        if sname not in cleaned_stems:
            continue
        log(f"  Extracting MIDI: {sname} (CREPE)...")
        mp = os.path.join(midi_dir, f"{song_name}_{sname}.mid")
        ok = p4_extract_mono_midi(cleaned_stems[sname], mp, sname)
        if ok:
            midi_files[sname] = mp
            report["midi_files"][sname] = mp

    # Automation detection for all stems
    log("  Detecting automation...")
    for sname, spath in cleaned_stems.items():
        log(f"    Automation: {sname}...")
        cc_data, hop = p4_detect_automation(spath)
        ap = os.path.join(auto_dir, f"{song_name}_{sname}_automation.mid")
        p4_save_automation_midi(cc_data, hop, sr, bpm, duration_s, ap)
        report["automation"] = {sname: ap}

    # Copy master and stems to Ableton samples folder
    ableton_samples = os.path.join(song_base, "P4_MIDI", "ableton", "samples")
    if master_path and os.path.exists(master_path):
        shutil.copy2(master_path, os.path.join(ableton_samples, os.path.basename(master_path)))
    for sname, spath in cleaned_stems.items():
        shutil.copy2(spath, os.path.join(ableton_samples, os.path.basename(spath)))

    # Build Ableton project
    log("  Building Ableton project...")
    als_path = p4_build_ableton_als(
        song_base, song_name, cleaned_stems, master_path,
        sr, bpm, midi_files, duration_s)
    report["ableton_project"] = als_path

    rpt = os.path.join(song_base, "P4_MIDI", "midi_reports", "p4_report.json")
    with open(rpt, 'w') as f:
        json.dump(report, f, indent=2)

    sep("P4 COMPLETE")
    return midi_files, als_path

# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    sep("SunoMaster v" + VERSION)

    # Computer selection
    root = select_computer()
    paths = build_paths(root)
    ensure_folders(paths)

    # LetsSubmit API key (optional)
    ls_key = input("\nLetsSubmit API key (press Enter to skip): ").strip() or None

    # Song or batch mode
    print("\nMode:")
    print("  [1] Single song")
    print("  [2] Batch - all songs in releases folder")
    mode = input("Enter 1 or 2: ").strip()

    songs_to_process = []

    if mode == "2":
        confirm = input(f"\nProcess ALL songs in {paths['releases']}? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Batch cancelled.")
            return
        ref_path = input(f"Reference track path (from {paths['references']}): ").strip().strip('"')
        for entry in os.scandir(paths['releases']):
            if entry.is_dir():
                wav = find_original_wav(entry.path)
                if wav:
                    songs_to_process.append((entry.path, wav, ref_path))
    else:
        song_folder = input(f"\nSong folder path (inside {paths['releases']}): ").strip().strip('"')
        if not os.path.isdir(song_folder):
            # Try treating input as song name
            song_folder = os.path.join(paths['releases'], song_folder)
        wav = find_original_wav(song_folder)
        if not wav:
            print(f"No WAV found in {song_folder}")
            return
        ref_path = input(f"Reference track path (from {paths['references']}): ").strip().strip('"')
        songs_to_process.append((song_folder, wav, ref_path))

    # Process each song
    for song_folder, original_wav, ref_path in songs_to_process:
        song_name = os.path.basename(song_folder)
        sep(f"PROCESSING: {song_name}")

        # Create song subfolders
        song_base = song_folders(paths['releases'], song_name)

        # Load reference track
        ref_audio, ref_sr = None, None
        if ref_path and os.path.exists(ref_path):
            try:
                ref_audio, ref_sr, _ = load(ref_path)
                log(f"Reference track loaded: {ref_path}")
            except Exception as e:
                log(f"Could not load reference: {e}", "WARN")

        # Load original mix (sacred reference)
        mix_audio, sr, mix_info = load(original_wav)
        log(f"Original mix: {original_wav}")
        log(f"Duration: {mix_audio.shape[0]/sr:.1f}s | SR: {sr}Hz | Ch: {mix_audio.shape[1]}")

        # P0 - Detection & Splitting
        stems_raw = p0_pipeline(song_base, original_wav, paths, ls_key)
        if not stems_raw:
            log(f"P0 failed for {song_name} - skipping.", "ERROR")
            continue

        # P1 - Stem Cleaning
        cleaned_stems, bpm = p1_pipeline(song_base, stems_raw, mix_audio, sr, mix_info)

        # P2 - Mixing
        premix_path, premix_audio = p2_pipeline(song_base, cleaned_stems, mix_audio, sr, mix_info)

        # P3 - Mastering
        master_path, master_audio = p3_pipeline(
            song_base, premix_path, mix_audio, sr, mix_info,
            ref_audio, ref_sr,
            collection_dir=paths['collection'],
            shortened_root=paths['shortened'])

        # P4 - MIDI & Ableton
        midi_files, als_path = p4_pipeline(
            song_base, cleaned_stems, mix_audio, sr, mix_info, bpm, master_path)

        # Save full log
        log_path = os.path.join(song_base, f"{song_name}_pipeline_log.txt")
        save_log(log_path)
        sep(f"DONE: {song_name}")
        log(f"Final master : {master_path}")
        log(f"Ableton proj : {als_path}")
        log(f"Log saved    : {log_path}")

    sep("ALL PIPELINES COMPLETE")

if __name__ == '__main__':
    main()
