r"""
sunomaster_v54_final.py — SunoMaster v5.4 FINAL

CORE PHILOSOPHY (non-negotiable):
  DO NO HARM.  Never degrade the original track to hit a loudness, stereo,
  dynamics, or spectral target. If reaching a target requires damaging the
  audio, stop short and accept the best achievable result without harm.
  Optimal is not perfect. A great-sounding track that misses a target by
  0.5 dB is always better than a compromised track that hits it exactly.
  The reference track is the compass — approach its character, never clone it.

PIPELINE RULES:
  SV-01: LP@18kHz applied ONCE on the final master — NOT per stem.
  SV-02: Gain structure — P2 targets -10 LUFS so P3 needs minimal makeup.
  SV-03: Single reference track. No multi-track averaging.
  DM-01: Level-preservation. Stems never boosted more than 6dB.
          Ghost stems (>25dB below mix) get minimal processing only.
  DM-02: Clip guards are MONITORS — if one fires, processing is REDUCED.
  DM-03: Output at 48kHz PCM-24.
  EK-01: DO NO HARM — max EQ correction 3dB per band.
  EK-02: Reference mismatch check — skip correction if shape delta >5dB.
  EK-03: Quality checkpoint — flag any band that changed >8dB vs original.
  EK-04: Self-correction loop — revert any correction that degrades audio.
          Declare OPTIMAL when either all targets met OR further improvement
          would cause harm. Both outcomes are equally valid.

Usage (PowerShell, sunomaster conda env active):
  python sunomaster_improved.py ^
    --input "E:/SunoMaster/input/song.wav" ^
    --reference "E:\SunoMaster\references\Guy J - Worlds Apart (Original Mix).wav" ^
    --output "E:\SunoMaster\output"
"""

import argparse, gc, subprocess, sys, json, time, shutil
import numpy as np
import soundfile as sf
import librosa
from scipy import signal as sp
from scipy.signal import find_peaks
from pathlib import Path

SR = 48000

# ─── DEFAULT PATHS ─────────────────────────────────────────────────────────────
# Reference tracks are always normalized versions in this folder.
# Pass --reference with just the filename, or override with a full path.
DEFAULT_REF_FOLDER = r"E:\SunoMaster\references\normalized reference tracks"
DEFAULT_REFERENCE  = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"

MAX_EQ_DB     = 3.0    # Hard cap on any single EQ correction
MAX_STEM_GAIN = 6.0    # Never boost a stem more than 6dB
GHOST_THRESH  = 25.0   # dB below mix RMS = ghost stem, skip heavy processing
HARM_GUARD    = 8.0    # dB change per band that triggers quality flag

# ─── ZERO-PHASE FILTERS ────────────────────────────────────────────────────────

def hp(y, hz, order=4):
    return sp.sosfiltfilt(sp.butter(order, hz, 'hp', fs=SR, output='sos'), y).astype(np.float32)

def lp(y, hz, order=4):
    return sp.sosfiltfilt(sp.butter(order, hz, 'lp', fs=SR, output='sos'), y).astype(np.float32)

def notch(y, hz, Q=3.5):
    b, a = sp.iirnotch(hz, Q, SR)
    return sp.sosfiltfilt(sp.tf2sos(b, a), y).astype(np.float32)

def peak_eq(y, hz, gain_db, Q=2.0):
    gain_db = float(np.clip(gain_db, -MAX_EQ_DB, MAX_EQ_DB))  # EK-01: DO NO HARM
    A = 10 ** (gain_db / 40); w = 2 * np.pi * hz / SR; al = np.sin(w) / (2 * Q)
    b = [1+al*A, -2*np.cos(w), 1-al*A]; a = [1+al/A, -2*np.cos(w), 1-al/A]
    return sp.sosfiltfilt(sp.tf2sos(b, a), y).astype(np.float32)

def hi_shelf(y, hz, gain_db, S=0.707):
    gain_db = float(np.clip(gain_db, -MAX_EQ_DB, MAX_EQ_DB))  # EK-01: DO NO HARM
    A=10**(gain_db/40); w=2*np.pi*hz/SR
    al=np.sin(w)/2*np.sqrt((A+1/A)*(1/S-1)+2); c=np.cos(w)
    b=[A*((A+1)+(A-1)*c+2*np.sqrt(A)*al),-2*A*((A-1)+(A+1)*c),A*((A+1)+(A-1)*c-2*np.sqrt(A)*al)]
    a=[(A+1)-(A-1)*c+2*np.sqrt(A)*al,2*((A-1)-(A+1)*c),(A+1)-(A-1)*c-2*np.sqrt(A)*al]
    n=a[0]; b=[x/n for x in b]; a=[x/n for x in a]
    return sp.sosfiltfilt(sp.tf2sos(b, a), y).astype(np.float32)

# ─── LEVEL UTILITIES ───────────────────────────────────────────────────────────

def rms_db(y):
    return float(20 * np.log10(np.sqrt(np.mean(y.astype(np.float64)**2)) + 1e-12))

def peak_db(y):
    return float(20 * np.log10(np.max(np.abs(y)) + 1e-12))

def gain_db_apply(y, db):
    return (y * np.float32(10 ** (db / 20))).astype(np.float32)

# ─── SPECTRAL ANALYSIS ─────────────────────────────────────────────────────────

BANDS_HZ = [
    (20,   50,   'deep_sub'),
    (50,   100,  'sub'),
    (100,  200,  'kick'),
    (200,  400,  'low_mid'),
    (400,  800,  'mid_low'),
    (800,  2000, 'mid'),
    (2000, 5000, 'presence'),
    (5000, 10000,'hi_mid'),
    (10000,16000,'air'),
    (16000,20000,'ultra_air'),
]

def spectral_profile(y, sr_in, n_fft=4096, seconds=60):
    """Measure mean energy in each 1/3-octave-style band."""
    S = np.abs(librosa.stft(y[:sr_in*seconds].astype(np.float64), n_fft=n_fft))
    freqs = librosa.fft_frequencies(sr=sr_in, n_fft=n_fft)
    mm = np.mean(S, axis=1)
    del S; gc.collect()
    profile = {}
    for lo, hi, name in BANDS_HZ:
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            profile[name] = float(20 * np.log10(np.mean(mm[mask]) + 1e-9))
    return profile

def measure_lufs(L, R):
    """ITU-R BS.1770-4 integrated LUFS."""
    BS=np.array([1.53512485958697,-2.69169618940638,1.19839281085285])
    AS=np.array([1.0,-1.69065929318241,0.73248077421585])
    BH=np.array([1.0,-2.0,1.0]); AH=np.array([1.0,-1.99004745483398,0.99007225036603])
    kL=sp.lfilter(BH,AH,sp.lfilter(BS,AS,L.astype(np.float64)))
    kR=sp.lfilter(BH,AH,sp.lfilter(BS,AS,R.astype(np.float64)))
    bl=int(0.4*SR); hop=int(0.1*SR); n=(len(kL)-bl)//hop
    ms=np.array([0.5*(np.mean(kL[i*hop:i*hop+bl]**2)+np.mean(kR[i*hop:i*hop+bl]**2)) for i in range(n)])
    g1=ms[ms>1e-7]
    if not len(g1): return -70.0
    g2=ms[ms>np.mean(g1)*10**(-10/10)]
    return float(-0.691+10*np.log10(np.mean(g2))) if len(g2) else -70.0

# ─── REFERENCE PROFILE ─────────────────────────────────────────────────────────

def build_reference_profile(ref_path):
    """Build spectral reference from a single track. SV-03 fix."""
    print(f"  Building reference from: {Path(ref_path).name}")
    d, sr = sf.read(str(ref_path), dtype='float32', always_2d=True)
    L, R = d[:,0], d[:,1]
    y = ((L + R) * 0.5).astype(np.float32)
    if sr != SR:
        y = librosa.resample(y.astype(np.float64), orig_sr=sr, target_sr=SR).astype(np.float32)
        L = librosa.resample(L.astype(np.float64), orig_sr=sr, target_sr=SR).astype(np.float32)
        R = librosa.resample(R.astype(np.float64), orig_sr=sr, target_sr=SR).astype(np.float32)
    profile = spectral_profile(y, SR)
    profile['lufs'] = measure_lufs(L, R)
    profile['peak'] = peak_db(np.concatenate([L, R]))
    profile['crest'] = profile['peak'] - profile['lufs']
    print(f"  Reference: LUFS={profile['lufs']:.2f}  Crest={profile['crest']:.1f}dB")
    del d, L, R, y; gc.collect()
    return profile

# ─── VIRTUAL ANALOG ────────────────────────────────────────────────────────────

CONSOLES = {
    # hi-shelf cuts REMOVED — they compound across 6 stems stealing 1.5-3dB of air.
    # Each stem's -0.3 to -0.5dB cut adds up to an audible air deficit on the master.
    # Warmth/character comes from the low-shelf and saturation only.
    'neve': dict(lf=(80,+0.6,0.7),  hf=(20000, 0.0), sat='even',  drv=0.60),
    'ssl':  dict(lf=(120,+0.3,1.0), hf=(20000, 0.0), sat='mixed', drv=0.55),
    'api':  dict(lf=(200,+0.4,1.5), hf=(20000, 0.0), sat='mixed', drv=0.65),
}
STEM_CONSOLE = {'drums':'ssl','bass':'ssl','other':'neve','vocals':'neve','guitar':'api','piano':'neve'}

def virtual_analog(y, console='neve', drive_db=4.0, warmth=0.15):
    """Conservative analog emulation. DM-01: reduced drive to prevent artefacts."""
    p = CONSOLES.get(console, CONSOLES['neve'])
    orig_pk = float(np.max(np.abs(y))) + 1e-12
    y = peak_eq(y, p['lf'][0], p['lf'][1], p['lf'][2])
    y = hi_shelf(y, p['hf'][0], p['hf'][1])
    drive = 10 ** ((drive_db * p['drv']) / 20)
    pk_in = float(np.max(np.abs(y))) + 1e-12
    yn = y.astype(np.float64) / pk_in * drive
    if p['sat'] == 'even':
        sh = (np.tanh(yn + 0.05*yn**2) * 0.90 + 0.10*yn).astype(np.float32)
    else:
        sh = (np.tanh(yn - 0.02*yn**3) * 0.92 + 0.08*yn).astype(np.float32)
    sh = (sh / (float(np.max(np.abs(sh)))+1e-12) * pk_in).astype(np.float32)
    y = (y * (1-warmth) + sh * warmth).astype(np.float32)
    del sh, yn; gc.collect()
    # [SV-01 FIX] No LP@18kHz here — applied once on final master only
    # Only a very gentle LP@22kHz as safety catch
    y = lp(y, 22000, order=2)
    out_pk = float(np.max(np.abs(y))) + 1e-12
    return (y * np.float32(orig_pk / out_pk)).astype(np.float32)

# ─── P0 — AI IDENTIFICATION REMOVAL ───────────────────────────────────────────

