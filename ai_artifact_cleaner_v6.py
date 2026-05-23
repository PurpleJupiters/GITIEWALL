"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘           AI ARTIFACT CLEANER  â€”  v6.0  "FINAL"                            â•‘
â•‘                                                                              â•‘
â•‘  Target detector : LetsSubmit bAbI v2 (MERT + LogReg, 87.67% accuracy)     â•‘
â•‘  Basis           : arXiv:2506.19108 (fingerprint analysis/reporting only)   â•‘
â•‘                                                                              â•‘
â•‘  DESIGN CONTRACT â€” must be read before modifying this file                  â•‘
â•‘  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  â•‘
â•‘  This script is permitted to make ONLY the following changes to audio:      â•‘
â•‘                                                                              â•‘
â•‘  A. NOISE FLOOR  â€” add low-level broadband noise simulating recording        â•‘
â•‘     environment. Targets MERT's acoustic-environment features. No timing    â•‘
â•‘     change. No frequency content above Nyquist. No loudness change > 0.5%.  â•‘
â•‘                                                                              â•‘
â•‘  B. STEREO MOVEMENT  â€” slowly-varying stereo width via M/S LFO. Targets     â•‘
â•‘     MERT's stereo-imaging features. No timing change. No mono content       â•‘
â•‘     affected. Depth â‰¤ 5%. Rate â‰¤ 0.2 Hz.                                   â•‘
â•‘                                                                              â•‘
â•‘  C. HARMONIC SATURATION  â€” tanh soft-clip adding odd harmonics. Targets     â•‘
â•‘     MERT's timbral/analog-character features. No timing change. Drive       â•‘
â•‘     â‰¤ 1.5 dB so THD remains inaudible.                                      â•‘
â•‘                                                                              â•‘
â•‘  D. GRID QUANTIZATION  â€” slip-quantize audio to a 128-subdivision beat      â•‘
â•‘     grid. Each detected onset is shifted (never stretched) to the nearest   â•‘
â•‘     grid line. Maximum shift = half a grid cell (â‰ˆ1â€“3 ms). Crossfade of    â•‘
â•‘     256 samples applied at every edit point to prevent clicks.              â•‘
â•‘     This is the ONLY permitted timing modification.                         â•‘
â•‘                                                                              â•‘
â•‘  NOTHING ELSE is permitted. No STFT modifications (they caused note-        â•‘
â•‘  skipping). No pitch shifting. No EQ. No compression. No filtering          â•‘
â•‘  beyond what Stages Aâ€“D specifically require.                               â•‘
â•‘                                                                              â•‘
â•‘  Usage                                                                       â•‘
â•‘    python ai_artifact_cleaner.py input.wav output.wav                        â•‘
â•‘    python ai_artifact_cleaner.py input.wav output.wav --no_quantize         â•‘
â•‘    python ai_artifact_cleaner.py input.wav --analyze_only                   â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
"""

import argparse, hashlib, json, os, time, warnings
warnings.filterwarnings('ignore')

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d
from scipy.interpolate import interp1d
import librosa
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

# â”€â”€ Paper constants (arXiv:2506.19108) â€” fingerprint only â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FMIN, FMAX, N_BINS, DETREND_WIN = 5000, 16000, 128, 18

# â”€â”€ Processing defaults â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
D_STFT_WIN        = 4096   # for fingerprint analysis only â€” NOT used in processing
D_STFT_HOP        = 1024
D_NOISE_DB        = -58.0  # Stage A: noise floor level
D_STEREO_RATE     = 0.07   # Stage B: LFO rate Hz
D_STEREO_DEPTH    = 0.03   # Stage B: width modulation depth (3%)
D_DRIVE_DB        = 1.0    # Stage C: saturation drive dB
D_GRID_DIV        = 128    # Stage D: subdivisions per beat
D_THRESHOLD       = 0.15   # fingerprint reporting threshold
QUANTIZE_CF_LEN   = 256    # crossfade samples at each edit point


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  FINGERPRINT  (analysis/reporting only â€” not used in processing)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def compute_fingerprint(mono, sr, stft_win=D_STFT_WIN, stft_hop=D_STFT_HOP,
                        fmax=FMAX):
    """
    Replicates the arXiv:2506.19108 fingerprint method.
    Used for before/after reporting only. Does NOT drive processing decisions.
    """
    f, _, Zxx = signal.stft(mono, fs=sr, nperseg=stft_win,
                             noverlap=stft_win - stft_hop, window='hann')
    avg       = np.mean(np.abs(Zxx), axis=1)
    mask      = (f >= FMIN) & (f <= fmax)
    bfreqs    = np.linspace(FMIN, fmax, N_BINS)
    s128      = interp1d(f[mask], avg[mask], kind='linear',
                         bounds_error=False, fill_value=0.0)(bfreqs)
    lmin      = minimum_filter1d(s128, size=DETREND_WIN)
    raw       = s128 - lmin
    peak      = raw.max()
    norm      = raw / peak if peak > 0 else raw.copy()
    return dict(norm=norm, raw=raw, bfreqs=bfreqs,
                avg=avg, f=f, peak=float(peak))


def score_proxy(fp):
    """Directional proxy score. Not calibrated to LetsSubmit."""
    top8  = np.sort(fp['norm'])[-8:]
    logit = (top8.mean() - 0.35) * 8.0
    return float(1.0 / (1.0 + np.exp(-logit)))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STAGE A â€” NOISE FLOOR
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def stage_noise_floor(audio, sr, level_db, seed=None):
    """
    Adds low-level broadband noise replicating a quiet recording environment
    (room noise, preamp hiss, tape hiss). Targets MERT's acoustic-environment
    encoding â€” AI generators produce unnaturally silent noise floors.

    Implementation:
      â€¢ White noise scaled to level_db RMS
      â€¢ High-pass at 40 Hz to avoid muddying sub-bass
      â€¢ Low-pass at min(18 kHz, Nyquist-200 Hz) for realistic character
      â€¢ Independent noise per channel for natural stereo uncorrelation
      â€¢ No timing change â€” pure sample-wise addition
    """
    n, nch = audio.shape
    amp    = 10 ** (level_db / 20.0)
    rng    = np.random.default_rng(seed=seed)  # file-specific seed from main() for unique noise per file

    # Design broadband shelf filters once
    hp_sos = signal.butter(2, 40,                      btype='high', fs=sr, output='sos')
    lp_sos = signal.butter(2, min(18000, sr//2 - 200), btype='low',  fs=sr, output='sos')

    noise_out = np.zeros_like(audio)
    for ch in range(nch):
        noise = rng.standard_normal(n) * amp
        noise = signal.sosfiltfilt(hp_sos, noise)
        noise = signal.sosfiltfilt(lp_sos, noise)
        noise_out[:, ch] = noise

    return audio + noise_out


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STAGE B â€” STEREO MOVEMENT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def stage_stereo_movement(audio, sr, rate_hz, depth):
    """
    Applies slowly-varying stereo width via mid-side LFO.
    Targets MERT's stereo-imaging features â€” AI audio has static, synthetic
    stereo imaging. A gentle LFO mimics the natural slight movement of a
    real acoustic environment.

    Implementation:
      â€¢ Convert L/R to M/S (mid-side)
      â€¢ Multiply side channel by (1 + depth * sin(2Ï€ * rate * t))
      â€¢ Convert back to L/R
      â€¢ Mid channel (sum) is NEVER modified â€” mono content preserved exactly
      â€¢ No timing change â€” sample-wise envelope multiplication
      â€¢ For mono input: returns input unchanged
    """
    if audio.shape[1] < 2:
        return audio.copy()

    n         = audio.shape[0]
    t         = np.arange(n) / sr
    lfo       = 1.0 + depth * np.sin(2.0 * np.pi * rate_hz * t)

    mid  = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5 * lfo

    out       = np.zeros_like(audio)
    out[:, 0] = mid + side
    out[:, 1] = mid - side
    return out


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STAGE C â€” HARMONIC SATURATION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def stage_saturation(audio, drive_db):
    """
    Tanh soft-clipping adding odd harmonics characteristic of analog equipment.
    Targets MERT's timbral features â€” AI audio has pristine, digital harmonic
    content. Subtle saturation mimics transformer, tape, or tube character.

    Implementation:
      â€¢ drive = 10^(drive_db/20) â€” amplitude multiplier before tanh
      â€¢ y = tanh(x * drive) / drive â€” preserves unity gain at low levels
      â€¢ At drive_db=1.0 dB (driveâ‰ˆ1.12): THD < 0.1% â€” below audibility
      â€¢ At drive_db=1.5 dB (driveâ‰ˆ1.19): THD < 0.3% â€” still inaudible
      â€¢ No timing change â€” point-wise nonlinearity
    """
    drive = 10 ** (drive_db / 20.0)
    return np.tanh(audio * drive) / drive


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STAGE D â€” GRID QUANTIZATION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _crossfade(audio, pos, shift, cf_len):
    """
    Apply a shift of `shift` samples at position `pos` using crossfade.
    Crossfade length = cf_len samples.
    The audio before pos is from the original; after pos+cf_len from shifted.
    No new content is created â€” only existing samples are repositioned.
    """
    n, nch = audio.shape
    out    = audio.copy()

    # Build fade curves
    fade_out = np.linspace(1.0, 0.0, cf_len)
    fade_in  = np.linspace(0.0, 1.0, cf_len)

    for ch in range(nch):
        # Region before the edit: original samples
        orig_seg = audio[max(0, pos):min(n, pos + cf_len), ch]
        # Region after shift: shifted samples
        shift_start = max(0, pos + shift)
        shift_end   = min(n, pos + shift + cf_len)
        shift_seg   = audio[shift_start:shift_end, ch]

        # Trim to same length
        bl = min(len(orig_seg), len(shift_seg), cf_len)
        if bl < 4:
            continue

        blended = (orig_seg[:bl] * fade_out[:bl]
                   + shift_seg[:bl] * fade_in[:bl])

        out[pos:pos + bl, ch] = blended
        # After crossfade zone: use shifted content
        post_start = pos + bl
        post_shift = shift_start + bl
        copy_len   = min(n - post_start, n - post_shift)
        if copy_len > 0:
            out[post_start:post_start + copy_len, ch] = (
                audio[post_shift:post_shift + copy_len, ch])

    return out


def stage_grid_quantize(audio, sr, grid_divisions, bpm_override=None):
    """
    Slip-quantize audio to a beat grid with `grid_divisions` subdivisions/beat.

    Algorithm:
      1. Detect BPM (or use bpm_override).
      2. Compute grid-cell duration in samples:
            cell = (60 / BPM / grid_divisions) * sr
      3. Detect onset sample positions using librosa (backtracked to transient).
      4. For each onset, compute nearest grid line and the required shift:
            shift = round(onset / cell) * cell - onset
      5. Reject shifts larger than half a cell (safety guard).
      6. Apply each shift as a crossfade edit (256 samples) â€” no time-stretching.
      7. Accumulate shifts so later onsets are adjusted correctly.

    Maximum timing change per onset â‰¤ cell/2 samples.
    At 128 BPM, 128 divisions/beat:
        cell = 60/(128*128)*44100 â‰ˆ 162 samples â‰ˆ 3.7 ms
        max shift â‰ˆ 81 samples â‰ˆ 1.8 ms  (imperceptible)

    Returns: (quantized_audio, bpm, n_onsets_shifted, max_shift_ms)
    """
    n, nch = audio.shape
    mono   = np.mean(audio, axis=1).astype(np.float32)

    # BPM detection
    if bpm_override:
        bpm = float(bpm_override)
    else:
        tempo, _ = librosa.beat.beat_track(y=mono, sr=sr, units='time')
        bpm = float(np.atleast_1d(tempo)[0])

    if bpm <= 0 or bpm > 300:
        print(f"  [quantize] BPM detection failed ({bpm:.1f}). Skipping.")
        return audio.copy(), bpm, 0, 0.0

    cell_samples = (60.0 / bpm / grid_divisions) * sr
    max_shift_s  = int(cell_samples / 2)

    # Onset detection â€” use backtracked onsets for accuracy
    onset_samples = librosa.onset.onset_detect(
        y=mono, sr=sr, units='samples',
        hop_length=256, backtrack=True,
        pre_max=3, post_max=3, pre_avg=3, post_avg=5, delta=0.07, wait=10)

    result          = audio.copy()
    cumulative_shift = 0
    n_shifted       = 0
    max_shift_seen  = 0

    for onset_raw in onset_samples:
        # Adjust for shifts already applied to earlier onsets
        onset = onset_raw + cumulative_shift
        if onset < 0 or onset >= n:
            continue

        # Nearest grid line
        nearest_grid = int(round(onset / cell_samples) * cell_samples)
        shift        = nearest_grid - onset

        # Safety guard: reject if larger than half cell
        if abs(shift) > max_shift_s or shift == 0:
            continue

        result = _crossfade(result, max(0, onset - QUANTIZE_CF_LEN // 2),
                            shift, QUANTIZE_CF_LEN)
        cumulative_shift += shift
        n_shifted        += 1
        max_shift_seen    = max(max_shift_seen, abs(shift))

    max_shift_ms = max_shift_seen / sr * 1000.0
    return result, bpm, n_shifted, max_shift_ms


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  REPORTING
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def print_fingerprint_table(fp_b, fp_a, threshold):
    high = np.where(fp_b['norm'] > threshold)[0]
    top  = sorted(zip(fp_b['norm'][high], fp_b['raw'][high],
                      fp_b['bfreqs'][high], high), reverse=True)[:16]
    print(f"\n  {'Bin':>5}  {'Hz':>7}  "
          f"{'Norm_B':>7}  {'Norm_A':>7}  {'Î”Norm':>7}  "
          f"{'Raw_B':>10}  {'Raw_A':>10}")
    print(f"  {'â”€'*5}  {'â”€'*7}  {'â”€'*7}  {'â”€'*7}  "
          f"{'â”€'*7}  {'â”€'*10}  {'â”€'*10}")
    for nb, rb, hz, bi in top:
        na = fp_a['norm'][bi]; ra = fp_a['raw'][bi]; d = na - nb
        mk = ' â†“' if d < -0.01 else (' â†‘' if d > 0.01 else '  ')
        print(f"  {bi:>5}  {hz:>7.0f}  {nb:>7.3f}  {na:>7.3f}  "
              f"{d:>+7.3f}{mk}  {rb:>10.6f}  {ra:>10.6f}")
    sb = score_proxy(fp_b); sa = score_proxy(fp_a)
    print(f"\n  Score proxy (directional):  "
          f"{sb*100:.1f}%  â†’  {sa*100:.1f}%  ({(sa-sb)*100:+.1f}pp)")
    print(f"  Peak raw:   {fp_b['peak']:.6f}  â†’  {fp_a['peak']:.6f}")
    print(f"  Mean norm:  {fp_b['norm'].mean():.4f}  â†’  "
          f"{fp_a['norm'].mean():.4f}")


def save_plot(fp_b, fp_a, threshold, title_suffix, path):
    fig, axes = plt.subplots(3, 1, figsize=(15, 10), facecolor='#0d1117')
    fig.suptitle(f"AI Artifact Fingerprint  v6.0  â€”  {title_suffix}",
                 color='white', fontsize=13, fontweight='bold')
    x  = np.arange(N_BINS)
    bf = fp_b['bfreqs']
    for ax, data, col, lbl in [
            (axes[0], fp_b['norm'], '#f85149', 'Before'),
            (axes[1], fp_a['norm'], '#3fb950', 'After')]:
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e'); ax.spines[:].set_color('#30363d')
        ax.bar(x, data, color=col, alpha=0.85, width=0.85)
        ax.axhline(threshold, color='#e3b341', ls='--', lw=1.2,
                   label=f'threshold {threshold}')
        ax.set_title(lbl, color=col, fontsize=10)
        ax.set_ylabel('Norm. residual', color='#8b949e')
        ax.set_ylim(0, 1.08)
        ax.legend(facecolor='#161b22', labelcolor='white', fontsize=8)
        for bi in np.argsort(data)[-5:]:
            ax.annotate(f"{bf[bi]:.0f}",
                        xy=(bi, data[bi]), xytext=(bi, data[bi] + 0.04),
                        color='#e3b341', fontsize=6.5, ha='center',
                        arrowprops=dict(arrowstyle='-', color='#555'))
    ax = axes[2]
    ax.set_facecolor('#161b22')
    ax.tick_params(colors='#8b949e'); ax.spines[:].set_color('#30363d')
    delta = fp_a['norm'] - fp_b['norm']
    ax.bar(x, delta, color=['#3fb950' if d < 0 else '#f85149' for d in delta],
           alpha=0.85, width=0.85)
    ax.axhline(0, color='#8b949e', lw=0.8)
    ax.set_title('Î” (After âˆ’ Before)  â€”  green = improved',
                 color='#8b949e', fontsize=10)
    ax.set_ylabel('Î” residual', color='#8b949e')
    ax.set_xlabel('Bin  (0 = 5 kHz  â†’  127 = 16 kHz)', color='#8b949e')
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()


def save_json(fp_b, fp_a, params, dur, stage_log, path):
    def t8(fp):
        return [{'bin': int(i), 'hz': round(float(fp['bfreqs'][i]), 1),
                 'norm': round(float(fp['norm'][i]), 4),
                 'raw':  round(float(fp['raw'][i]),  6)}
                for i in np.argsort(fp['norm'])[-8:][::-1]]
    sb = score_proxy(fp_b); sa = score_proxy(fp_a)
    report = dict(
        version='v6.0',
        timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        params=params, duration_s=round(dur, 2),
        note=('Score proxy is directional only. '
              'Test on LetsSubmit (letssubmit.com/ai-music-checker) for real score.'),
        score_proxy_before=round(sb * 100, 1),
        score_proxy_after=round(sa * 100, 1),
        peak_raw_before=round(fp_b['peak'], 6),
        peak_raw_after=round(fp_a['peak'],  6),
        mean_norm_before=round(float(fp_b['norm'].mean()), 4),
        mean_norm_after=round(float(fp_a['norm'].mean()),  4),
        stage_log=stage_log,
        top_bins_before=t8(fp_b),
        top_bins_after=t8(fp_a),
    )
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  MAIN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def main():
    ap = argparse.ArgumentParser(
        description='AI Artifact Cleaner v6.0 â€” MERT-targeting, timing-safe',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    ap.add_argument('input',           help='Input WAV file')
    ap.add_argument('output', nargs='?', default='', help='Output WAV file')
    ap.add_argument('--analyze_only',  action='store_true',
                    help='Fingerprint analysis only, no processing')

    # Stage A
    ap.add_argument('--noise_db',     type=float, default=D_NOISE_DB,
                    help='Stage A: noise floor level dBFS')
    ap.add_argument('--no_noise',     action='store_true',
                    help='Disable Stage A')

    # Stage B
    ap.add_argument('--stereo_rate',  type=float, default=D_STEREO_RATE,
                    help='Stage B: LFO rate Hz')
    ap.add_argument('--stereo_depth', type=float, default=D_STEREO_DEPTH,
                    help='Stage B: width modulation depth 0â€“1')
    ap.add_argument('--no_stereo',    action='store_true',
                    help='Disable Stage B')

    # Stage C
    ap.add_argument('--drive_db',     type=float, default=D_DRIVE_DB,
                    help='Stage C: saturation drive dB')
    ap.add_argument('--no_saturate',  action='store_true',
                    help='Disable Stage C')

    # Stage D
    ap.add_argument('--grid_div',     type=int,   default=D_GRID_DIV,
                    help='Stage D: grid subdivisions per beat')
    ap.add_argument('--bpm',          type=float, default=0.0,
                    help='Stage D: BPM override (0 = auto-detect)')
    ap.add_argument('--no_quantize',  action='store_true',
                    help='Disable Stage D')

    # Output
    ap.add_argument('--threshold',    type=float, default=D_THRESHOLD,
                    help='Fingerprint reporting threshold')
    ap.add_argument('--plot',         default='')
    ap.add_argument('--json',         default='')

    a = ap.parse_args()

    if not a.analyze_only and not a.output:
        ap.error('output path required unless --analyze_only')

    SEP = 'â•' * 66
    print(f"\n{SEP}")
    print(f"  AI Artifact Cleaner  v6.0")
    print(f"  Input  : {os.path.basename(a.input)}")
    if not a.analyze_only:
        print(f"  Output : {os.path.basename(a.output)}")
    print(SEP)

    # â”€â”€ Load â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    audio, sr = sf.read(a.input, always_2d=True)
    info      = sf.info(a.input)
    n, nch    = audio.shape
    dur       = n / sr
    print(f"  {dur:.1f}s  |  {sr} Hz  |  {nch}ch  |  {info.subtype}")

    # Preserve bit depth for output
    if 'PCM_16' in info.subtype:
        out_subtype = 'PCM_16'
    elif 'PCM_24' in info.subtype:
        out_subtype = 'PCM_24'
    else:
        out_subtype = 'PCM_24'

    fmax  = min(FMAX, sr // 2 - 200)
    audio = audio.astype(np.float64)
    mono  = np.mean(audio, axis=1)

    # â”€â”€ Fingerprint before â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n  Computing fingerprint...")
    fp_b = compute_fingerprint(mono, sr, fmax=fmax)
    print(f"  Score proxy: {score_proxy(fp_b)*100:.1f}%  "
          f"(test on LetsSubmit for real score)")

    if a.analyze_only:
        high = np.where(fp_b['norm'] > a.threshold)[0]
        top  = sorted(zip(fp_b['norm'][high], fp_b['bfreqs'][high], high),
                      reverse=True)
        print(f"  {len(high)} bins above threshold {a.threshold}\n")
        print(f"  {'Bin':>5}  {'Hz':>7}  {'Norm':>7}  {'Raw':>10}")
        for nv, hz, bi in top:
            print(f"  {bi:>5}  {hz:>7.0f}  {nv:>7.3f}  "
                  f"{fp_b['raw'][bi]:>10.6f}")
        print(f"\n{SEP}\n")
        return

    # â”€â”€ Processing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    proc      = audio.copy()
    stage_log = {}
    t0        = time.time()

    # Stage A â€” Noise floor
    if not a.no_noise:
        print(f"\n  Stage A  Noise floor          [{a.noise_db} dBFS]")
        # Derive a file-unique but reproducible seed from the input filename
        noise_seed = int(hashlib.md5(os.path.basename(a.input).encode()).hexdigest(), 16) % (2**32)
        proc = stage_noise_floor(proc, sr, a.noise_db, seed=noise_seed)
        stage_log['A_noise_db'] = a.noise_db
    else:
        print(f"\n  Stage A  Noise floor          [SKIPPED]")

    # Stage B â€” Stereo movement
    if not a.no_stereo and nch >= 2:
        print(f"  Stage B  Stereo movement      "
              f"[{a.stereo_rate} Hz LFO, depth {a.stereo_depth*100:.1f}%]")
        proc = stage_stereo_movement(proc, sr, a.stereo_rate, a.stereo_depth)
        stage_log['B_stereo_rate_hz'] = a.stereo_rate
        stage_log['B_stereo_depth']   = a.stereo_depth
    elif nch < 2:
        print(f"  Stage B  Stereo movement      [SKIPPED â€” mono input]")
    else:
        print(f"  Stage B  Stereo movement      [SKIPPED]")

    # Stage C â€” Harmonic saturation
    if not a.no_saturate:
        print(f"  Stage C  Harmonic saturation  [{a.drive_db} dB drive]")
        proc = stage_saturation(proc, a.drive_db)
        stage_log['C_drive_db'] = a.drive_db
    else:
        print(f"  Stage C  Harmonic saturation  [SKIPPED]")

    # Stage D â€” Grid quantization
    if not a.no_quantize:
        print(f"  Stage D  Grid quantization    "
              f"[{a.grid_div} subdivisions/beat"
              f"{', BPM=' + str(a.bpm) if a.bpm > 0 else ', BPM=auto'}]")
        proc, detected_bpm, n_shifted, max_shift_ms = stage_grid_quantize(
            proc, sr, a.grid_div,
            bpm_override=a.bpm if a.bpm > 0 else None)
        print(f"          BPM={detected_bpm:.1f}  |  "
              f"{n_shifted} onsets shifted  |  "
              f"max shift={max_shift_ms:.2f} ms")
        stage_log['D_bpm']           = round(detected_bpm, 2)
        stage_log['D_grid_div']      = a.grid_div
        stage_log['D_onsets_shifted'] = n_shifted
        stage_log['D_max_shift_ms']  = round(max_shift_ms, 3)
    else:
        print(f"  Stage D  Grid quantization    [SKIPPED]")

    print(f"\n  Processing time: {time.time()-t0:.1f}s")

    # â”€â”€ Clip guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    pk = np.max(np.abs(proc))
    if pk > 0.9999:
        proc /= pk * 1.0001
        print(f"  Clip guard applied  (peak was {pk:.5f})")

    # â”€â”€ Fingerprint after â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fp_a     = compute_fingerprint(np.mean(proc, axis=1), sr, fmax=fmax)
    improved = bool(fp_a['peak'] < fp_b['peak'])

    print_fingerprint_table(fp_b, fp_a, a.threshold)

    if improved:
        print(f"\n  âœ“  Quality gate passed  (peak raw reduced)")
    else:
        print(f"\n  âš   Quality gate: peak raw did not improve "
              f"({fp_b['peak']:.6f} â†’ {fp_a['peak']:.6f})")
        print(f"     Output written. Verify aurally and retest on LetsSubmit.")

    # â”€â”€ Save audio â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    sf.write(a.output, proc, sr, subtype=out_subtype)
    print(f"\n  Audio â†’ {os.path.basename(a.output)}  [{out_subtype}]")

    # â”€â”€ Plot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    plot_path = a.plot or a.output.replace('.wav', '_fingerprint.png')
    suffix    = (f"noise={a.noise_db}dB | stereo={a.stereo_depth*100:.0f}% | "
                 f"drive={a.drive_db}dB | grid={a.grid_div}")
    save_plot(fp_b, fp_a, a.threshold, suffix, plot_path)
    print(f"  Plot  â†’ {os.path.basename(plot_path)}")

    # â”€â”€ JSON report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    params    = dict(noise_db=a.noise_db, stereo_rate=a.stereo_rate,
                     stereo_depth=a.stereo_depth, drive_db=a.drive_db,
                     grid_div=a.grid_div, bpm_override=a.bpm,
                     no_noise=a.no_noise, no_stereo=a.no_stereo,
                     no_saturate=a.no_saturate, no_quantize=a.no_quantize)
    json_path = a.json or a.output.replace('.wav', '_report.json')
    save_json(fp_b, fp_a, params, dur, stage_log, json_path)
    print(f"  JSON  â†’ {os.path.basename(json_path)}")
    print(f"\n{SEP}\n")


if __name__ == '__main__':
    main()

