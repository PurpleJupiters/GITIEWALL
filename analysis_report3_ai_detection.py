"""Report 3: AI detection analysis — acoustic signatures compared across all files"""
import numpy as np, soundfile as sf, librosa, warnings
from scipy import signal
from scipy.signal import butter, sosfilt, find_peaks
from scipy.ndimage import median_filter
warnings.filterwarnings('ignore')

ORIG  = r"C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav"
MAST  = r"C:\Users\equat\Desktop\Latest Mastered Songs\Transfinite (Agent WALL) Master_master_v5.4.wav"
REF   = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"
VOCS  = r"C:\Users\equat\Desktop\Latest Mastered Songs\Transfinite_vocals.wav"
SR = 48000

def load_mono(p):
    d,sr=sf.read(p,always_2d=True,dtype='float32')
    L,R=d[:,0],d[:,1]
    if sr!=SR:
        L=librosa.resample(L.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
        R=librosa.resample(R.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
    return ((L+R)*0.5).astype(np.float32)

def ai_indicators(mono, label):
    """Compute all AI detection indicators for a mono signal."""
    n_fft=2048; hop=n_fft//4
    D = librosa.stft(mono.astype(np.float64), n_fft=n_fft, hop_length=hop)
    mag = np.abs(D)
    phase = np.angle(D)
    freqs = librosa.fft_frequencies(sr=SR, n_fft=n_fft)

    results = {}

    # 1. SPECTRAL FLATNESS — AI vocoders produce unnatural spectral envelopes.
    # AI vocals: too flat (noise-like) in noise zones, too tonal in harmonic zones.
    # Measure in the critical 1-8kHz range where vocoder artifacts appear.
    mask_crit = (freqs>=1000) & (freqs<=8000)
    geo = np.exp(np.mean(np.log(mag[mask_crit]+1e-9), axis=0))
    arith = np.mean(mag[mask_crit], axis=0) + 1e-9
    results['spectral_flatness_1_8k'] = float(np.mean(geo/arith))

    # 2. PHASE COHERENCE — Natural audio has pseudo-random phase relationships
    # between adjacent frames. AI neural vocoders produce unusually coherent phase.
    phase_diff = np.diff(phase, axis=1)
    phase_coherence = float(np.mean(np.abs(np.cos(phase_diff[mask_crit,:]))))
    results['phase_coherence'] = phase_coherence

    # 3. HARMONIC REGULARITY — AI harmonic content is too regular.
    # Measure: std dev of the amplitude of harmonics across time.
    # Natural instruments: high std (harmonics breathe). AI: low std (static).
    harmonic, _ = librosa.effects.hpss(mono.astype(np.float32))
    h_stft = np.abs(librosa.stft(harmonic.astype(np.float64), n_fft=n_fft, hop_length=hop))
    # Find harmonic bins (where energy is above background)
    h_mean = np.mean(h_stft, axis=1)
    h_bg = median_filter(h_mean, size=15)
    harm_bins = h_mean > h_bg * 1.5
    if harm_bins.sum() > 5:
        harm_amp_variance = float(np.mean(np.std(h_stft[harm_bins], axis=1)))
    else:
        harm_amp_variance = 0.0
    results['harmonic_amplitude_variance'] = harm_amp_variance

    # 4. PITCH MICRO-VARIATIONS — Natural vocals have micro-pitch variations (~±5-15 cents).
    # AI vocals: pitch too stable (unless vibrato added), or pitch artifacts.
    try:
        f0, voiced, _ = librosa.pyin(mono.astype(np.float64), fmin=80, fmax=800,
                                      sr=SR, hop_length=hop)
        voiced_f0 = f0[voiced & (f0>0)]
        if len(voiced_f0) > 20:
            pitch_std = float(np.std(1200*np.log2(voiced_f0/np.mean(voiced_f0)+1e-9)))
        else:
            pitch_std = 0.0
    except:
        pitch_std = 0.0
    results['pitch_micro_variation_cents'] = pitch_std

    # 5. ONSET SHARPNESS — AI voice synthesis produces unnaturally sharp onsets.
    # Measure: distribution of onset rise times.
    hop_o = int(SR*0.001)
    env = np.array([float(np.sqrt(np.mean(mono[i*hop_o:(i+1)*hop_o]**2)+1e-20))
                    for i in range(len(mono)//hop_o)])
    env_db = 20*np.log10(env+1e-9)
    rises_10ms = []
    for i in range(10, len(env_db)-1):
        r = env_db[i] - env_db[max(0,i-10)]
        if r > 15:
            rises_10ms.append(r)
    results['avg_onset_rise_10ms'] = float(np.mean(rises_10ms)) if rises_10ms else 0
    results['n_sharp_onsets_30db'] = sum(1 for r in rises_10ms if r > 30)

    # 6. SPECTRAL ENVELOPE SMOOTHNESS — AI vocoders produce smooth spectral envelopes.
    # Measure roughness: how much does adjacent spectral bins differ?
    mean_spec = np.mean(mag, axis=1)
    spectral_roughness = float(np.mean(np.abs(np.diff(mean_spec))))
    results['spectral_roughness'] = spectral_roughness

    # 7. TRANSIENT DENSITY — Natural audio has organic transient distribution.
    # AI: transients cluster suspiciously at regular (beat-aligned) intervals.
    onset_frames = librosa.onset.onset_detect(y=mono, sr=SR, hop_length=hop)
    if len(onset_frames) > 3:
        onset_intervals = np.diff(onset_frames)
        regularity = 1.0 - float(np.std(onset_intervals)/(np.mean(onset_intervals)+1e-9))
    else:
        regularity = 0.0
    results['onset_regularity'] = max(0.0, regularity)

    # 8. NEURAL VOCODER ARTIFACT SCORE — frequency regions known to show vocoder artifacts
    # 3-5kHz range: AI vocoders create characteristic resonances here.
    mask_voc = (freqs>=3000) & (freqs<=5000)
    bg_spectrum = median_filter(np.mean(mag, axis=1), size=31)
    artifact_score = float(np.mean(np.maximum(0,
        np.mean(mag[mask_voc], axis=1) - bg_spectrum[mask_voc])))
    results['vocoder_artifact_score'] = artifact_score

    return results

# ── AI SCORE COMPUTATION ─────────────────────────────────────────────────────
def compute_ai_score(r):
    """Combine indicators into a single AI likelihood score 0-100."""
    score = 0
    # Spectral flatness in critical zone (human: 0.05-0.20, AI: 0.25-0.60)
    sf = r['spectral_flatness_1_8k']
    score += min(25, max(0, (sf - 0.15) * 100))
    # Phase coherence (human: 0.55-0.70, AI: 0.70-0.90)
    pc = r['phase_coherence']
    score += min(20, max(0, (pc - 0.65) * 100))
    # Harmonic amplitude variance (human: high >0.010, AI: low <0.008)
    hav = r['harmonic_amplitude_variance']
    score += min(15, max(0, (0.012 - hav) * 2000))
    # Pitch micro-variation (human: 15-40 cents, AI: 0-10 cents)
    pmv = r['pitch_micro_variation_cents']
    score += min(20, max(0, (15 - pmv) * 2)) if pmv < 15 else 0
    # Sharp onsets (human: <5, AI: >15)
    score += min(10, r['n_sharp_onsets_30db'] * 0.5)
    # Vocoder artifacts
    va = r['vocoder_artifact_score']
    score += min(10, va * 50)
    return min(100, score)

print("="*80)
print("  REPORT 3: AI DETECTION ANALYSIS")
print("  Analyzing acoustic signatures used by AI detection algorithms")
print("="*80)

files = [
    ("Reference (Guy J)",    REF,  "human_full"),
    ("Original song (input)",ORIG, "ai_full"),
    ("Master v5.4 (full)",   MAST, "ai_full"),
    ("Vocals only track",    VOCS, "ai_vocal"),
]

all_results = {}
for label, path, kind in files:
    print(f"\n  Loading: {label}...")
    mono = load_mono(path)
    # For full mixes, use only 120s from middle to speed up analysis
    if kind in ("human_full","ai_full"):
        mid = len(mono)//2
        mono = mono[max(0,mid-SR*60):mid+SR*60]
    r = ai_indicators(mono, label)
    r['ai_score'] = compute_ai_score(r)
    all_results[label] = r

print(f"\n  AI DETECTION INDICATORS — COMPARISON TABLE")
print(f"  {'Indicator':<38} {'Ref(Human)':>12}  {'Original':>12}  {'Master':>12}  {'Vocals':>12}")
print(f"  {'-'*80}")

labels_short = ["Reference (Guy J)", "Original song (input)", "Master v5.4 (full)", "Vocals only track"]
metrics = [
    ("Spectral flatness 1-8kHz",          'spectral_flatness_1_8k',      ".3f", "lower=more human"),
    ("Phase coherence",                    'phase_coherence',              ".3f", "lower=more human"),
    ("Harmonic amplitude variance",        'harmonic_amplitude_variance',  ".4f", "higher=more human"),
    ("Pitch micro-variation (cents)",      'pitch_micro_variation_cents',  ".1f", "higher=more human"),
    ("Avg onset rise dB/10ms",             'avg_onset_rise_10ms',          ".1f", "lower=more human"),
    ("Sharp onsets count (>30dB/10ms)",    'n_sharp_onsets_30db',          "d",   "lower=more human"),
    ("Spectral roughness",                 'spectral_roughness',           ".4f", "moderate=human"),
    ("Onset regularity (0=random,1=grid)", 'onset_regularity',             ".3f", "lower=more human"),
    ("Vocoder artifact score",             'vocoder_artifact_score',       ".4f", "lower=more human"),
]

for display, key, fmt, note in metrics:
    vals = [all_results[l][key] for l in labels_short]
    row_str = f"  {display:<38}"
    for v in vals:
        row_str += f" {v:>12{fmt}}"
    print(f"{row_str}  ({note})")

print(f"\n  AI LIKELIHOOD SCORES (0=fully human, 100=clearly AI-generated)")
print(f"  {'File':<40} {'AI Score':>10}  {'Verdict'}")
print(f"  {'-'*65}")
for label in labels_short:
    sc = all_results[label]['ai_score']
    if sc < 20:   verdict = "Human / Natural"
    elif sc < 40: verdict = "Possibly AI / Lightly processed"
    elif sc < 60: verdict = "Likely AI generated"
    elif sc < 80: verdict = "Strongly AI — artifacts present"
    else:         verdict = "Clearly AI — heavy artifact signatures"
    sym = "  [OK]" if sc<30 else (" [!!] " if sc<55 else " [!!!]")
    print(f"  {label:<40} {sc:>10.1f}  {verdict} {sym}")

print(f"\n  WHAT AI DETECTORS LOOK FOR:")
print(f"  Spectral flatness  : AI vocoders produce unnaturally flat spectra in 1-8kHz")
print(f"  Phase coherence    : AI lacks natural phase randomisation between frames")
print(f"  Harmonic variance  : Natural instruments 'breathe'; AI harmonics are static")
print(f"  Pitch micro-var    : Natural voices vary ±15-40 cents; AI is too stable")
print(f"  Sharp onsets       : AI vocal synthesis starts/stops unnaturally abruptly")
print(f"  Vocoder artifacts  : 3-5kHz resonance peaks from neural vocoder synthesis")
print("="*80)