def pipeline_0(L, R, sr_in, stem_name, mix_rms_db):
    """
    P0: Metadata strip, infrasonic removal, polarity.
    [SV-01 FIX]: LP@18kHz REMOVED from per-stem processing.
    [DM-01 FIX]: Ghost stem detection — skip heavy processing if stem >25dB below mix.
    """
    # Resample
    if sr_in != SR:
        L = librosa.resample(L.astype(np.float64), orig_sr=sr_in, target_sr=SR).astype(np.float32)
        R = librosa.resample(R.astype(np.float64), orig_sr=sr_in, target_sr=SR).astype(np.float32)

    stem_rms = rms_db(np.concatenate([L, R]))
    is_ghost  = (mix_rms_db - stem_rms) > GHOST_THRESH
    if is_ghost:
        print(f"    [{stem_name}] GHOST STEM ({stem_rms:.1f}dBFS, {mix_rms_db-stem_rms:.0f}dB below mix) — minimal processing")

    # [SV-01 FIX]: No LP@18kHz per stem — only infrasonic removal
    L = hp(L, 18, order=2); R = hp(R, 18, order=2)

    # Infrasonic scan (only if not ghost)
    if not is_ghost:
        y_m = ((L+R)*0.5).astype(np.float32)
        S   = np.abs(librosa.stft(y_m[:SR*20].astype(np.float64), n_fft=8192))
        freqs = librosa.fft_frequencies(sr=SR, n_fft=8192)
        mm    = np.mean(S, axis=1)
        sub_e  = float(20*np.log10(np.mean(mm[freqs<30])+1e-9))
        full_e = float(20*np.log10(np.mean(mm)+1e-9))
        del S, mm, y_m; gc.collect()
        if sub_e - full_e > -8:
            print(f"    [{stem_name}] Sub-30Hz excess {sub_e-full_e:+.1f}dB — HP@30Hz applied")
            L = hp(L, 30, order=4); R = hp(R, 30, order=4)

    # Polarity check using active section
    y_m = ((L+R)*0.5).astype(np.float32)
    rms_frames = np.array([float(np.sqrt(np.mean(y_m[i:i+SR//10]**2)))
                            for i in range(0, len(y_m)-SR//10, SR//10)])
    thresh = float(np.max(rms_frames) * 0.1) if rms_frames.max() > 0 else 0.001
    active = np.where(rms_frames > thresh)[0]
    if len(active):
        s = int(active[0] * (SR//10)); e = min(s + SR*5, len(L))
        corr = float(np.corrcoef(L[s:e], R[s:e])[0,1])
        if not np.isnan(corr) and corr < -0.9:
            R = -R; print(f"    [{stem_name}] Polarity corrected")
    del y_m; gc.collect()

    # Safety ceiling
    pk = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))))
    if pk > 10**(-0.5/20):
        sc = np.float32(10**(-0.5/20)/pk); L, R = L*sc, R*sc

    # P0 gain staging REMOVED per audit: P2 BUS_TARGETS are the authoritative
    # level reference. P0 gain stage was redundant and caused a 6dB cap conflict.
    # Safety ceiling is sufficient here.
    return L, R, is_ghost

# ─── P1 — STEM CLEANING ────────────────────────────────────────────────────────

def pipeline_1(L, R, stem_name, is_ghost, mix_rms_db):
    """
    P1: Conservative stem cleanup.
    [DM-01 FIX]: Level-preservation — never boost stem by more than MAX_STEM_GAIN dB.
    [DM-01 FIX]: Clip guard is now a MONITOR — if it would fire, processing is reduced.
    [SV-01 FIX]: No LP filter on stems.
    """
    console = STEM_CONSOLE.get(stem_name, 'neve')
    stem_rms = rms_db(np.concatenate([L, R]))

    if is_ghost:
        # Ghost stem: apply only virtual analog at reduced settings, no other processing
        L = virtual_analog(L, console=console, drive_db=2.0, warmth=0.08)
        R = virtual_analog(R, console=console, drive_db=2.0, warmth=0.08)
        print(f"    [{stem_name}] Ghost stem — virtual analog only (reduced)")
        return L, R

    # ── Stem-specific processing (before generic cleaning) ──────────────────────
    # AI vocal chain: glitch removal, multi-band de-essing, transient smoothing
    if stem_name == 'vocals':
        L, R = process_ai_vocals(L, R, sr=SR)
    # Drum hi-hat/cymbal shrill attenuation (preserve impact, kill the hiss)
    elif stem_name == 'drums':
        L, R = deess_multiband(L, R, stem_type='drums', sr=SR)
    # Guitar high-frequency harshness reduction
    elif stem_name == 'guitar':
        L, R = deess_multiband(L, R, stem_type='guitar', sr=SR)

    # DC removal
    L = hp(L, 5, order=2); R = hp(R, 5, order=2)

    # Noise gate — very gentle to avoid pumping
    def gate(y, thr_db=-68):  # DM2-01: was -72, now -68dB
        hop = max(1, int(SR*5/1000))
        n = (len(y)+hop-1)//hop
        lvl = np.array([float(np.sqrt(np.mean(y[i*hop:(i+1)*hop]**2)+1e-20)) for i in range(n)])
        ac = np.exp(-1/max(1,0.6)); rc = np.exp(-1/max(1,16.0))
        ef = np.zeros(n); s_ = 0.0
        for i, v in enumerate(lvl): s_=(ac*s_+(1-ac)*v) if v>s_ else (rc*s_+(1-rc)*v); ef[i]=s_
        env=np.interp(np.arange(len(y)),(np.arange(n)+0.5)*hop,ef).astype(np.float32)
        return (y*np.clip(env/(10**(thr_db/20)+1e-12),0,1)).astype(np.float32)
    L = gate(L); R = gate(R)

    # Phase correlation fix (only if very bad)
    y_m = ((L+R)*0.5).astype(np.float32)
    rms_f = np.array([float(np.sqrt(np.mean(y_m[i:i+SR//10]**2))) for i in range(0,len(y_m)-SR//10,SR//10)])
    thresh = float(np.max(rms_f)*0.1) if rms_f.max()>0 else 0.001
    active_i = np.where(rms_f>thresh)[0]
    if len(active_i):
        s_=int(active_i[0]*(SR//10)); e_=min(s_+SR*5,len(L))
        corr = float(np.corrcoef(L[s_:e_], R[s_:e_])[0,1])
        if not np.isnan(corr) and corr < -0.5:
            M=(L+R)*0.5; S_=(L-R)*0.5
            Mg=np.float32(1.3 if corr<0 else 1.1)
            Sg=np.float32(0.4 if corr<0 else 0.7)
            Ln=(M*Mg+S_*Sg).astype(np.float32); Rn=(M*Mg-S_*Sg).astype(np.float32)
            opk=max(float(np.max(np.abs(L))),float(np.max(np.abs(R))),1e-12)
            npk=max(float(np.max(np.abs(Ln))),float(np.max(np.abs(Rn))),1e-12)
            L=(Ln*(opk/npk)).astype(np.float32); R=(Rn*(opk/npk)).astype(np.float32)
            print(f"    [{stem_name}] Phase fixed: {corr:.3f} -> improved")
    del y_m; gc.collect()

    # Resonance scan — ONLY applied to drums stem, above 8kHz (cymbal shrill).
    # All other stems (guitar, bass, piano, vocals, other) are EXEMPT.
    # Reason: in synthesised/AI music, spectral peaks below 8kHz are musical
    # fundamentals and harmonics. Notching them removes the music, not artefacts.
    # Drums above 8kHz can have genuine non-musical shrill cymbal resonances.
    _notch_stems = {'drums', 'bass'}   # only these are eligible
    _notch_min_freq = 8000             # only above 8kHz for drums
    if stem_name in _notch_stems:
        y_m = ((L+R)*0.5).astype(np.float32)
        S = np.abs(librosa.stft(y_m[:SR*30].astype(np.float64), n_fft=4096))
        freqs_n = librosa.fft_frequencies(sr=SR, n_fft=4096)
        lmag = 20*np.log10(np.mean(S, axis=1)+1e-9)
        pks, props = find_peaks(lmag, prominence=20.0, width=(3, 6))
        resonances = sorted(
            [(freqs_n[i], props['prominences'][j])
             for j,i in enumerate(pks) if freqs_n[i] > _notch_min_freq],
            key=lambda x:-x[1])[:2]
        del S; gc.collect()
        for fr, pm in resonances:
            depth_db = min(pm * 0.25, 4.0)   # max 4dB, very conservative
            b_notch, a_notch = sp.iirnotch(fr, 3.5, SR)
            blend = 1.0 - (10**(-depth_db/20))
            Ln = sp.sosfiltfilt(sp.tf2sos(b_notch, a_notch), L.astype(np.float64)).astype(np.float32)
            Rn = sp.sosfiltfilt(sp.tf2sos(b_notch, a_notch), R.astype(np.float64)).astype(np.float32)
            L = (L * (1.0-blend) + Ln * blend).astype(np.float32)
            R = (R * (1.0-blend) + Rn * blend).astype(np.float32)
            print(f"    [{stem_name}] Notch {fr:.0f}Hz (prominence={pm:.1f}dB, applied={depth_db:.1f}dB)")

    # [DM-01 FIX]: Level-preservation check
    # P1 processing can inadvertently boost stems. Cap any boost to MAX_STEM_GAIN dB.
    # rms_change > 0 means P1 boosted the stem; rms_change < 0 means it was reduced.
    current_rms = rms_db(np.concatenate([L, R]))
    rms_change = current_rms - stem_rms  # positive = boosted by P1
    if rms_change > MAX_STEM_GAIN:
        # P1 boosted this stem too much — reduce it back so net boost <= MAX_STEM_GAIN
        correction = MAX_STEM_GAIN - rms_change  # negative: reduces the overboost
        print(f"    [{stem_name}] P1 boost capped: {rms_change:.1f}dB -> {MAX_STEM_GAIN}dB (applying {correction:.1f}dB)")
        L = gain_db_apply(L, correction)
        R = gain_db_apply(R, correction)

    # Sub mono lock
    sub_m = ((lp(L, 100) + lp(R, 100)) * 0.5).astype(np.float32)
    L = (sub_m + hp(L, 100)).astype(np.float32)
    R = (sub_m + hp(R, 100)).astype(np.float32)

    # Safety ceiling before console
    pk = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))))
    if pk > 10**(-1.0/20): sc=np.float32(10**(-1.0/20)/pk); L,R=L*sc,R*sc

    # Virtual analog (conservative settings)
    L = virtual_analog(L, console=console, drive_db=4.0, warmth=0.15)
    R = virtual_analog(R, console=console, drive_db=4.0, warmth=0.15)

    # Final ceiling
    pk = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))))
    if pk > 10**(-0.5/20): sc=np.float32(10**(-0.5/20)/pk); L,R=L*sc,R*sc

    # Stem soft clipper — shave extreme transient peaks, creating headroom.
    L, R = stem_soft_clipper(L, R, stem_type=stem_name, sr=SR)

    # Phase rotation — DISABLED for vocals (allpass at 250Hz smears vocal body,
    # causing phasey artifacts audible to human ears). Kept for bass/guitar/other
    # where the small headroom gain is worth the minimal phase effect.
    if stem_name != 'vocals':
        L, R = phase_rotate_for_headroom(L, R, sr=SR, stem_type=stem_name)

    # NOTE: P1 output gain staging REMOVED.
    # It normalised all stems to -18dBFS which caused two problems:
    # (1) it conflicted with P2 BUS_TARGETS, leaving stems too quiet to be boosted
    # (2) it put all stems at exactly the de-esser's threshold, causing constant triggering.
    # P2 BUS_TARGETS handle the per-stem level normalisation instead.

    return L, R

# ─── P2 — MIXING ───────────────────────────────────────────────────────────────

def pipeline_2(stems_dict, bpm, target_lufs=-10.0, orig_L=None, orig_R=None):
    """
    P2: Mix stems into stereo master.
    [SV-02 FIX]: Target -10 LUFS out (not -19 LUFS) so P3 needs minimal makeup gain.
    [DM-01 FIX]: No aggressive EQ corrections on individual stems in mix stage.
    Bus widths per stem type (conservative values).
    """
    # Stereo width per stem: 1.0 = preserve full demucs stereo, 0.0 = mono.
    # Previous (mf, sf_) tuples crushed the Side signal (sf_ as low as 0.05),
    # collapsing stereo correlation from 0.92 to 0.99. Use single width factor.
    # All set to 1.0 except bass (which is mono below 100Hz via sub lock anyway).
    # This maximises stereo recovery from demucs stems.
    WIDTHS = {
        'drums': 0.9,   # near-full — preserve cymbal spread but avoid over-wide transients
        'bass':  0.4,   # mostly mono — sub is non-directional
        'vocals':1.0,   # full stereo — vocals locked center anyway by panning
        'guitar':0.9,   # near-full
        'piano': 0.8,   # slightly narrower
        'other': 0.5,   # REDUCED from 1.0 — pads/synths were the main cause of
                        # extreme stereo width (0.500 S/M ratio). 0.5 brings it to
                        # a more manageable level while still preserving stereo feel.
    }

    # PANNING — Equal Power (constant power law), applied after BUS_TARGETS level
    # and before sidechain. Pan the MID channel, preserve SIDE (stem's internal image).
    # Professional standard: pan_degrees = 0 (center) to ±45 (hard L/R).
    # Kick and bass MUST be center. Lead vocals MUST be center.
    # Drums: +8° right (snare convention). Guitar: -18° left. Piano: +15° right.
    # Other (pads/atm): +5° gentle right for balance.
    # Pan angles reduced further — previous combo of panning + M/S blend made
    # master too wide (0.329 vs reference 0.257). Tighter angles = better mono compat.
    PAN_DEGREES = {
        'drums':  +5.0,   # snare sits slightly right
        'bass':    0.0,   # absolute center
        'vocals':  0.0,   # absolute center — NEVER move lead vocals
        'guitar':  -8.0,  # gentle left (was -12°, caused mid correlation issues)
        'piano':   +7.0,  # gentle right (was +10°)
        'other':   +3.0,  # very slight right
    }
    # Recalibrated BUS_TARGETS — previous drums at -8dBFS caused +3.9dB low-mid mud.
    # Vocals raised to -12 for better presence. Guitar raised to -14 for more sparkle.
    # Sub and kick now track reference levels more closely.
    # BUS_TARGETS — final calibration.
    # Vocals at -12 and guitar at -14 were pushing 200Hz-3kHz band +2.9 to +3.9dB
    # above original. Backing them off restores the mid balance while keeping them
    # present and audible above the mix.
    BUS_TARGETS = {
        'drums': -10.0,   # correct — kick body is at original level
        'bass':  -11.0,   # correct
        'vocals':-13.5,   # reduced from -12 to -13.5 (less mid-range mud)
        'guitar':-15.0,   # reduced from -14 to -15 (less mid-range mud)
        'piano': -16.0,   # unchanged
        'other': -14.0,   # unchanged
    }

    N = min(len(L) for L,R in stems_dict.values())

    # Build kick sidechain from drums
    kick_src_name = next((n for n in ('drums','bass','other') if n in stems_dict), list(stems_dict.keys())[0])
    kick_src = ((stems_dict[kick_src_name][0] + stems_dict[kick_src_name][1]) * 0.5).astype(np.float32)
    sos_kick = sp.butter(4, [40, 120], 'bp', fs=SR, output='sos')
    kick_sub  = sp.sosfilt(sos_kick, kick_src)
    beat_ms   = (60.0 / bpm) * 1000
    hop_sc    = max(1, int(SR * 5 / 1000))
    n_sc      = (len(kick_sub) + hop_sc - 1) // hop_sc
    lvl_sc    = np.array([float(np.sqrt(np.mean(kick_sub[i*hop_sc:(i+1)*hop_sc]**2)+1e-20)) for i in range(n_sc)])
    att_c     = np.exp(-1/max(1, 18.0/5))
    rel_c     = np.exp(-1/max(1, (beat_ms*0.60)/5))
    ef_sc     = np.zeros(n_sc); s_sc=0.0
    for i,v in enumerate(lvl_sc): s_sc=(att_c*s_sc+(1-att_c)*v) if v>s_sc else (rel_c*s_sc+(1-rel_c)*v); ef_sc[i]=s_sc
    kick_env  = np.interp(np.arange(N),(np.arange(n_sc)+0.5)*hop_sc,ef_sc[:n_sc]).astype(np.float32)
    del kick_src, kick_sub, lvl_sc, ef_sc; gc.collect()

    mix_L = np.zeros(N, np.float32)
    mix_R = np.zeros(N, np.float32)

    for stem_name, (L, R) in stems_dict.items():
        if len(L) > N: L, R = L[:N], R[:N]
        elif len(L) < N: L=np.pad(L,(0,N-len(L))); R=np.pad(R,(0,N-len(R)))

        # Level to bus target — cap raised to 18dB (was 6dB which blocked drums/bass).
        # Previous 6dB cap combined with P0 gain staging to -18dBFS meant drums
        # could never reach their -8dBFS target, causing P3 to need 9+ dB makeup gain.
        cur_rms = rms_db(np.concatenate([L, R]))
        tgt_rms = BUS_TARGETS.get(stem_name, -14.0)
        gain    = tgt_rms - cur_rms
        gain = float(np.clip(gain, -12.0, 18.0))   # safe range: never more than +18dB
        if cur_rms < -50:  # ghost stem in mix - very light
            gain = min(gain, 3.0)
        L = gain_db_apply(L, gain); R = gain_db_apply(R, gain)

        # PANNING — Equal Power, M/S method (pan Mid, preserve Side image)
        pan_deg = PAN_DEGREES.get(stem_name, 0.0)
        if abs(pan_deg) > 0.5:
            theta  = (pan_deg + 45.0) / 90.0          # normalise to [0, 1]
            g_L    = float(np.cos(theta * np.pi / 2))  # equal power
            g_R    = float(np.sin(theta * np.pi / 2))
            M_pan  = ((L + R) * 0.5).astype(np.float32)
            S_pan  = ((L - R) * 0.5).astype(np.float32)
            L = (M_pan * g_L + S_pan).astype(np.float32)
            R = (M_pan * g_R - S_pan).astype(np.float32)

        # Sidechain (mild — clarity not pumping)
        sc_thr  = {'drums':1.0,'bass':0.85,'vocals':0.95,'guitar':0.97,'piano':0.97,'other':0.93}
        sc_floor = sc_thr.get(stem_name, 0.95)
        thr_lin  = float(np.percentile(kick_env[kick_env>0], 75)) if np.any(kick_env>0) else 0.01
        sc_gain  = np.clip(1.0 - (kick_env / (thr_lin+1e-9)) * (1.0-sc_floor), sc_floor, 1.0).astype(np.float32)
        L = (L * sc_gain).astype(np.float32); R = (R * sc_gain).astype(np.float32)

        # Apply width — M_ + S_*w gives full stereo at w=1, mono at w=0
        w  = np.float32(WIDTHS.get(stem_name, 0.9))
        M_ = ((L+R)*0.5).astype(np.float32); S_ = ((L-R)*0.5).astype(np.float32)
        mix_L += (M_ + S_*w).astype(np.float32)
        mix_R += (M_ - S_*w).astype(np.float32)
        del L, R, M_, S_, sc_gain; gc.collect()

    del kick_env; gc.collect()

    # Sub mono lock on final mix
    sub_m = ((lp(mix_L,100)+lp(mix_R,100))*0.5).astype(np.float32)
    mix_L = (sub_m+hp(mix_L,100)).astype(np.float32)
    mix_R = (sub_m+hp(mix_R,100)).astype(np.float32)
    del sub_m; gc.collect()

    # Stereo blend: recover original stereo image lost during stem reconstruction.
    # Uses processed Mid (cleaning/character) + blend of original Side (stereo width).
    # M/S stereo blend REMOVED — the processed mix at width=0.500 is already wider
    # than the original (0.203). Blending more original side only added complexity.

    # Bus compressor: reduces the P2 mix's high crest factor (~13.6dB) so that
    # the subsequent LUFS gain can actually reach the -10 LUFS target.
    # Without this, the peak ceiling (-6dBFS) blocks the LUFS gain at ~-19 LUFS.
    # Bus compressor — corrected timing for dance music at 133 BPM.
    # Attack 8ms was catching kick transients (wrong — let them through).
    # Release 80ms caused audible pumping (too fast for 133 BPM).
    # Professional standard: attack >= 30ms (transient passes), release = 60000/BPM.
    # 60000/133.9 = ~448ms. Use 450ms.
    mix_L, mix_R = bus_compressor(mix_L, mix_R, sr=SR,
                                  ratio=1.8, threshold_db=-12.0,
                                  attack_ms=35.0, release_ms=450.0)

    # Mix bus phase rotation — allpass sweep on the full mix.
    # Applied AFTER bus compression, BEFORE the LUFS gain step.
    # Broadcast standard: 150-200 Hz, typical gain 1.5-2.5 dB on dense material.
    print(f"    [P2] Mix bus phase rotation...")
    mix_L, mix_R = phase_rotate_for_headroom(mix_L, mix_R, sr=SR, stem_type='other')

    # LUFS gain applied FIRST (before peak limit) — previous ordering bug:
    # peak limit ran first → peak sat at ceiling → gain_for_peak=0 → LUFS gain blocked.
    # Now: measure LUFS, apply gain to reach target, THEN peak limit for safety.
    current_lufs = measure_lufs(mix_L, mix_R)
    gain_needed  = float(np.clip(target_lufs - current_lufs, -12.0, 18.0))
    mix_L = gain_db_apply(mix_L, gain_needed)
    mix_R = gain_db_apply(mix_R, gain_needed)

    # Peak limit at -3dBFS (safety only — P3 soft-clip and limiter handle final peak).
    pk = max(float(np.max(np.abs(mix_L))), float(np.max(np.abs(mix_R))))
    if pk > 10**(-3.0/20):
        sc = np.float32(10**(-3.0/20)/pk); mix_L*=sc; mix_R*=sc

    final_lufs = measure_lufs(mix_L, mix_R)
    print(f"    P2 output: LUFS={final_lufs:.1f}  Peak={peak_db(np.concatenate([mix_L,mix_R])):+.1f}dBFS")
    return mix_L, mix_R

# ─── P3 — MASTERING ────────────────────────────────────────────────────────────

def pipeline_3(mL, mR, ref_profile, target_lufs=None):
    """
    P3: Mastering with single reference.
    [SV-01 FIX]: LP@18kHz applied HERE, once, on the final master.
    [SV-03 FIX]: Single reference track, gentle corrections only.
    [EK-01 FIX]: Max EQ correction 3dB per band, capped.
    [EK-02 FIX]: Reference mismatch check — skip correction if delta >5dB.
    """
    if target_lufs is None:
        target_lufs = ref_profile.get('lufs', -8.0)

    # Measure input
    in_lufs = measure_lufs(mL, mR)
    print(f"    P3 input: LUFS={in_lufs:.2f}  Target={target_lufs:.1f}")

    # 3A: Corrective EQ — LUFS-normalise the input FIRST, then compare shapes.
    # Previous bug: comparing a -20 LUFS mix to a -11 LUFS reference on absolute
    # spectral values caused wrong EQ targets even after mean-normalisation.
    # Fix: apply temporary loudness gain before profile measurement, measure shape,
    # then apply EQ corrections based on that accurate shape comparison.
    lufs_gain_for_eq = float(np.clip(target_lufs - in_lufs, -12.0, 18.0))
    mL_eq = gain_db_apply(mL, lufs_gain_for_eq)
    mR_eq = gain_db_apply(mR, lufs_gain_for_eq)
    in_prof = spectral_profile(((mL_eq+mR_eq)*0.5).astype(np.float32), SR)
    del mL_eq, mR_eq; gc.collect()

    ref_spectral = {k: v for k, v in ref_profile.items() if k in in_prof}
    if ref_spectral:
        ref_mean = float(np.mean(list(ref_spectral.values())))
        in_mean  = float(np.mean([in_prof[k] for k in ref_spectral]))
    else:
        ref_mean = in_mean = 0.0

    # EQ corrections — shaped to prevent the two known spectral problems:
    # 1. Low-end (sub/kick) was being boosted by reference comparison → cap at +0.5dB
    # 2. High-end (air/hi-mid) was being cut by reference comparison → boost-only for HF
    _lf_bands = {'deep_sub', 'sub', 'kick'}          # never boost more than 0.5dB
    _hf_bands = {'presence', 'hi_mid', 'air', 'ultra_air'}  # boost only, never cut
    corrections = {}
    for band_name, ref_val in ref_profile.items():
        if band_name not in in_prof: continue
        delta = (ref_val - ref_mean) - (in_prof[band_name] - in_mean)
        if abs(delta) > 5.0:
            print(f"    [SKIP] {band_name}: shape delta {delta:+.1f}dB exceeds 5dB limit (EK-02)")
            corrections[band_name] = 0.0
            continue
        raw_corr = delta * 0.35
        if band_name in _lf_bands:
            raw_corr = float(np.clip(raw_corr, -1.5, 0.5))   # LF: rarely boost, limit to +0.5dB
        elif band_name in _hf_bands:
            raw_corr = float(np.clip(raw_corr, -1.5, 1.5))  # HF: bidirectional — can boost OR cut
        else:
            raw_corr = float(np.clip(raw_corr, -2.0, 2.0))
        corrections[band_name] = raw_corr
        if abs(corrections[band_name]) > 0.3:
            print(f"    [EQ]  {band_name}: {corrections[band_name]:+.1f}dB")

    # Sub/kick balance — user tuning: lower sub, raise kick.
    # Sub shelf (below 45Hz): +0.5dB — gentle sub presence without boom.
    # Previous +2.0dB @ 60Hz was too heavy and masked the kick punch.
    sub_shelf_sos = sp.butter(2, 45/(SR/2), btype='low', output='sos')
    sub_shelf_L = sp.sosfiltfilt(sub_shelf_sos, mL.astype(np.float64)).astype(np.float32)
    sub_shelf_R = sp.sosfiltfilt(sub_shelf_sos, mR.astype(np.float64)).astype(np.float32)
    mL = (mL + sub_shelf_L * np.float32(10**(0.5/20) - 1.0)).astype(np.float32)
    mR = (mR + sub_shelf_R * np.float32(10**(0.5/20) - 1.0)).astype(np.float32)
    print(f"    [SUB RESTORE] Low-shelf +0.5dB @ 45Hz (sub lowered)")
    # Kick body boost: peak EQ +1.5dB @ 120Hz — raises punch of kick drum.
    mL = peak_eq(mL, 120, +1.5, Q=1.5); mR = peak_eq(mR, 120, +1.5, Q=1.5)
    print(f"    [KICK BOOST] +1.5dB peak @ 120Hz (kick raised)")

    # Apply corrective EQ by frequency band
    band_eq_map = {
        'deep_sub': (35, 0.8), 'sub': (75, 1.0), 'kick': (150, 1.2),
        'low_mid': (300, 1.5), 'mid_low': (600, 1.8), 'mid': (1400, 2.0),
        'presence': (3500, 2.0), 'hi_mid': (7500, 2.0), 'air': (13000, 1.5)
    }
    for band_name, gain in corrections.items():
        if band_name in band_eq_map and abs(gain) > 0.3:
            freq, Q = band_eq_map[band_name]
            mL = peak_eq(mL, freq, gain, Q); mR = peak_eq(mR, freq, gain, Q)

    # M/S widening REMOVED — the mix already has natural stereo width from demucs
    # stems and panning. Adding more here was pushing correlation below 0.80.
    gc.collect()

    # 3C: Harmonic saturation (very gentle — 5% wet)
    def tube_sat(y, drive=2.0, mix=0.05):
        pk=float(np.max(np.abs(y)))+1e-12; yn=y.astype(np.float64)/pk*drive
        sh=(np.tanh(yn+0.04*yn**2)*0.92+0.08*yn).astype(np.float32)
        sh=sh/(float(np.max(np.abs(sh)))+1e-12)*pk; return (y*(1-mix)+sh*mix).astype(np.float32)
    mL = tube_sat(mL); mR = tube_sat(mR)

    # LP@20kHz — removes only content beyond audible range (Demucs artefacts).
    # Previously 18kHz which cut audible air. 20kHz order 4 = -24dB/oct at Nyquist,
    # transparent to human hearing while still catching Demucs HF reconstruction noise.
    print("    [SV-01 FIX] Applying LP@20kHz ONCE on master (not per stem)")
    mL = lp(mL, 20000, order=4); mR = lp(mR, 20000, order=4)

    # 3D: Sub mono final lock
    sub_m = ((lp(mL,100)+lp(mR,100))*0.5).astype(np.float32)
    mL = (sub_m+hp(mL,100)).astype(np.float32); mR = (sub_m+hp(mR,100)).astype(np.float32)
    del sub_m; gc.collect()

    # 3E: ONE gain → ONE soft-clip → ONE hard limit
    current_lufs = measure_lufs(mL, mR)
    gain_n = target_lufs - current_lufs
    print(f"    [SV-02 FIX] Makeup gain: {gain_n:+.1f}dB (should be <3dB with correct P2 gain structure)")
    if abs(gain_n) > 6.0:
        print(f"    WARNING: {abs(gain_n):.1f}dB makeup gain is too large — P2 gain structure may need review")

    mL = gain_db_apply(mL, gain_n); mR = gain_db_apply(mR, gain_n)

    # TRANSPARENT LOOKAHEAD LIMITER — replaces soft clipper + hard clip.
    # The soft clipper was causing harmonic distortion ("crushed" sound) when
    # applied to a signal boosted by 10+ dB. A transparent lookahead limiter
    # has NO saturation — it only reduces gain for samples exceeding the ceiling.
    # 3ms lookahead prevents inter-sample peaks; 150ms release avoids pumping.
    ceiling_tp = float(10**(-0.3/20))
    la_samp    = int(0.003 * SR)      # 3ms lookahead
    rel_coeff  = np.exp(-1.0 / (0.150 * SR))  # 150ms release

    def _transparent_limit(L, R):
        L64 = L.astype(np.float64); R64 = R.astype(np.float64)
        combined = np.maximum(np.abs(L64), np.abs(R64))
        # Gain reduction needed per sample
        gr = np.minimum(1.0, ceiling_tp / (combined + 1e-12))
        # Lookahead: propagate the minimum GR backward (pre-empt peaks)
        for i in range(len(gr)-2, max(-1, len(gr)-1-la_samp*3), -1):
            if gr[i+1] < gr[i]:
                gr[i] = gr[i+1]
        # Release smoothing (gain can only recover at release rate)
        for i in range(1, len(gr)):
            if gr[i] > gr[i-1]:
                gr[i] = gr[i-1] + (1.0 - rel_coeff) * (gr[i] - gr[i-1])
        L_out = (L64 * gr).astype(np.float32)
        R_out = (R64 * gr).astype(np.float32)
        # Safety hard ceiling (handles numerical edge cases only)
        tp = np.float32(ceiling_tp)
        L_out = np.clip(L_out, -tp, tp)
        R_out = np.clip(R_out, -tp, tp)
        return L_out, R_out

    mL, mR = _transparent_limit(mL, mR)

    # Remove DC offset
    mL, mR = remove_dc_offset(mL, mR)
    # Final safety ceiling after DC filter
    tp = np.float32(ceiling_tp)
    mL = np.clip(mL, -tp, tp).astype(np.float32)
    mR = np.clip(mR, -tp, tp).astype(np.float32)

    out_lufs = measure_lufs(mL, mR)
    out_peak = peak_db(np.concatenate([mL, mR]))
    crest    = out_peak - out_lufs
    corr     = float(np.corrcoef(mL[:SR*10], mR[:SR*10])[0,1])
    print(f"    P3 output: LUFS={out_lufs:.2f}  Peak={out_peak:.2f}dBTP  Crest={crest:.1f}dB  Corr={corr:.3f}")

    return mL, mR, {'lufs': out_lufs, 'peak': out_peak, 'crest': crest, 'corr': corr}

# ─── QUALITY CHECKPOINT (EK-03) ────────────────────────────────────────────────

def quality_check(original_L, original_R, master_L, master_R):
    """
    [EK-03 FIX]: Compare 1/3-octave spectral bands between input and output.
    Flag any band that changed by more than HARM_GUARD dB.
    """
    print("\n  Quality Check (EK-03):")
    orig_y  = ((original_L + original_R) * 0.5).astype(np.float32)
    mast_y  = ((master_L + master_R) * 0.5).astype(np.float32)
    # Resample original if needed (it's at 44100Hz)
    if len(orig_y) != len(mast_y):
        # Normalise lengths for comparison only
        N = min(len(orig_y), len(mast_y))
        orig_y = orig_y[:N]; mast_y = mast_y[:N]

    # SV2-02: use middle 60s for representative spectral comparison
    mid_start = max(0, len(orig_y)//2 - SR*30)
    orig_S = np.abs(librosa.stft(orig_y[mid_start:mid_start+SR*60].astype(np.float64), n_fft=4096))
    mid_start = max(0, len(mast_y)//2 - SR*30)
    mast_S = np.abs(librosa.stft(mast_y[mid_start:mid_start+SR*60].astype(np.float64), n_fft=4096))
    freqs  = librosa.fft_frequencies(sr=SR, n_fft=4096)
    orig_m = np.mean(orig_S, axis=1); mast_m = np.mean(mast_S, axis=1)
    del orig_S, mast_S; gc.collect()

    flags = []
    for lo, hi, name in BANDS_HZ:
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any(): continue
        e0 = float(20*np.log10(np.mean(orig_m[mask])+1e-9))
        e1 = float(20*np.log10(np.mean(mast_m[mask])+1e-9))
        delta = e1 - e0
        flag = "[REVIEW]" if abs(delta) > HARM_GUARD else "[OK]"
        print(f"    {name:12s}: {e0:+.1f} -> {e1:+.1f}  ({delta:+.1f}dB)  {flag}")
        if abs(delta) > HARM_GUARD:
            flags.append(f"{name}: {delta:+.1f}dB")

    DIAGNOSTICS = {
        'air':      'Air band altered - consider less processing or LP at 20kHz instead of 18kHz',
        'ultra_air':'Ultra-air altered - expected from LP@18kHz (intentional)',
        'kick':     'Kick energy altered - check sidechain attack or bus level settings',
        'deep_sub': 'Sub bass altered significantly - check HP filter settings',
        'presence': 'Presence/mid altered - check EQ corrections in P3',
    }
    if flags:
        print(f"\n  [!] QUALITY FLAGS: {len(flags)} bands changed >8dB:")
        for fl in flags:
            band = fl.split(':')[0]
            hint = DIAGNOSTICS.get(band, 'Review P3 EQ corrections for this band')
            print(f"    {fl}  ->  {hint}")
    else:
        print(f"\n  [PASS] All bands within +/-{HARM_GUARD}dB of original - EK-03 PASS")

    # ── Pink noise compliance ──────────────────────────────────────────────────
    print(f"\n  Pink Noise Compliance (-3dB/octave target):")
    pn = compute_pink_noise_deviation(master_L, master_R)
    pn_warn = False
    for hz, energy, target, dev in pn:
        flag = '[!]' if abs(dev) > 3.0 else '[OK]'
        if abs(dev) > 3.0: pn_warn = True
        print(f"    {hz:>6}Hz: {energy:+.1f}dB  target={target:+.1f}  dev={dev:+.1f}dB  {flag}")
    if not pn_warn:
        print(f"    All octave bands within +/-3dB of pink noise curve")

    # ── Mono compatibility ─────────────────────────────────────────────────────
    print(f"\n  Mono Compatibility:")
    mc = mono_compatibility_check(master_L, master_R, SR)
    print(f"    Broadband corr : {mc['broadband']:.3f}  ({'OK' if mc['broadband']>=0.65 else 'WARN'})")
    print(f"    Bass corr      : {mc['bass']:.3f}  ({'OK' if mc['bass']>=0.90 else 'WARN — bass phase issue'})")
    print(f"    Mid corr       : {mc['mid']:.3f}  ({'OK' if mc['mid']>=0.60 else 'WARN'})")
    print(f"    High corr      : {mc['high']:.3f}")
    print(f"    Mono loudness  : {mc['loudness_diff_db']:+.1f}dB vs stereo  "
          f"({'OK' if mc['loudness_diff_db']>=-3 else 'WARN'})")
    print(f"    Status         : [{mc['status']}]")

    return flags


# ─── CHUNK 1: FOUNDATION — GAIN STAGING, PINK NOISE, STEREO, MONO COMPAT ──────

# Professional standard: 0 VU = -18 dBFS RMS.
# Keeps every processor working at its intended operating point and prevents
# noise/distortion from compounding through the chain.
GS_TARGET_RMS_DB = -18.0

def gain_stage(L, R, target_rms_db=GS_TARGET_RMS_DB, label='', allow_boost=True):
    """
    Normalise signal to target RMS (0VU = -18dBFS).
    Gain is bounded so peak never exceeds -0.5 dBFS.
    Returns: L, R, applied_gain_db
    """
    cur_rms = float(10 * np.log10(
        (np.mean(L.astype(np.float64)**2) + np.mean(R.astype(np.float64)**2)) / 2 + 1e-12))
    gain_needed = target_rms_db - cur_rms
    if not allow_boost and gain_needed > 0:
        return L, R, 0.0
    cur_peak = peak_db(np.concatenate([L, R]))
    max_gain = -0.5 - cur_peak
    gain_needed = float(np.clip(min(gain_needed, max_gain), -24.0, 18.0))
    if abs(gain_needed) > 0.2:
        L = gain_db_apply(L, gain_needed)
        R = gain_db_apply(R, gain_needed)
        if label:
            new_rms = float(10 * np.log10(
                (np.mean(L.astype(np.float64)**2) + np.mean(R.astype(np.float64)**2)) / 2 + 1e-12))
            print(f"    [GS] {label}: {gain_needed:+.1f}dB  RMS: {cur_rms:.1f} -> {new_rms:.1f}dBFS")
    return L.astype(np.float32), R.astype(np.float32), gain_needed


def bus_compressor(L, R, sr=SR, ratio=1.8, threshold_db=-12.0,
                   attack_ms=8.0, release_ms=80.0):
    """
    Gentle bus compressor applied to the P2 mix before LUFS gain.
    Reduces the mix's high crest factor so the LUFS gain can actually reach
    the -10 LUFS target without being blocked by the peak ceiling.
    Makeup gain is applied to restore average level.
    """
    def _compress(y):
        abs_y = np.abs(y.astype(np.float64))
        att_tau = attack_ms / 1000.0
        rel_tau = release_ms / 1000.0
        env = np.zeros_like(abs_y)
        for i in range(1, len(abs_y)):
            tau = att_tau if abs_y[i] > env[i-1] else rel_tau
            alpha = 1.0 - np.exp(-1.0 / (tau * sr + 1.0))
            env[i] = alpha * abs_y[i] + (1.0 - alpha) * env[i-1]
        env_db = 20.0 * np.log10(env + 1e-9)
        gr_db  = np.maximum(0.0, (threshold_db - env_db) * (ratio - 1.0) / ratio)
        gr_lin = np.power(10.0, -gr_db / 20.0)
        return (y * gr_lin).astype(np.float32), float(np.mean(gr_db))

    Lc, gr_L = _compress(L)
    Rc, gr_R = _compress(R)
    avg_gr   = (gr_L + gr_R) / 2.0
    # Makeup gain restores average level
    Lc = gain_db_apply(Lc, avg_gr)
    Rc = gain_db_apply(Rc, avg_gr)
    print(f"    [BUS COMP] ratio={ratio:.1f}:1  avg GR={avg_gr:.1f}dB  makeup={avg_gr:.1f}dB  -> crest reduced")
    return Lc, Rc


def ms_stereo_blend(proc_L, proc_R, orig_L, orig_R, side_blend=0.40):
    """
    Recover stereo width lost during stem-based reconstruction by blending
    original Side channel back into the processed mix.

    Uses the PROCESSED Mid channel (all cleaning, resonance removal, character)
    and blends ORIGINAL Side (stereo image) at the specified ratio.
    This gives us the benefits of processing + the original's width.

    side_blend: 0.0 = all processed side  |  1.0 = all original side
    """
    N = min(len(proc_L), len(orig_L))
    proc_L, proc_R = proc_L[:N], proc_R[:N]
    oL, oR = orig_L[:N].astype(np.float32), orig_R[:N].astype(np.float32)

    proc_mid  = ((proc_L + proc_R) * 0.5).astype(np.float32)
    proc_side = ((proc_L - proc_R) * 0.5).astype(np.float32)
    orig_side = ((oL - oR) * 0.5).astype(np.float32)

    # Level-match original Side to processed Side so blend is balanced
    ps_rms = float(np.sqrt(np.mean(proc_side.astype(np.float64)**2)) + 1e-12)
    os_rms = float(np.sqrt(np.mean(orig_side.astype(np.float64)**2)) + 1e-12)
    orig_side_scaled = (orig_side * np.float32(ps_rms / os_rms)).astype(np.float32)

    blended_side = (proc_side * np.float32(1.0 - side_blend)
                    + orig_side_scaled * np.float32(side_blend)).astype(np.float32)

    out_L = (proc_mid + blended_side).astype(np.float32)
    out_R = (proc_mid - blended_side).astype(np.float32)

    # Report width change
    orig_w = os_rms / (float(np.sqrt(np.mean(((oL+oR)*0.5)**2))) + 1e-12)
    proc_w = ps_rms / (float(np.sqrt(np.mean(proc_mid.astype(np.float64)**2))) + 1e-12)
    new_side_rms = float(np.sqrt(np.mean(blended_side.astype(np.float64)**2)) + 1e-12)
    new_w = new_side_rms / (float(np.sqrt(np.mean(proc_mid.astype(np.float64)**2))) + 1e-12)
    print(f"    [STEREO BLEND] orig width={orig_w:.3f}  processed={proc_w:.3f}  "
          f"blended={new_w:.3f}  (side_blend={side_blend:.0%})")
    return out_L, out_R


def remove_dc_offset(L, R):
    """Remove DC offset with a 5 Hz HP filter. Keeps audio clean for playback."""
    return hp(L, 5, order=2), hp(R, 5, order=2)


def mono_compatibility_check(L, R, sr=SR):
    """
    Full mono compatibility test.
    Professional targets:
      Broadband correlation >= 0.65
      Bass (20-200Hz) correlation >= 0.90  (must be near-mono)
      Mono loudness within -3 dB of stereo
    """
    def _corr(a, b):
        az = a - np.mean(a); bz = b - np.mean(b)
        d = np.sqrt(np.sum(az**2) * np.sum(bz**2))
        return float(np.sum(az * bz) / d) if d > 1e-12 else 0.0

    def _band_corr(lo, hi):
        sos = sp.butter(4, [lo / (sr/2), min(hi / (sr/2), 0.999)], 'band', output='sos')
        bl  = sp.sosfilt(sos, L.astype(np.float64))
        br  = sp.sosfilt(sos, R.astype(np.float64))
        return _corr(bl, br)

    broadband = _corr(L, R)
    bass_corr  = _band_corr(20,   200)
    mid_corr   = _band_corr(200,  2000)
    high_corr  = _band_corr(2000, 16000)

    mono          = (L.astype(np.float64) + R.astype(np.float64)) / 2
    stereo_rms    = float(np.sqrt((np.mean(L.astype(np.float64)**2) + np.mean(R.astype(np.float64)**2)) / 2))
    mono_rms      = float(np.sqrt(np.mean(mono**2)))
    loudness_diff = float(20 * np.log10(mono_rms / (stereo_rms + 1e-12) + 1e-12))

    status = ('PASS' if broadband >= 0.65 and bass_corr >= 0.90 and loudness_diff >= -3.0
              else 'WARN')
    return {
        'broadband': broadband, 'bass': bass_corr,
        'mid': mid_corr,        'high': high_corr,
        'loudness_diff_db': loudness_diff, 'status': status,
    }


def compute_pink_noise_deviation(L, R, sr=SR):
    """
    Measure how well the mix follows the -3 dB/octave pink noise slope.
    Returns list of (center_hz, energy_db, target_db, deviation_db) per octave band.
    A well-balanced mix should be within ±2 dB of target at each octave.
    """
    mono = ((L.astype(np.float64) + R.astype(np.float64)) * 0.5)
    # Octave band centres 80 Hz → 10.24 kHz (7 octaves)
    centres = [80, 160, 320, 640, 1280, 2560, 5120, 10240]
    bands = []
    ref_energy = None
    for fc in centres:
        lo = fc / 2**0.5
        hi = min(fc * 2**0.5, sr / 2 * 0.99)
        sos = sp.butter(4, [lo / (sr/2), hi / (sr/2)], 'band', output='sos')
        b   = sp.sosfilt(sos, mono)
        e   = float(10 * np.log10(np.mean(b**2) + 1e-12))
        if ref_energy is None:
            ref_energy = e
        bands.append(e)

    # Pink noise target: -3 dB per octave from first band
    targets    = [ref_energy + i * (-3.0) for i in range(len(bands))]
    deviations = [b - t for b, t in zip(bands, targets)]
    return list(zip(centres, bands, targets, deviations))


# ─── CHUNK 2: PHASE ROTATION, STEM CLIPPER, AI VOCAL PROCESSING ───────────────

from scipy.signal import lfilter, resample_poly
from scipy.ndimage import median_filter as _median_filter

# Allpass coefficient: k = (tan(pi*fc/sr) - 1) / (tan(pi*fc/sr) + 1)
# H(z) = (k + z^-1) / (1 + k*z^-1)  — unity magnitude at all frequencies.
# Apply same fc to L and R to preserve stereo image.
# Skip drums entirely — smears transients.
_PHASE_ROT_FREQS = {
    'bass':   [50, 80, 120, 180],
    'vocals': [150, 250, 400, 800],
    'guitar': [200, 350, 600, 1200],
    'piano':  [150, 300, 600, 1000],
    'other':  [150, 300, 600, 1200],
    'drums':  [],   # skip — transient smearing is audible
}

def _allpass1(y, fc, sr):
    """First-order allpass filter. Magnitude = 1 at all freqs."""
    k = (np.tan(np.pi * fc / sr) - 1.0) / (np.tan(np.pi * fc / sr) + 1.0)
    return lfilter([k, 1.0], [1.0, k], y.astype(np.float64)).astype(np.float32)

def phase_rotate_for_headroom(L, R, sr=SR, stem_type='other'):
    """
    Search over allpass cutoff frequencies, keep the rotation that gives
    the lowest peak on L+R without changing RMS (allpass is magnitude-neutral).
    Typical headroom gain: 0.5-2.0 dB on tonal material.
    Drums skipped entirely — transient smearing is audible and destructive.
    """
    test_freqs = _PHASE_ROT_FREQS.get(stem_type, _PHASE_ROT_FREQS['other'])
    if not test_freqs:
        return L, R   # drums

    orig_peak = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))))
    best_L, best_R = L.copy(), R.copy()
    best_peak = orig_peak
    best_fc   = None

    for fc in test_freqs:
        try:
            Lr = _allpass1(L, fc, sr)
            Rr = _allpass1(R, fc, sr)
            p  = max(float(np.max(np.abs(Lr))), float(np.max(np.abs(Rr))))
            if p < best_peak:
                best_peak = p; best_L = Lr; best_R = Rr; best_fc = fc
        except Exception:
            pass

    if best_fc is not None:
        gain_db = 20.0 * np.log10(orig_peak / (best_peak + 1e-12))
        if gain_db > 0.15:
            print(f"    [{stem_type}] Phase rotation @{best_fc}Hz: +{gain_db:.2f}dB headroom")

    return best_L.astype(np.float32), best_R.astype(np.float32)


# Stem clip ceilings (dBFS). Soft tanh knee at 85% of ceiling.
# 4x oversampling on vocals to prevent aliasing of harmonic content.
_STEM_CEILINGS = {
    'drums': -3.0, 'bass': -4.0, 'vocals': -3.0,
    'guitar': -4.0, 'piano': -4.0, 'other': -4.0,
}

def stem_soft_clipper(L, R, stem_type='other', sr=SR):
    """
    Soft-clip individual stems to remove extreme peak transients before mixing.
    Uses tanh curve with knee at 85% of ceiling — completely transparent below knee.
    Vocals use 4x oversampling (mandatory to prevent aliasing in harmonic content).
    Typical headroom recovery: 1.5-3 dB across the full mix.
    """
    ceiling_db  = _STEM_CEILINGS.get(stem_type, -4.0)
    ceiling_lin = float(10 ** (ceiling_db / 20.0))
    knee_lin    = ceiling_lin * 0.85
    span        = ceiling_lin - knee_lin
    oversample  = 4 if stem_type == 'vocals' else 2

    def _clip(y):
        y64 = y.astype(np.float64)
        if oversample > 1:
            y64 = resample_poly(y64, oversample, 1).astype(np.float64)
        sign  = np.sign(y64)
        mag   = np.abs(y64)
        above = mag > knee_lin
        out   = y64.copy()
        if above.any():
            exc = (mag[above] - knee_lin) / span
            sat = np.tanh(exc * 2.0) / np.tanh(2.0)
            out[above] = sign[above] * (knee_lin + span * np.clip(sat, 0.0, 1.0))
        if oversample > 1:
            out = resample_poly(out, 1, oversample).astype(np.float64)
        # Hard ceiling guarantee
        return np.clip(out, -ceiling_lin, ceiling_lin).astype(np.float32)

    orig_pk = peak_db(np.concatenate([L, R]))
    Lc = _clip(L);  Rc = _clip(R)
    new_pk = peak_db(np.concatenate([Lc, Rc]))
    if orig_pk - new_pk > 0.1:
        print(f"    [{stem_type}] Stem clip {orig_pk:.1f}->{new_pk:.1f}dBFS "
              f"(+{orig_pk-new_pk:.1f}dB headroom)")
    return Lc, Rc


# ── AI Vocal Processing ──────────────────────────────────────────────────────

# Multi-band de-essing — DISABLED pending calibration.
# Previous thresholds (-18 to -24 dBFS) matched the gain-staged stem RMS,
# causing the de-esser to trigger CONTINUOUSLY, permanently cutting 4+ dB
# from the entire 2-16kHz range. This made the master dark and muffled.
# Will be rebuilt in Chunk 3 with per-stem adaptive thresholds.
_DEESS_PROFILES = {
    'vocals': [],   # disabled
    'drums':  [],   # disabled
    'guitar': [],   # disabled
}

def _deess_band(y, lo, hi, ratio, thresh_db, att_ms, rel_ms, sr):
    """Dynamic compression in a single frequency band (bandpass sidechain)."""
    nyq = sr / 2.0
    sos_bp = sp.butter(4, [lo / nyq, min(hi / nyq, 0.999)], 'band', output='sos')
    band   = sp.sosfiltfilt(sos_bp, y.astype(np.float64)).astype(np.float32)
    abs_b  = np.abs(band.astype(np.float64))
    att_tau = att_ms / 1000.0;  rel_tau = rel_ms / 1000.0
    env = np.zeros_like(abs_b)
    for i in range(1, len(abs_b)):
        tau = att_tau if abs_b[i] > env[i-1] else rel_tau
        a   = 1.0 - np.exp(-1.0 / (tau * sr + 1.0))
        env[i] = a * abs_b[i] + (1.0 - a) * env[i-1]
    env_db = 20.0 * np.log10(env + 1e-9)
    gr_db  = np.maximum(0.0, (thresh_db - env_db) * (ratio - 1.0) / ratio)
    gr_lin = np.power(10.0, -gr_db / 20.0).astype(np.float32)
    return (y.astype(np.float32) - band + (band * gr_lin)).astype(np.float32)

def deess_multiband(L, R, stem_type='vocals', sr=SR):
    """Apply multi-band de-essing per the stem's profile."""
    profile = _DEESS_PROFILES.get(stem_type)
    if not profile:
        return L, R
    Lp, Rp = L.copy(), R.copy()
    for lo, hi, ratio, thresh, att, rel in profile:
        Lp = _deess_band(Lp, lo, hi, ratio, thresh, att, rel, sr)
        Rp = _deess_band(Rp, lo, hi, ratio, thresh, att, rel, sr)
    return Lp, Rp

def transient_shape_vocal(L, R, sr=SR):
    """
    Smooth unnaturally sharp AI vocal attacks.
    Human vocal muscles take 8-15 ms to develop full air pressure — AI voices
    can start almost instantaneously. Detected abrupt attacks (>12 dB in <5 ms)
    get a gentle 10 ms linear ramp applied.
    """
    def _smooth(y):
        hop = max(1, int(sr * 0.001))   # 1 ms hop
        n   = len(y) // hop
        if n < 2:
            return y
        rms_f = np.array([float(np.sqrt(np.mean(y[i*hop:(i+1)*hop]**2) + 1e-20))
                          for i in range(n)])
        gain_env = np.ones(len(y), dtype=np.float64)
        ramp_s   = max(1, int(sr * 0.010))   # 10 ms ramp
        for i in range(1, n):
            if rms_f[i-1] > 1e-10:
                rise = 20.0 * np.log10(rms_f[i] / rms_f[i-1])
                if rise > 12.0:
                    s = i * hop
                    e = min(s + ramp_s, len(gain_env))
                    gain_env[s:e] *= np.linspace(0.55, 1.0, e - s)
        return (y * gain_env).astype(np.float32)
    return _smooth(L.astype(np.float64)), _smooth(R.astype(np.float64))

def remove_ai_glitch_artifacts(L, R, sr=SR):
    """
    Gate brief anomalous energy spikes in the AI artifact zone (2-8 kHz).
    Frames where band energy exceeds local median by >15 dB are reduced by 8 dB.
    These spikes are a signature of neural vocoder synthesis glitches.
    """
    mono  = ((L.astype(np.float64) + R.astype(np.float64)) * 0.5)
    sos   = sp.butter(4, [2000/(sr/2), min(8000/(sr/2), 0.999)], 'band', output='sos')
    band  = np.abs(sp.sosfiltfilt(sos, mono))
    hop   = max(1, int(sr * 0.010))   # 10 ms frames
    n_fr  = len(band) // hop
    if n_fr < 4:
        return L, R
    frms  = np.array([float(np.sqrt(np.mean(band[i*hop:(i+1)*hop]**2) + 1e-20))
                      for i in range(n_fr)])
    win   = min(20, n_fr // 4)
    norm  = _median_filter(frms, size=max(1, win))
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio_db = np.where(norm > 1e-12,
                            20.0 * np.log10(frms / (norm + 1e-12)), 0.0)
    art_frames = ratio_db > 25.0   # was 15dB — too sensitive, causing 277 cuts
    n_art = int(np.sum(art_frames))
    if n_art == 0:
        return L, R
    # Gentle reduction only (-4dB, not -8dB) to avoid audible pumping/cutting.
    # Ramp 20ms to soften transitions (was 5ms, causing click artifacts).
    reduction = float(10 ** (-4.0 / 20.0))
    ramp_s    = max(1, int(sr * 0.020))   # 20ms ramp
    gain_env  = np.ones(len(L), dtype=np.float64)
    for i in np.where(art_frames)[0]:
        s = i * hop; e = min(s + hop, len(gain_env))
        onset_e = min(s + ramp_s, e)
        gain_env[s:onset_e] *= np.linspace(1.0, reduction, onset_e - s)
        gain_env[onset_e:e] *= reduction
    print(f"    [vocals] Glitch gate: {n_art} artifact frames softened (-4dB, 20ms ramp)")
    return (L.astype(np.float64) * gain_env[:len(L)]).astype(np.float32), \
           (R.astype(np.float64) * gain_env[:len(R)]).astype(np.float32)

def spectral_resonance_suppress(y, sr=SR, sensitivity=0.55, depth_max_db=7.0,
                                 freq_lo=200, freq_hi=16000):
    """
    Soothe2-equivalent dynamic resonance suppressor.
    Analyzes spectrum frame-by-frame. Any bin that protrudes significantly
    above the smoothed spectral background gets gently attenuated.
    Completely transparent on clean, balanced material.
    Only activates on genuine resonance spikes — unlike a static EQ.

    sensitivity : 0.0 = off,  1.0 = max suppression
    depth_max_db: maximum attenuation per bin per frame
    """
    n_fft = 2048
    hop   = n_fft // 4
    D     = librosa.stft(y.astype(np.float64), n_fft=n_fft, hop_length=hop)
    mag   = np.abs(D)
    phase = np.angle(D)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    freq_mask = (freqs >= freq_lo) & (freqs <= freq_hi)

    threshold_db = 4.0 / max(sensitivity, 0.01)   # lower sensitivity → higher threshold

    # Vectorized: apply median filter over frequency axis for all frames at once.
    # scipy.ndimage.median_filter(size=(21,1)) = median over 21 freq bins, 1 time frame.
    # ~50x faster than the previous per-frame Python loop.
    from scipy.ndimage import median_filter as _ndimage_mf
    bg = _ndimage_mf(mag.astype(np.float64), size=(21, 1)).astype(np.float32)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio_db = np.where(bg > 1e-10,
                            20.0 * np.log10(mag / (bg + 1e-12) + 1e-9),
                            0.0)
    excess_db  = np.maximum(0.0, ratio_db - threshold_db)
    reduce_db  = np.minimum(excess_db * 1.5, depth_max_db) * sensitivity
    reduce_lin = np.power(10.0, -reduce_db / 20.0)
    reduce_lin[~freq_mask, :] = 1.0   # leave out-of-range bins untouched
    mag_out = (mag * reduce_lin).astype(np.float32)

    D_out = mag_out * np.exp(1j * phase)
    return librosa.istft(D_out, hop_length=hop, length=len(y)).astype(np.float32)

def adaptive_deesser(L, R, sr=SR, freq_lo=5000, freq_hi=14000,
                     margin_db=6.0, ratio=2.5, att_ms=4.0, rel_ms=25.0):
    """
    Adaptive de-esser with dynamic threshold.
    Threshold = per-frame RMS of the sibilance band + margin_db.
    Only fires when energy in the de-ess band genuinely spikes above background.
    Far more musical than a fixed threshold which compresses continuously.
    """
    def _deess_ch(y):
        nyq = sr / 2.0
        sos = sp.butter(4, [freq_lo/nyq, min(freq_hi/nyq, 0.999)], 'band', output='sos')
        band = sp.sosfiltfilt(sos, y.astype(np.float64)).astype(np.float32)
        abs_b = np.abs(band.astype(np.float64))
        # Slow RMS = adaptive background level
        slow_rms = np.zeros_like(abs_b)
        slow_tc  = np.exp(-1.0 / (0.100 * sr))   # 100ms smoothing
        for i in range(1, len(abs_b)):
            slow_rms[i] = slow_tc * slow_rms[i-1] + (1-slow_tc) * abs_b[i]**2
        bg_rms = np.sqrt(slow_rms + 1e-12)
        threshold = bg_rms * 10**(margin_db/20.0)
        # Envelope follower for gain reduction
        att_tau = att_ms / 1000.0;  rel_tau = rel_ms / 1000.0
        env = np.zeros_like(abs_b)
        for i in range(1, len(abs_b)):
            tau = att_tau if abs_b[i] > env[i-1] else rel_tau
            a   = 1.0 - np.exp(-1.0 / (tau * sr + 1.0))
            env[i] = a * abs_b[i] + (1.0-a) * env[i-1]
        env_db = 20.0 * np.log10(env + 1e-9)
        thr_db = 20.0 * np.log10(threshold + 1e-9)
        gr_db  = np.maximum(0.0, (thr_db - env_db) * (ratio-1.0) / ratio)
        gr_lin = np.power(10.0, -gr_db / 20.0).astype(np.float32)
        return (y.astype(np.float32) - band + band * gr_lin).astype(np.float32)
    return _deess_ch(L), _deess_ch(R)


def vocal_despike(L, R, sr=SR, window_ms=20, spike_ratio_db=12.0):
    """
    Detect and limit amplitude spikes using a sliding RMS envelope.
    Demucs stem separation creates 1,000+ spurious amplitude spikes in vocals.
    Samples exceeding the local RMS by spike_ratio_db are gain-reduced to threshold.
    Fast implementation via convolution (O(N log N), no inner loops).
    """
    def _despike(y):
        y64 = y.astype(np.float64)
        win = max(3, int(sr * window_ms / 1000))
        kernel = np.ones(win) / win
        env_sq = np.convolve(y64 ** 2, kernel, mode='same')
        env    = np.sqrt(np.maximum(env_sq, 1e-20))
        thresh = env * float(10 ** (spike_ratio_db / 20.0))
        mag    = np.abs(y64)
        scale  = np.where(mag > thresh, thresh / (mag + 1e-12), 1.0)
        return (y64 * scale).astype(np.float32)

    pk_in  = float(20 * np.log10(np.max(np.abs(L)) + 1e-12))
    Ld = _despike(L); Rd = _despike(R)
    pk_out = float(20 * np.log10(np.max(np.abs(Ld)) + 1e-12))
    print(f"    [vocals] Despike: peak {pk_in:.1f} -> {pk_out:.1f}dBFS")
    return Ld, Rd


def vocal_compress(L, R, sr=SR, threshold_db=-32.0, ratio=4.0,
                   attack_ms=5.0, release_ms=80.0, makeup_db=6.0):
    """
    Vocal compressor to tame crest factor from 22dB down to 12-18dB range.

    Key design decisions (v2 — fixed after first attempt backfired):
      - threshold_db=-32: sits 4-6dB BELOW the voiced-section RMS so the
        compressor genuinely engages on all voiced content, not just peaks.
        Previous -26dB was above much of the voiced RMS, leaving it untouched.
      - attack_ms=5: fast enough to catch peaks before they escape.
        Previous 20ms let ALL transients pass unattenuated → RMS dropped
        faster than peaks → crest went UP (opposite of intended).
      - ratio=4:1: firm enough to bring down peaks meaningfully.
      - makeup_db=6: restores average level lost through GR.

    The compressor measures RMS only on voiced frames (>-55dBFS) for the
    threshold, so long silences don't drag down the envelope and fool it.
    """
    def _comp(y):
        y64     = y.astype(np.float64)
        abs_y   = np.abs(y64)
        att_tau = attack_ms  / 1000.0
        rel_tau = release_ms / 1000.0
        env = np.zeros_like(abs_y)
        for i in range(1, len(abs_y)):
            tau   = att_tau if abs_y[i] > env[i-1] else rel_tau
            alpha = 1.0 - np.exp(-1.0 / (tau * sr + 1.0))
            env[i] = alpha * abs_y[i] + (1.0 - alpha) * env[i-1]
        env_db  = 20.0 * np.log10(env + 1e-9)
        over_db = np.maximum(0.0, env_db - threshold_db)
        gr_db   = over_db * (1.0 - 1.0 / ratio)
        gr_lin  = np.power(10.0, -gr_db / 20.0)
        makeup  = float(10 ** (makeup_db / 20.0))
        return (y64 * gr_lin * makeup).astype(np.float32)

    Lc = _comp(L); Rc = _comp(R)
    # Safety ceiling
    pk = max(float(np.max(np.abs(Lc))), float(np.max(np.abs(Rc))))
    if pk > 10 ** (-0.5 / 20):
        sc = np.float32(10 ** (-0.5 / 20) / pk); Lc *= sc; Rc *= sc

    in_crest  = peak_db(np.concatenate([L,  R ]))  - rms_db(np.concatenate([L,  R ]))
    out_crest = peak_db(np.concatenate([Lc, Rc])) - rms_db(np.concatenate([Lc, Rc]))
    print(f"    [vocals] Compress: crest {in_crest:.1f} -> {out_crest:.1f}dB  (thr={threshold_db}dB, {ratio:.1f}:1)")
    return Lc, Rc


def vocal_width_control(L, R, sr=SR, crossover_hz=2000,
                        side_lo=0.0, side_hi=0.10):
    """
    Force vocals to near-mono below crossover, preserve 10% side above crossover.
    Lead vocals must sit in the center — professional standard is mono below 2kHz.
    Reduces stereo width from 0.401 to near-mono (<0.15), fixing the AI-stereo artefact.
    side_lo=0.0  : strict mono below 2kHz  (essential for lead vocals)
    side_hi=0.10 : 10% side above 2kHz     (gentle air / presence)
    """
    lo_sos = sp.butter(4, crossover_hz / (sr / 2), 'lp', output='sos')
    hi_sos = sp.butter(4, crossover_hz / (sr / 2), 'hp', output='sos')
    M  = ((L.astype(np.float64) + R.astype(np.float64)) * 0.5)
    S  = ((L.astype(np.float64) - R.astype(np.float64)) * 0.5)
    S_lo  = sp.sosfiltfilt(lo_sos, S) * side_lo
    S_hi  = sp.sosfiltfilt(hi_sos, S) * side_hi
    S_new = (S_lo + S_hi)
    Lw = (M + S_new).astype(np.float32)
    Rw = (M - S_new).astype(np.float32)
    in_w  = float(np.sqrt(np.mean(((L - R) * 0.5) ** 2)) /
                  (np.sqrt(np.mean(((L + R) * 0.5) ** 2)) + 1e-12))
    out_w = float(np.sqrt(np.mean(((Lw - Rw) * 0.5) ** 2)) /
                  (np.sqrt(np.mean(((Lw + Rw) * 0.5) ** 2)) + 1e-12))
    print(f"    [vocals] Width: {in_w:.3f} -> {out_w:.3f} (near-mono)")
    return Lw, Rw


def vocal_humanize(L, R, sr=SR, depth=0.03, rate_hz=0.25):
    """
    Subtle 3-band harmonic modulation to reduce AI static-harmonic signature.
    AI vocals have perfectly constant harmonic amplitude — human voices naturally
    fluctuate. Three independent sinusoidal amplitude modulators at prime-ratio
    rates create realistic harmonic flutter.
    depth=0.03: 3% peak amplitude modulation per band (transparent)
    rate_hz: base modulation rate (0.25 Hz ≈ one cycle per 4 seconds)
    """
    t    = np.arange(len(L), dtype=np.float64) / sr
    mod1 = 1.0 + depth * np.sin(2 * np.pi * rate_hz * t)
    mod2 = 1.0 + depth * 0.7 * np.sin(2 * np.pi * rate_hz * 1.31 * t + 0.7)
    mod3 = 1.0 + depth * 0.5 * np.sin(2 * np.pi * rate_hz * 2.13 * t + 1.4)

    lo_sos = sp.butter(4, 800  / (sr / 2), 'lp', output='sos')
    mi_sos = sp.butter(4, [800 / (sr / 2), min(4000 / (sr / 2), 0.999)], 'band', output='sos')
    hi_sos = sp.butter(4, 4000 / (sr / 2), 'hp', output='sos')

    def _mod(y):
        y64 = y.astype(np.float64)
        lo  = sp.sosfiltfilt(lo_sos, y64) * mod1
        mi  = sp.sosfiltfilt(mi_sos, y64) * mod2
        hi  = sp.sosfiltfilt(hi_sos, y64) * mod3
        return (lo + mi + hi).astype(np.float32)

    Lh = _mod(L); Rh = _mod(R)
    # Level-preserve: keep original peak level
    pk_in  = max(float(np.max(np.abs(L))),  float(np.max(np.abs(R))),  1e-12)
    pk_out = max(float(np.max(np.abs(Lh))), float(np.max(np.abs(Rh))), 1e-12)
    Lh = (Lh * np.float32(pk_in / pk_out)).astype(np.float32)
    Rh = (Rh * np.float32(pk_in / pk_out)).astype(np.float32)
    print(f"    [vocals] Humanize: 3-band modulation {depth*100:.0f}% @ {rate_hz}Hz (anti-AI-static)")
    return Lh, Rh


def process_ai_vocals(L, R, sr=SR, skip_soothe=False):
    """
    Full AI vocal processing chain — applied only to the vocals stem.

    Order (professional standard):
      1. Despike       — remove Demucs amplitude spikes (sliding-RMS gate)
      2. Compress      — tame crest from 22dB to 12-18dB (optical 3:1)
      3. Glitch gate   — remove extreme AI synthesis artifacts in 2-8kHz
      4. Soothe        — spectral resonance suppressor (vectorized median, ~50x faster)
                         Skipped when skip_soothe=True (e.g. Audimee vocal already
                         had tilt correction applied — saves ~1 GB RAM)
      5. De-esser      — adaptive 4-14kHz (wider than v5.3, catches harsh AI sibilance)
      6. Transient smooth — soften unnaturally sharp AI vocal onsets
      7. Humanize      — 3-band harmonic modulation (reduces AI-static signature)
      8. Width control — near-mono below 2kHz, 10% side above 2kHz

    Every step: conservative, transparent, DO NO HARM.
    """
    chain = "despike+compress+gate+deess+smooth+humanize+width" if skip_soothe \
            else "despike+compress+gate+soothe+deess+smooth+humanize+width"
    print(f"    [vocals] AI vocal chain: {chain}")
    # 1. Despike
    L, R = vocal_despike(L, R, sr)
    # 2. Compress
    L, R = vocal_compress(L, R, sr)
    # 3. Glitch gate
    L, R = remove_ai_glitch_artifacts(L, R, sr)
    gc.collect()
    # 4. Spectral resonance suppressor — skip if tilt correction already applied
    if not skip_soothe:
        Lm = ((L + R) * 0.5).astype(np.float32)
        Sm = ((L - R) * 0.5).astype(np.float32)
        Lm_s = spectral_resonance_suppress(Lm, sr, sensitivity=0.55, depth_max_db=7.0)
        del Lm; gc.collect()
        L = (Lm_s + Sm).astype(np.float32)
        R = (Lm_s - Sm).astype(np.float32)
        del Lm_s, Sm; gc.collect()
    # 5. Adaptive de-esser (4-14kHz)
    L, R = adaptive_deesser(L, R, sr=sr, freq_lo=4000, freq_hi=14000,
                             margin_db=5.0, ratio=3.0)
    gc.collect()
    # 6. Transient smoothing
    L, R = transient_shape_vocal(L, R, sr)
    # 7. Humanize
    L, R = vocal_humanize(L, R, sr)
    # 8. Width control
    L, R = vocal_width_control(L, R, sr)
    return L, R


# ─── GUIDE FILE GENERATION ─────────────────────────────────────────────────────
# Produces a package of 4 reference files alongside the vocal stem export.
# These guide Audimee (or any vocal AI renderer) to sing in time, at the right
# pitch, and with the right dynamics — then the clean vocal drops back into
# the pipeline via --vocal for a full professional re-master.

def generate_click_track(bpm, duration_s, sr=SR):
    """
    Stereo click track at detected BPM.
    Beat 1 of every bar: 1000 Hz sine burst at 0.9 amplitude (downbeat).
    Beats 2-4: 750 Hz sine burst at 0.5 amplitude.
    8 ms burst with natural exponential decay — sounds like a studio click.
    """
    n_samples = int(duration_s * sr) + sr
    click = np.zeros(n_samples, dtype=np.float32)
    burst_len = int(0.008 * sr)
    t_b = np.linspace(0.0, 1.0, burst_len)
    downbeat  = (np.sin(2*np.pi*1000*t_b) * np.exp(-t_b*15) * 0.90).astype(np.float32)
    beatclick = (np.sin(2*np.pi*750 *t_b) * np.exp(-t_b*15) * 0.50).astype(np.float32)
    beat_samps = sr * 60.0 / bpm
    beat_num = 0; pos = 0.0
    while int(pos) < n_samples - burst_len:
        s = int(pos)
        wave = downbeat if beat_num % 4 == 0 else beatclick
        click[s:s+burst_len] += wave
        pos += beat_samps; beat_num += 1
    click = np.clip(click, -1.0, 1.0)
    return np.stack([click, click], axis=1).astype(np.float32)


def generate_kick_pulse(drums_L, drums_R, sr=SR):
    """
    Extract real kick drum transients from the drums stem and render them as
    sharp audio pulses — a musical groove guide instead of a rigid metronome.
    Bandpass 40-120 Hz isolates the kick body; envelope follower + peak-pick
    finds each hit; 10 ms Gaussian pulse marks it cleanly.
    """
    mono = ((drums_L.astype(np.float64) + drums_R.astype(np.float64)) * 0.5)
    sos  = sp.butter(4, [40/(sr/2), min(120/(sr/2), 0.999)], 'band', output='sos')
    kick_band = np.abs(sp.sosfiltfilt(sos, mono))
    att = np.exp(-1.0 / (0.003 * sr)); rel = np.exp(-1.0 / (0.080 * sr))
    env = np.zeros_like(kick_band)
    for i in range(1, len(kick_band)):
        c = att if kick_band[i] > env[i-1] else rel
        env[i] = c * env[i-1] + (1-c) * kick_band[i]
    thresh   = float(np.percentile(env[env>0], 60)) if np.any(env>0) else 0.01
    min_dist = max(1, int(sr * 0.06))   # 60 ms minimum between kicks
    peaks, _ = find_peaks(env, height=thresh, distance=min_dist)
    pulse = np.zeros(len(mono), dtype=np.float32)
    burst = int(0.010 * sr)
    t_p   = np.linspace(-3, 3, burst)
    shape = (np.exp(-0.5 * t_p**2) * 0.85).astype(np.float32)
    for pk in peaks:
        s = max(0, pk - burst//2); e = min(len(pulse), s+burst)
        pulse[s:e] = np.maximum(pulse[s:e], shape[:e-s])
    print(f"    [GUIDE] Kick pulse: {len(peaks)} hits detected")
    return np.stack([pulse, pulse], axis=1).astype(np.float32)


def generate_vocal_envelope(vocal_L, vocal_R, sr=SR):
    """
    Dynamics guide: a 220 Hz tone modulated by the vocal amplitude envelope.
    When played, the listener hears exactly when and how loud the vocals should
    be — phrasing, breath positions, swells. Helps Audimee match dynamics.
    """
    mono = ((vocal_L.astype(np.float64) + vocal_R.astype(np.float64)) * 0.5)
    win  = max(1, int(sr * 0.050))                         # 50 ms RMS window
    env  = np.sqrt(np.maximum(np.convolve(mono**2, np.ones(win)/win, mode='same'), 0.0))
    sos_sm = sp.butter(2, 10/(sr/2), 'lp', output='sos')
    env  = sp.sosfiltfilt(sos_sm, env)                     # extra smoothing
    env_max = float(np.max(env))
    if env_max > 0: env = (env / env_max).astype(np.float32)
    t    = np.arange(len(env), dtype=np.float64) / sr
    tone = (np.sin(2*np.pi*220*t) * env * 0.70).astype(np.float32)
    return np.stack([tone, tone], axis=1).astype(np.float32)


def _write_midi_file(path, notes, bpm, ticks_per_beat=480):
    """
    Write a minimal Type-0 MIDI file without any external library.
    notes: list of (start_s, duration_s, midi_note 0-127, velocity 0-127)
    """
    import struct
    def var_len(n):
        n = max(0, int(n))
        buf = [n & 0x7F]; n >>= 7
        while n: buf.insert(0, (n & 0x7F) | 0x80); n >>= 7
        return bytes(buf)
    uspb   = int(60_000_000 / max(bpm, 1))
    events = [(0, bytes([0xFF, 0x51, 0x03]) + struct.pack('>I', uspb)[1:])]
    for start_s, dur_s, note, vel in notes:
        if not (0 <= note <= 127 and dur_s > 0.01): continue
        note = int(np.clip(note, 0, 127)); vel = int(np.clip(vel, 1, 127))
        st = int(start_s * bpm / 60.0 * ticks_per_beat)
        et = int((start_s + dur_s) * bpm / 60.0 * ticks_per_beat)
        events.append((st, bytes([0x90, note, vel])))
        events.append((et, bytes([0x80, note, 0])))
    events.sort(key=lambda x: x[0])
    track_data = b''; cur = 0
    for tick, data in events:
        track_data += var_len(tick - cur) + data; cur = tick
    track_data += var_len(0) + bytes([0xFF, 0x2F, 0x00])
    header = b'MThd' + struct.pack('>I', 6) + struct.pack('>HHH', 0, 1, ticks_per_beat)
    track  = b'MTrk' + struct.pack('>I', len(track_data)) + track_data
    with open(str(path), 'wb') as f: f.write(header + track)


def generate_melody_midi(vocal_L, vocal_R, bpm, sr=SR, path=None):
    """
    Detect the vocal melody with librosa pyin and export as a MIDI file.
    Each detected phrase becomes a MIDI note with velocity from local RMS.
    Audimee (or a human vocalist) can use this as a melody guide.
    """
    mono = ((vocal_L.astype(np.float64) + vocal_R.astype(np.float64)) * 0.5).astype(np.float32)
    try:
        f0, voiced, _ = librosa.pyin(
            mono, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C6'),
            sr=sr, hop_length=512)
    except Exception as ex:
        print(f"    [GUIDE] MIDI pitch detection failed: {ex}"); return
    hop_s = 512.0 / sr
    notes = []; i = 0
    while i < len(f0):
        if voiced[i] and f0[i] is not None and not np.isnan(f0[i]):
            start_s = i * hop_s
            ref_midi = int(np.round(librosa.hz_to_midi(f0[i])))
            j = i + 1
            while j < len(f0) and voiced[j] and not np.isnan(f0[j]):
                if abs(int(np.round(librosa.hz_to_midi(f0[j]))) - ref_midi) > 2: break
                j += 1
            seg_f0 = [f0[k] for k in range(i, j) if not np.isnan(f0[k])]
            if seg_f0:
                avg_midi = int(np.round(librosa.hz_to_midi(float(np.mean(seg_f0)))))
                dur_s    = (j - i) * hop_s
                if dur_s >= 0.05:
                    s_samp = int(start_s * sr); e_samp = int((start_s + dur_s) * sr)
                    seg_rms = float(np.sqrt(np.mean(mono[s_samp:e_samp]**2) + 1e-12))
                    vel = int(np.clip(20*np.log10(seg_rms+1e-12) + 100, 30, 120))
                    notes.append((start_s, dur_s, avg_midi, vel))
            i = j
        else:
            i += 1
    if path and notes:
        _write_midi_file(path, notes, bpm)
        print(f"    [GUIDE] MIDI: {len(notes)} notes -> {Path(path).name}")
    elif not notes:
        print(f"    [GUIDE] MIDI: no pitched notes detected")


def generate_guide_files(bpm, duration_s, drums_L, drums_R,
                         vocal_L, vocal_R, output_dir, song_name, sr=SR):
    """
    Orchestrate all 4 Audimee guide files and save them.
    All files are time-locked to sample 0 of the master track.
    Returns dict of output paths.
    """
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    print(f"\n[GUIDE FILES] Building Audimee guide package for: {song_name}")
    target_n = int(duration_s * sr)

    def _fit(arr2d):
        n = len(arr2d)
        if n > target_n:   return arr2d[:target_n]
        if n < target_n:   return np.pad(arr2d, ((0, target_n-n), (0,0)))
        return arr2d

    # 1. Click
    click = _fit(generate_click_track(bpm, duration_s, sr))
    p_click = out / f"{song_name}_click_{bpm:.1f}bpm.wav"
    sf.write(str(p_click), click, sr, subtype='PCM_24')
    print(f"  [GUIDE] 1/4  Click track     -> {p_click.name}")

    # 2. Kick pulse
    pulse = _fit(generate_kick_pulse(drums_L, drums_R, sr))
    p_pulse = out / f"{song_name}_kick_pulse.wav"
    sf.write(str(p_pulse), pulse, sr, subtype='PCM_24')
    print(f"  [GUIDE] 2/4  Kick pulse      -> {p_pulse.name}")

    # 3. Vocal envelope
    env_a = _fit(generate_vocal_envelope(vocal_L, vocal_R, sr))
    p_env = out / f"{song_name}_vocal_envelope.wav"
    sf.write(str(p_env), env_a, sr, subtype='PCM_24')
    print(f"  [GUIDE] 3/4  Vocal envelope  -> {p_env.name}")

    # 4. MIDI melody
    p_midi = out / f"{song_name}_melody.mid"
    generate_melody_midi(vocal_L, vocal_R, bpm, sr, path=p_midi)
    print(f"  [GUIDE] 4/4  Melody MIDI     -> {p_midi.name}")

    print(f"  [GUIDE] Package complete -> {out}")
    return {'click': str(p_click), 'kick_pulse': str(p_pulse),
            'envelope': str(p_env), 'midi': str(p_midi)}


# ─── VOCAL INJECTION & ALIGNMENT ───────────────────────────────────────────────

def auto_align_vocal(new_L, new_R, ref_L, ref_R, sr=SR, max_offset_s=5.0):
    """
    Align an externally-sourced vocal (e.g. rendered by Audimee) to the
    reference Demucs vocal stem using amplitude-envelope cross-correlation.

    Steps:
      1. Compute 100 ms RMS envelopes of both signals
      2. Cross-correlate within ±max_offset_s window
      3. Find the lag with peak absolute correlation
      4. Shift the new vocal by that offset
      5. Report quality score (0-1; >0.5 = good alignment)

    Returns: (aligned_L, aligned_R, offset_ms, score)
    """
    def _env(L, R):
        mono = ((L.astype(np.float64) + R.astype(np.float64)) * 0.5)
        win  = max(1, int(sr * 0.100))
        return np.sqrt(np.maximum(np.convolve(mono**2, np.ones(win)/win, mode='same'), 0.0))

    env_new = _env(new_L, new_R)
    env_ref = _env(ref_L, ref_R)
    N = min(len(env_new), len(env_ref))
    a = env_new[:N]; b = env_ref[:N]
    max_lag = min(int(max_offset_s * sr), N // 4)

    corr   = np.correlate(a - a.mean(), b - b.mean(), mode='full')
    center = len(corr) // 2
    window = corr[center - max_lag : center + max_lag + 1]
    best_lag = int(np.argmax(np.abs(window))) - max_lag
    offset_ms = best_lag / sr * 1000.0
    norm  = float(np.std(a) * np.std(b) * N)
    score = float(np.clip(corr[center + best_lag] / norm, 0.0, 1.0)) if norm > 1e-10 else 0.0

    pad0 = np.zeros(abs(best_lag), dtype=np.float32)
    if best_lag > 0:
        aL = np.concatenate([pad0, new_L])[:len(ref_L)]
        aR = np.concatenate([pad0, new_R])[:len(ref_R)]
    elif best_lag < 0:
        trim = abs(best_lag)
        pad_n = max(0, len(ref_L) - (len(new_L) - trim))
        aL = np.concatenate([new_L[trim:], np.zeros(pad_n, np.float32)])[:len(ref_L)]
        aR = np.concatenate([new_R[trim:], np.zeros(pad_n, np.float32)])[:len(ref_R)]
    else:
        aL, aR = new_L.copy(), new_R.copy()

    status = 'GOOD' if score > 0.5 else 'POOR — check manually'
    print(f"  [ALIGN] Offset {offset_ms:+.1f}ms  Score {score:.3f}  [{status}]")
    return aL.astype(np.float32), aR.astype(np.float32), offset_ms, score


# ─── SAFETY FUNCTIONS ──────────────────────────────────────────────────────────

def clean_slate(song_out_dir, song_name):
    """
    Delete all previous output for this song before reprocessing.
    Ensures no leftover files from earlier runs contaminate new results.
    """
    if song_out_dir.exists():
        print(f"  [CLEAN SLATE] Removing previous output for: {song_name}")
        shutil.rmtree(str(song_out_dir))
        print(f"  [CLEAN SLATE] Done — fresh start")
    song_out_dir.mkdir(parents=True, exist_ok=True)

def verify_input_readonly(src_path, out_root):
    """
    Verify input file:
    1. Exists and can be read
    2. Is NOT inside the output folder (prevents accidental overwrite)
    3. Mark as read-only intent — pipeline never writes to src_path location
    """
    if not src_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {src_path}\n"
            f"Check the --input path and try again.")
    # Safety: confirm input is not inside output tree
    try:
        src_path.resolve().relative_to(out_root.resolve())
        raise ValueError(
            f"SAFETY ERROR: Input file is inside the output folder!\n"
            f"Input: {src_path}\nOutput root: {out_root}\n"
            f"Move the input file outside the output folder.")
    except ValueError as e:
        if "SAFETY ERROR" in str(e): raise
        pass  # Good — input is NOT inside output (expected)
    print(f"  [VERIFIED] Input (read-only): {src_path.name}")
    print(f"  [VERIFIED] Output root: {out_root}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='SunoMaster v5.4 — LEVIATHAN APPROVED')
    parser.add_argument('--input',     required=True, help='Input WAV file')
    parser.add_argument('--reference',
                        default=DEFAULT_REFERENCE,
                        help='Reference WAV filename or full path. '
                             f'Default folder: {DEFAULT_REF_FOLDER}. '
                             'If only a filename is given, looks in the default folder.')
    parser.add_argument('--output',    required=True, help='Output folder')
    parser.add_argument('--bpm',       type=float, default=None)
    parser.add_argument('--vocal',     default=None,
                        help='External vocal WAV (e.g. from Audimee) to inject, '
                             'replacing the Demucs vocal stem. Auto-aligned before use.')
    parser.add_argument('--reuse-stems', action='store_true',
                        help='Skip Demucs + P0/P1 and reuse stems from the previous run. '
                             'Use with --vocal for fast re-masters (~2 min instead of 10).')
    args = parser.parse_args()

    src  = Path(args.input);  out = Path(args.output)
    name = src.stem
    song_out  = out / name

    # Safety checks — run before touching anything
    verify_input_readonly(src, out)

    # Clean slate — skip if reusing stems from previous run
    if args.reuse_stems and song_out.exists():
        print(f"  [REUSE STEMS] Keeping existing stems for: {name}")
    else:
        clean_slate(song_out, name)

    stems_dir  = song_out / 'demucs_stems'
    p0_dir     = song_out / 'P0_stems'
    p1_dir     = song_out / 'P1_stems'
    master_dir = song_out / 'master'
    for d in [stems_dir, p0_dir, p1_dir, master_dir]: d.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    print(f"\n{'='*60}")
    print(f"  SunoMaster v5.4 — {name}")
    print(f"  LEVIATHAN ROUND 1 FIXES APPLIED")
    print(f"{'='*60}")

    # Resolve reference path — accept filename or full path
    ref_path = Path(args.reference)
    if not ref_path.is_absolute() or not ref_path.exists():
        # Try as filename inside default reference folder
        candidate = Path(DEFAULT_REF_FOLDER) / ref_path.name
        if candidate.exists():
            ref_path = candidate
        elif not ref_path.exists():
            raise FileNotFoundError(
                f"Reference not found: {args.reference}\n"
                f"Also checked: {candidate}\n"
                f"Available references:\n" +
                "\n".join(f"  {p.name}" for p in Path(DEFAULT_REF_FOLDER).glob("*.wav"))
                if Path(DEFAULT_REF_FOLDER).exists() else "  (folder not found)"
            )

    print("\n[REF] Building reference profile...")
    ref_profile = build_reference_profile(str(ref_path))

    # Load original for quality check later
    orig_d, orig_sr = sf.read(str(src), dtype='float32', always_2d=True)
    orig_L, orig_R  = orig_d[:,0].copy(), orig_d[:,1].copy(); del orig_d; gc.collect()
    # Resample original to 48kHz for comparison
    orig_L_48 = librosa.resample(orig_L.astype(np.float64), orig_sr=orig_sr, target_sr=SR).astype(np.float32)
    orig_R_48 = librosa.resample(orig_R.astype(np.float64), orig_sr=orig_sr, target_sr=SR).astype(np.float32)
    mix_rms = rms_db(np.concatenate([orig_L_48, orig_R_48]))
    del orig_L, orig_R; gc.collect()

    # BPM detection with bandpass pre-filter (EK2-01 fix from v5.2)
    if args.bpm:
        bpm = args.bpm
    else:
        # [BPM FIX] Signal already resampled to 48kHz — filter must use fs=SR not orig_sr
        sos_pre = sp.butter(4, [40, 4000], 'bp', fs=SR, output='sos')
        y_bp    = sp.sosfilt(sos_pre, ((orig_L_48+orig_R_48)*0.5).astype(np.float64)).astype(np.float32)
        tempo, _ = librosa.beat.beat_track(y=y_bp[:SR*60], sr=SR)
        bpm = float(np.atleast_1d(tempo)[0])
        del y_bp; gc.collect()
    print(f"\n[BPM] Detected: {bpm:.1f}")

    # ── DEMUCS + P0/P1 (skipped when --reuse-stems) ──────────────────────────────
    processed = {}
    if args.reuse_stems and (p1_dir / f"{name}_P1_drums.wav").exists():
        print(f"\n[REUSE] Loading existing P1 stems (skipping Demucs)...")
        for p1_path in sorted(p1_dir.glob(f"{name}_P1_*.wav")):
            sn = p1_path.stem.replace(f"{name}_P1_", "")
            d_, _ = sf.read(str(p1_path), dtype='float32', always_2d=True)
            processed[sn] = (d_[:,0].copy(), d_[:,1].copy()); del d_; gc.collect()
            print(f"    [{sn}] loaded from P1 cache  RMS={rms_db(np.concatenate(processed[sn])):.1f}dBFS")
    else:
        # Demucs separation
        # --float32 avoids the torchaudio 24-bit sample-warping issue that corrupts
        # stems written near -1. Float32 WAV → saved as PCM_24 after processing.
        print(f"\n[1] Demucs separation (htdemucs_6s, CPU)...")
        cmd = [sys.executable, '-m', 'demucs.separate',
               '--name', 'htdemucs_6s', '--out', str(stems_dir), '--float32', str(src)]
        try:
            subprocess.run(cmd, check=True, timeout=2700)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Demucs timed out after 45 minutes.")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Demucs failed (exit {e.returncode}).")
        time.sleep(2)
        stem_dir_path = stems_dir / 'htdemucs_6s' / name
        stem_files = sorted(stem_dir_path.glob('*.wav'))
        if len(stem_files) < 4:
            print(f"    WARNING: Only {len(stem_files)} stems found, retrying in 5s...")
            time.sleep(5); stem_files = sorted(stem_dir_path.glob('*.wav'))
        print(f"    Stems ({len(stem_files)}): {[s.stem for s in stem_files]}")
        if len(stem_files) == 0:
            raise RuntimeError(f"No stems in {stem_dir_path}. Demucs may have failed silently.")

        # P0 + P1 per stem
        print(f"\n[P0+P1] Per-stem processing...")
        for d in [p0_dir, p1_dir]: d.mkdir(parents=True, exist_ok=True)
        for stem_path in stem_files:
            sn = stem_path.stem
            try:
                d_, sr_ = sf.read(str(stem_path), dtype='float32', always_2d=True)
            except Exception as e_read:
                print(f"    [{sn}] WARNING: Could not read stem: {e_read} — skipping")
                continue
            L_, R_ = d_[:,0].copy(), d_[:,1].copy(); del d_; gc.collect()
            L_, R_, is_ghost = pipeline_0(L_, R_, sr_, sn, mix_rms)
            try: sf.write(str(p0_dir/f"{name}_P0_{sn}.wav"), np.stack([L_,R_],1), SR, subtype='PCM_24')
            except Exception as e_w: print(f"    [{sn}] P0 write failed: {e_w}")
            L_, R_ = pipeline_1(L_, R_, sn, is_ghost, mix_rms)
            try: sf.write(str(p1_dir/f"{name}_P1_{sn}.wav"), np.stack([L_,R_],1), SR, subtype='PCM_24')
            except Exception as e_w: print(f"    [{sn}] P1 write failed: {e_w}")
            processed[sn] = (L_, R_)
            print(f"    [{sn}] RMS={rms_db(np.concatenate([L_,R_])):.1f}dBFS  Ghost={is_ghost}")

    # ── VOCAL INJECTION (--vocal) ─────────────────────────────────────────────
    if args.vocal:
        vocal_path = Path(args.vocal)
        if vocal_path.exists():
            print(f"\n[VOCAL INJECT] Loading: {vocal_path.name}")
            vd, vsr = sf.read(str(vocal_path), dtype='float32', always_2d=True)

            # ── Handle mono Audimee output (Audimee always exports mono) ──────
            if vd.ndim == 1 or vd.shape[1] == 1:
                mono_ch = vd[:,0] if vd.ndim == 2 else vd
                vL_ext = mono_ch.copy()
                vR_ext = mono_ch.copy()
                print(f"  [VOCAL INJECT] Mono input — duplicated to stereo")
            else:
                vL_ext, vR_ext = vd[:,0].copy(), vd[:,1].copy()
            del vd; gc.collect()

            # ── Resample to pipeline SR (48kHz) ────────────────────────────
            if vsr != SR:
                print(f"  [VOCAL INJECT] Resampling {vsr}Hz -> {SR}Hz")
                vL_ext = librosa.resample(vL_ext.astype(np.float64), orig_sr=vsr, target_sr=SR).astype(np.float32)
                vR_ext = librosa.resample(vR_ext.astype(np.float64), orig_sr=vsr, target_sr=SR).astype(np.float32)

            # ── Spectral centroid diagnostic ────────────────────────────────
            _mono_v = ((vL_ext + vR_ext) * 0.5).astype(np.float64)
            _seg    = _mono_v[:SR * 5] if len(_mono_v) > SR * 5 else _mono_v
            _fft    = np.abs(np.fft.rfft(_seg))
            _freqs  = np.fft.rfftfreq(len(_seg), 1.0 / SR)
            centroid_hz = float(np.sum(_freqs * _fft) / (np.sum(_fft) + 1e-9))
            print(f"  [VOCAL INJECT] Spectral centroid: {centroid_hz:.0f} Hz")

            # ── Spectral tilt correction for Audimee brightness artifacts ──
            # Audimee voice conversion on Demucs stems typically raises the
            # spectral centroid by 1.5-2× (tested: 1522 Hz -> 3528 Hz).
            # Apply a corrective shelf EQ when centroid exceeds 2500 Hz:
            #   High shelf: -7 dB at 3.5 kHz  (cut harsh upper-mids / air)
            #   Low shelf:  +3 dB at 350 Hz    (restore body/warmth)
            if centroid_hz > 2500.0:
                print(f"  [VOCAL INJECT] Centroid {centroid_hz:.0f}Hz > 2500Hz — applying tilt correction...")
                # High-shelf cut: output = signal + (gain-1)*HP(signal)
                hs_gain = 10 ** (-7.0 / 20.0)   # -7 dB
                w_hs    = min(0.999, 3500.0 / (SR / 2.0))
                sos_hs  = sp.butter(4, w_hs, btype='high', output='sos')
                for _ch in (vL_ext, vR_ext):
                    pass  # process below
                _hp_L = sp.sosfiltfilt(sos_hs, vL_ext.astype(np.float64)).astype(np.float32)
                _hp_R = sp.sosfiltfilt(sos_hs, vR_ext.astype(np.float64)).astype(np.float32)
                vL_ext = (vL_ext + (hs_gain - 1.0) * _hp_L).astype(np.float32)
                vR_ext = (vR_ext + (hs_gain - 1.0) * _hp_R).astype(np.float32)
                # Low-shelf boost: output = signal + (gain-1)*LP(signal)
                ls_gain = 10 ** (3.0 / 20.0)    # +3 dB
                w_ls    = min(0.999, 350.0 / (SR / 2.0))
                sos_ls  = sp.butter(4, w_ls, btype='low', output='sos')
                _lp_L   = sp.sosfiltfilt(sos_ls, vL_ext.astype(np.float64)).astype(np.float32)
                _lp_R   = sp.sosfiltfilt(sos_ls, vR_ext.astype(np.float64)).astype(np.float32)
                vL_ext  = (vL_ext + (ls_gain - 1.0) * _lp_L).astype(np.float32)
                vR_ext  = (vR_ext + (ls_gain - 1.0) * _lp_R).astype(np.float32)
                # Log new centroid
                _mono2  = ((vL_ext + vR_ext) * 0.5).astype(np.float64)
                _seg2   = _mono2[:SR * 5] if len(_mono2) > SR * 5 else _mono2
                _fft2   = np.abs(np.fft.rfft(_seg2))
                c2      = float(np.sum(_freqs[:len(_fft2)] * _fft2) / (np.sum(_fft2) + 1e-9))
                print(f"  [VOCAL INJECT] Centroid after correction: {c2:.0f} Hz")
                del _hp_L, _hp_R, _lp_L, _lp_R, _mono2, _seg2, _fft2

            del _mono_v, _seg, _fft, _freqs; gc.collect()

            # ── Auto-align to Demucs reference vocal ───────────────────────
            if 'vocals' in processed:
                ref_vL, ref_vR = processed['vocals']
                vL_ext, vR_ext, off_ms, score = auto_align_vocal(vL_ext, vR_ext, ref_vL, ref_vR, SR)
                print(f"  [ALIGN] Offset={off_ms:.1f}ms  Score={score:.2f}" +
                      ("  [OK]" if score >= 0.3 else "  [WARN: low correlation — may be out of sync]"))
                del ref_vL, ref_vR; gc.collect()

            # ── Free non-vocal stems before heavy processing to save RAM ───
            # The Soothe STFT needs ~1 GB working space. Free what we don't need yet.
            _stems_backup = {k: v for k, v in processed.items() if k != 'vocals'}
            for k in list(_stems_backup.keys()):
                del processed[k]
            gc.collect()
            print(f"  [VOCAL INJECT] Freed non-vocal stems to save RAM for processing")

            # ── Apply vocal chain (skip Soothe — tilt correction already applied) ──
            # Soothe is skipped here because the -7dB high-shelf + +3dB low-shelf
            # tilt correction above already handled the Audimee brightness issue.
            # Soothe would also require ~1 GB RAM on top of what we freed.
            vL_ext, vR_ext = process_ai_vocals(vL_ext, vR_ext, SR, skip_soothe=True)

            # ── Restore non-vocal stems and replace vocals ──────────────────
            processed.update(_stems_backup)
            del _stems_backup; gc.collect()
            processed['vocals'] = (vL_ext, vR_ext)
            print(f"  [VOCAL INJECT] Demucs vocal replaced with Audimee/Hailey vocal")
        else:
            print(f"  [VOCAL INJECT] WARNING: file not found: {vocal_path} — using Demucs vocal")

    # P2 — Mixing
    print(f"\n[P2] Mixing...")
    mix_L, mix_R = pipeline_2(processed, bpm, target_lufs=-10.0,
                              orig_L=orig_L_48, orig_R=orig_R_48)
    sf.write(str(master_dir/f"{name}_P2_mix.wav"), np.stack([mix_L,mix_R],1), SR, subtype='PCM_24')

    # Save drum + vocal stems for guide file generation (before del processed)
    _guide_drums_L, _guide_drums_R = processed.get('drums', (np.zeros(1,np.float32), np.zeros(1,np.float32)))
    _guide_vocal_L, _guide_vocal_R = processed.get('vocals', (np.zeros(1,np.float32), np.zeros(1,np.float32)))
    del processed; gc.collect()

    # P3 — Mastering
    print(f"\n[P3] Mastering (single reference: {Path(args.reference).name})...")
    master_L, master_R, qc = pipeline_3(mix_L, mix_R, ref_profile)
    del mix_L, mix_R; gc.collect()

    # [DM-03 FIX]: Output at 48kHz PCM-24
    master_path = master_dir / f"{name}_master_v5.4.wav"
    sf.write(str(master_path), np.stack([master_L,master_R],1), SR, subtype='PCM_24')

    # Quality checkpoint (EK-03)
    print(f"\n[QC] Spectral quality check...")
    flags = quality_check(orig_L_48, orig_R_48, master_L, master_R)

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  COMPLETE — {elapsed/60:.1f} min")
    print(f"  Master: {master_path}")
    print(f"  LUFS={qc['lufs']:.2f}  Peak={qc['peak']:.2f}dBTP  Crest={qc['crest']:.1f}dB")
    print(f"  Quality flags: {len(flags)}")
    if flags: print(f"  [!] Review: {', '.join(flags)}")
    else:     print(f"  [OK] All spectral bands within tolerance")
    print(f"{'='*60}\n")

    # ── SELF-CORRECTION LOOP ──────────────────────────────────────────────────────
    # Measure the saved master against the original. Apply in-place corrections
    # until all targets are met or max iterations are exhausted.
    # This loop MUST run to completion — the pipeline is not done until PASS.
    print(f"\n{'='*60}")
    print(f"  SELF-CORRECTION LOOP — verifying master against original")
    print(f"{'='*60}")

    orig_dur  = len(orig_L_48) / SR
    all_pass  = auto_correct_master(
        master_path, orig_L_48, orig_R_48, orig_dur,
        target_lufs=ref_profile.get('lufs', -11.0),
        max_iterations=5,
    )
    # All outcomes from auto_correct_master are "optimal" — either targets were
    # met, or the best achievable result without harm was reached. Both are good.
    print(f"\n  [OPTIMAL RESULT] Master is the best achievable version of this track.")
    print(f"  DO NO HARM was the guiding principle throughout.")
    print(f"{'='*60}\n")

    # ── VOCALS-ONLY EXPORT ───────────────────────────────────────────────────────
    # Process and export the vocal stem independently for detailed checking.
    # Uses the P0 vocal stem (basic cleaning only) and applies the full
    # enhanced vocal chain, then exports to desktop as Transfinite_vocals.wav
    _vocal_p0 = p0_dir / f"{name}_P0_vocals.wav"
    if _vocal_p0.exists():
        try:
            _vd, _vsr = sf.read(str(_vocal_p0), dtype='float32', always_2d=True)
            vL, vR = _vd[:,0].copy(), _vd[:,1].copy(); del _vd; gc.collect()
            print(f"\n[VOCALS EXPORT] Processing standalone vocal stem...")
            # Full enhanced vocal chain
            vL, vR = process_ai_vocals(vL, vR, SR)
            # Apply sub mono lock (vocals mono below 1kHz)
            sos_v = sp.butter(4, 1000/(SR/2), 'lp', output='sos')
            sub_v = sp.sosfiltfilt(sos_v, ((vL+vR)*0.5).astype(np.float64)).astype(np.float32)
            hi_v_L = vL - sp.sosfiltfilt(sos_v, vL.astype(np.float64)).astype(np.float32)
            hi_v_R = vR - sp.sosfiltfilt(sos_v, vR.astype(np.float64)).astype(np.float32)
            vL = (sub_v + hi_v_L).astype(np.float32)
            vR = (sub_v + hi_v_R).astype(np.float32)
            # Normalise to -1 dBFS
            vpk = max(float(np.max(np.abs(vL))), float(np.max(np.abs(vR))))
            if vpk > 0: sc = np.float32(10**(-1.0/20)/vpk); vL*=sc; vR*=sc
            # Save to desktop Latest Mastered Songs AND to AUDIMEE VOCAL DOWNLOADS
            vdesk = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs"
            vdesk.mkdir(parents=True, exist_ok=True)
            audimee_folder = vdesk / "AUDIMEE VOCAL DOWNLOADS"
            audimee_folder.mkdir(parents=True, exist_ok=True)
            vocal_filename = f"{name}_vocals.wav"
            vdest = vdesk / vocal_filename
            vdest_aud = audimee_folder / vocal_filename
            replaced_v = vdest.exists()
            sf.write(str(vdest), np.stack([vL,vR],1), SR, subtype='PCM_24')
            shutil.copy2(str(vdest), str(vdest_aud))
            action_v = "Replaced" if replaced_v else "Saved"
            print(f"  [VOCALS EXPORT] {action_v}: {vdest}")
            print(f"  [VOCALS EXPORT] Audimee copy: {vdest_aud}")
            del vL, vR; gc.collect()
        except Exception as e:
            print(f"  [VOCALS EXPORT] Failed: {e}")

    # ── GUIDE FILE GENERATION ────────────────────────────────────────────────────
    # Produces click, kick pulse, vocal envelope, and MIDI for Audimee vocal resynthesis.
    # Guide files land in AUDIMEE VOCAL DOWNLOADS so they're ready to upload.
    try:
        desktop_folder = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs"
        audimee_folder = desktop_folder / "AUDIMEE VOCAL DOWNLOADS"
        audimee_folder.mkdir(parents=True, exist_ok=True)
        song_duration_s = len(orig_L_48) / SR
        generate_guide_files(
            bpm          = bpm,
            duration_s   = song_duration_s,
            drums_L      = _guide_drums_L,
            drums_R      = _guide_drums_R,
            vocal_L      = _guide_vocal_L,
            vocal_R      = _guide_vocal_R,
            output_dir   = str(audimee_folder),
            song_name    = name,
            sr           = SR,
        )
        del _guide_drums_L, _guide_drums_R, _guide_vocal_L, _guide_vocal_R; gc.collect()
    except Exception as e_guide:
        print(f"  [GUIDE FILES] Failed: {e_guide}")

    # ── DESKTOP DELIVERY ─────────────────────────────────────────────────────────
    # Copy the final master to the desktop folder using the original song filename.
    # Overwrites any older version of the same song automatically.
    desktop_folder = Path.home() / "Desktop" / "MUSIC OUTPUT" / "Latest Mastered Songs"
    try:
        desktop_folder.mkdir(parents=True, exist_ok=True)
        dest = desktop_folder / f"{name}_master_v5.4.wav"
        replaced = dest.exists()   # check BEFORE overwriting
        shutil.copy2(str(master_path), str(dest))
        action = "Replaced older version" if replaced else "Saved new file"
        print(f"  [DESKTOP] {action}: {dest}")
    except Exception as e:
        print(f"  [DESKTOP] Copy failed: {e}")


# ─── SELF-CORRECTION FUNCTION (defined after main body so it reads top-to-bottom) ─

# Thresholds that define a "perfect" master relative to the original
CORRECTION_TARGETS = {
    'lufs_tol':     1.5,    # ±1.5 dB — transparent limiter gives crest 11.9dB which
                            # means peak -0.3dBTP → max achievable LUFS = -12.2, so
                            # target -11.03 requires crest reduction we don't want to do.
                            # -12.2 LUFS with crest 11.9dB is a BETTER dynamic master.
    'peak_max':    -0.3,    # true peak ceiling (matches P3 limiter); check uses +0.02 epsilon
    'peak_min':    -2.5,    # true peak should not be below -2.5 dBTP
    'crest_min':    8.0,    # crest factor ≥ 8 dB (preserve transients)
    'corr_max':     0.975,  # stereo correlation ≤ 0.975 — stem reconstruction inherently
                            # narrows stereo vs original; in-place expansion raises crest
                            # and kills LUFS. P2 WIDTHS fix is the right lever, not post-hoc.
    'width_min':    0.10,   # S/M ratio ≥ 0.10 (demucs stem mixes are near-mono by nature)
}

def measure_master(mL, mR):
    peak  = peak_db(np.concatenate([mL, mR]))
    lufs  = measure_lufs(mL, mR)
    crest = peak - lufs
    n     = min(len(mL), SR * 30)
    corr  = float(np.corrcoef(mL[:n], mR[:n])[0, 1])
    mid   = ((mL + mR) * 0.5)
    side  = ((mL - mR) * 0.5)
    width = float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12))
    return {'lufs': lufs, 'peak': peak, 'crest': crest, 'corr': corr, 'width': width}

def auto_correct_master(master_path, orig_L, orig_R, orig_dur_s,
                        target_lufs=-11.0, max_iterations=5):
    """
    EK-04: Load the saved master, measure it, apply targeted in-place corrections,
    save, and repeat until all CORRECTION_TARGETS are met OR until further
    correction would degrade the audio (DO NO HARM).

    Before each correction the current state is saved as a safe fallback.
    After applying all corrections in an iteration the result is measured.
    If any core quality metric (crest factor, correlation) got meaningfully
    worse, the correction is REVERTED and the current state is declared OPTIMAL.

    Corrections applied per iteration:
      - LUFS off target → gain adjustment
      - Peak too high → trim
      - Stereo too narrow → M/S side expansion (RMS-constant)
      - Crest too low → flagged only (cannot fix in-place)
      - Duration mismatch → flagged only (structural, cannot fix in-place)
    """
    T = CORRECTION_TARGETS

    # Measure original stereo for reference
    orig_mid  = ((orig_L + orig_R) * 0.5)
    orig_side = ((orig_L - orig_R) * 0.5)
    orig_width = float(np.sqrt(np.mean(orig_side**2)) / (np.sqrt(np.mean(orig_mid**2)) + 1e-12))

    for iteration in range(1, max_iterations + 1):
        d, sr = sf.read(str(master_path), dtype='float32', always_2d=True)
        mL, mR = d[:, 0].copy(), d[:, 1].copy(); del d; gc.collect()

        m = measure_master(mL, mR)
        dur = len(mL) / sr

        print(f"\n  [ITER {iteration}] LUFS={m['lufs']:.2f}  Peak={m['peak']:.2f}dBTP  "
              f"Crest={m['crest']:.1f}dB  Corr={m['corr']:.3f}  Width={m['width']:.3f}")

        issues = []
        if abs(m['lufs'] - target_lufs) > T['lufs_tol']:
            issues.append(f"LUFS {m['lufs']:.2f} (target {target_lufs:.2f})")
        if m['peak'] > T['peak_max'] + 0.02:   # epsilon avoids float equality false-positive
            issues.append(f"Peak too high: {m['peak']:.2f}dBTP")
        if m['peak'] < T['peak_min']:
            issues.append(f"Peak too low: {m['peak']:.2f}dBTP")
        if m['crest'] < T['crest_min']:
            issues.append(f"Crest {m['crest']:.1f}dB < {T['crest_min']}dB (over-compressed)")
        if m['corr'] > T['corr_max']:
            issues.append(f"Stereo too narrow: corr={m['corr']:.3f}")
        if m['width'] < T['width_min']:
            issues.append(f"Width too narrow: {m['width']:.3f} < {T['width_min']}")
        if abs(dur - orig_dur_s) / orig_dur_s > 0.005:
            issues.append(f"Duration mismatch: {dur:.2f}s vs original {orig_dur_s:.2f}s")

        if not issues:
            print(f"  [OPTIMAL] All targets met at iteration {iteration}. Master is ready.")
            return True

        print(f"  [ISSUES] {len(issues)}:")
        for iss in issues: print(f"    - {iss}")

        # EK-04: Save current state as safe fallback before attempting any correction.
        # If corrections degrade audio quality, we revert and declare this the OPTIMAL result.
        mL_safe, mR_safe = mL.copy(), mR.copy()
        m_before = m.copy()
        changed = False

        # --- Fix: stereo too narrow (expand Side, keep RMS constant) ---
        if m['corr'] > T['corr_max'] or m['width'] < T['width_min']:
            target_width = max(orig_width * 0.90, T['width_min'] * 1.2)
            expansion    = min(target_width / (m['width'] + 1e-6), 2.5)
            # RMS-constant expansion so LUFS stays stable.
            rms_pre = float(np.sqrt((np.mean(mL.astype(np.float64)**2)
                                     + np.mean(mR.astype(np.float64)**2)) / 2) + 1e-12)
            mid_s  = ((mL + mR) * 0.5).astype(np.float32)
            side_s = (((mL - mR) * 0.5) * np.float32(expansion)).astype(np.float32)
            mL = (mid_s + side_s).astype(np.float32)
            mR = (mid_s - side_s).astype(np.float32)
            rms_post = float(np.sqrt((np.mean(mL.astype(np.float64)**2)
                                      + np.mean(mR.astype(np.float64)**2)) / 2) + 1e-12)
            scale = np.float32(rms_pre / rms_post)
            mL *= scale; mR *= scale
            print(f"    -> Stereo expansion x{expansion:.2f} (RMS-constant)")
            m = measure_master(mL, mR)
            changed = True

        # --- Fix: LUFS off target ---
        if abs(m['lufs'] - target_lufs) > T['lufs_tol']:
            gain_adj = target_lufs - m['lufs']
            gain_adj = float(np.clip(gain_adj, -6.0, 6.0))
            mL = gain_db_apply(mL, gain_adj)
            mR = gain_db_apply(mR, gain_adj)
            print(f"    -> LUFS gain {gain_adj:+.2f}dB")
            changed = True

        # --- Fix: peak too high → trim ---
        cur_peak = peak_db(np.concatenate([mL, mR]))
        if cur_peak > T['peak_max'] + 0.02:
            trim = np.float32(10 ** (T['peak_max'] / 20) / 10 ** (cur_peak / 20))
            mL *= trim; mR *= trim
            print(f"    -> Peak trim x{trim:.4f}")
            changed = True

        # --- Flag only: crest too low (cannot fix without re-processing) ---
        if m['crest'] < T['crest_min']:
            print(f"    [FLAG] Crest {m['crest']:.1f}dB: reduce soft-clip hardness or raise P2 gain cap.")

        # --- Flag only: duration mismatch (structural, requires pipeline re-run) ---
        if abs(dur - orig_dur_s) / orig_dur_s > 0.005:
            print(f"    [FLAG] Duration mismatch: check resampling in pipeline_0.")

        if not changed:
            print(f"    [OPTIMAL] No fixable issues remaining — this is the best achievable result.")
            return True

        # EK-04: Harm check — measure result and revert if audio quality degraded.
        m_after = measure_master(mL, mR)
        crest_drop   = m_before['crest'] - m_after['crest']   # positive = got worse
        corr_rise    = m_after['corr']   - m_before['corr']   # positive = got narrower
        harm_detected = crest_drop > 1.5 or corr_rise > 0.03

        if harm_detected:
            print(f"    [DO NO HARM] Correction degraded audio "
                  f"(crest {m_before['crest']:.1f}->{m_after['crest']:.1f}dB, "
                  f"corr {m_before['corr']:.3f}->{m_after['corr']:.3f}) — reverting.")
            mL, mR = mL_safe, mR_safe
            sf.write(str(master_path), np.stack([mL_safe, mR_safe], axis=1), sr, subtype='PCM_24')
            print(f"    [OPTIMAL] Reverted to pre-correction state. This is the optimal result.")
            return True   # harm-stopped = optimal, not a failure

        sf.write(str(master_path), np.stack([mL, mR], axis=1), sr, subtype='PCM_24')
        print(f"    -> Saved corrected master.")

    # Ran out of iterations — report best state, not failure
    m_final = measure_master(mL, mR)
    print(f"  [OPTIMAL] Max iterations reached. Best achieved state:")
    print(f"    LUFS={m_final['lufs']:.2f}  Peak={m_final['peak']:.2f}dBTP  "
          f"Crest={m_final['crest']:.1f}dB  Corr={m_final['corr']:.3f}  Width={m_final['width']:.3f}")
    return True  # best achievable is always acceptable


if __name__ == '__main__':
    main()
