import numpy as np, soundfile as sf, librosa, warnings
from scipy import signal
from scipy.signal import butter, sosfilt
warnings.filterwarnings('ignore')

ORIG = r"C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav"
MAST = r"E:\SunoMaster\output\Transfinite (Agent WALL) Master\master\Transfinite (Agent WALL) Master_master_v5.4.wav"
REF  = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"

def load(p):
    d, sr = sf.read(p, always_2d=True, dtype='float32')
    return d[:,0], d[:,1], sr

def lufs_bs1770(L, R, sr):
    BS = np.array([1.53512485958697,-2.69169618940638,1.19839281085285])
    AS = np.array([1.0,-1.69065929318241,0.73248077421585])
    BH = np.array([1.0,-2.0,1.0]); AH = np.array([1.0,-1.99004745483398,0.99007225036603])
    kL = signal.lfilter(BH, AH, signal.lfilter(BS, AS, L.astype(np.float64)))
    kR = signal.lfilter(BH, AH, signal.lfilter(BS, AS, R.astype(np.float64)))
    bl = int(0.4*sr); hop = int(0.1*sr); n = (len(kL)-bl)//hop
    if n < 1: return -70.0
    ms = np.array([0.5*(np.mean(kL[i*hop:i*hop+bl]**2)+np.mean(kR[i*hop:i*hop+bl]**2)) for i in range(n)])
    g1 = ms[ms > 1e-7]
    if not len(g1): return -70.0
    g2 = ms[ms > np.mean(g1)*10**(-10/10)]
    return float(-0.691+10*np.log10(np.mean(g2))) if len(g2) else -70.0

def peak_dbtp(L, R):
    return float(20*np.log10(max(np.max(np.abs(L)), np.max(np.abs(R)))+1e-12))

def rms_db(L, R):
    return float(10*np.log10((np.mean(L.astype(np.float64)**2)+np.mean(R.astype(np.float64)**2))/2+1e-12))

def crest(L, R, sr):
    return peak_dbtp(L, R) - lufs_bs1770(L, R, sr)

def corr_broad(L, R):
    n = min(len(L), len(R))
    lz = L[:n].astype(np.float64) - np.mean(L[:n])
    rz = R[:n].astype(np.float64) - np.mean(R[:n])
    d = np.sqrt(np.sum(lz**2) * np.sum(rz**2))
    return float(np.sum(lz*rz)/d) if d > 0 else 0.0

def width_sm(L, R):
    m = (L+R)/2; s = (L-R)/2
    return float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-12))

def dynamic_range_lra(L, R, sr):
    mono = (L.astype(np.float64)+R.astype(np.float64))/2
    bl = int(3*sr); hop = int(sr)
    n = (len(mono)-bl)//hop
    if n < 4: return 0.0
    lvl = np.array([10*np.log10(np.mean(mono[i*hop:i*hop+bl]**2)+1e-12) for i in range(n)])
    lvl = lvl[lvl > -70]
    if len(lvl) < 4: return 0.0
    return float(np.percentile(lvl, 95) - np.percentile(lvl, 10))

def band_db(L, R, lo, hi, sr):
    hi = min(hi, sr/2*0.99)
    sos = butter(4, [lo/(sr/2), hi/(sr/2)], btype='band', output='sos')
    bl = sosfilt(sos, L.astype(np.float64))
    br = sosfilt(sos, R.astype(np.float64))
    return 10*np.log10((np.mean(bl**2)+np.mean(br**2))/2+1e-12)

def spectral_slope(L, R, sr):
    mono = ((L+R)/2).astype(np.float32)
    D = librosa.stft(mono.astype(np.float64))
    mag = np.abs(D)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=D.shape[0]*2-2)
    mm = np.mean(mag, axis=1)
    mm_db = 20*np.log10(mm+1e-9)
    mask = (freqs > 100) & (freqs < 10000)
    if mask.sum() < 2: return 0.0
    log_f = np.log2(freqs[mask])
    return float(np.polyfit(log_f, mm_db[mask], 1)[0])

def detect_glitches(L, R, sr):
    mono = np.abs((L.astype(np.float64)+R.astype(np.float64))/2)
    hop = int(sr*0.01)
    n = len(mono)//hop
    if n < 4: return 0, 0.0
    frames = np.array([np.max(mono[i*hop:(i+1)*hop]) for i in range(n)])
    med = np.median(frames)
    spikes = np.sum(frames > med*10)
    silences = np.sum(frames < med*0.01)
    return int(spikes+silences), float(np.max(frames)/(med+1e-12))

def pink_noise_dev(L, R, sr):
    mono = ((L+R)/2).astype(np.float64)
    centres = [80, 160, 320, 640, 1280, 2560, 5120, 10240]
    energies = []
    for fc in centres:
        lo = fc/2**0.5
        hi = min(fc*2**0.5, sr/2*0.99)
        sos = butter(4, [lo/(sr/2), hi/(sr/2)], 'band', output='sos')
        b = sosfilt(sos, mono)
        energies.append(float(10*np.log10(np.mean(b**2)+1e-12)))
    ref = [energies[0]+i*(-3.0) for i in range(len(energies))]
    devs = [e-r for e, r in zip(energies, ref)]
    return centres, energies, ref, devs

# Load
oL, oR, osr = load(ORIG)
mL, mR, msr = load(MAST)
rL, rR, rsr = load(REF)

SR = 48000
oL2 = librosa.resample(oL.astype(np.float64), orig_sr=osr, target_sr=SR).astype(np.float32)
oR2 = librosa.resample(oR.astype(np.float64), orig_sr=osr, target_sr=SR).astype(np.float32)
rL2 = librosa.resample(rL.astype(np.float64), orig_sr=rsr, target_sr=SR).astype(np.float32)
rR2 = librosa.resample(rR.astype(np.float64), orig_sr=rsr, target_sr=SR).astype(np.float32)

sep = "=" * 72
print(sep)
print("  THREE-WAY DEEP ANALYSIS: ORIGINAL / MASTER v5.4 / REFERENCE (Guy J)")
print(sep)

print(f"\n  {'METRIC':<30} {'ORIGINAL':>12}  {'MASTER v5.4':>12}  {'REFERENCE':>12}")
print(f"  {'-'*70}")

ol = lufs_bs1770(oL2, oR2, SR); ml = lufs_bs1770(mL, mR, msr); rl = lufs_bs1770(rL2, rR2, SR)
print(f"  {'Integrated LUFS':<30} {ol:>+12.2f}  {ml:>+12.2f}  {rl:>+12.2f}")

op = peak_dbtp(oL2, oR2); mp = peak_dbtp(mL, mR); rp = peak_dbtp(rL2, rR2)
print(f"  {'True Peak (dBTP)':<30} {op:>+12.2f}  {mp:>+12.2f}  {rp:>+12.2f}")

orms = rms_db(oL2, oR2); mrms = rms_db(mL, mR); rrms = rms_db(rL2, rR2)
print(f"  {'RMS Level (dB)':<30} {orms:>+12.2f}  {mrms:>+12.2f}  {rrms:>+12.2f}")

ocr = crest(oL2, oR2, SR); mcr = crest(mL, mR, msr); rcr = crest(rL2, rR2, SR)
print(f"  {'Crest Factor (dB)':<30} {ocr:>12.2f}  {mcr:>12.2f}  {rcr:>12.2f}")

olra = dynamic_range_lra(oL2, oR2, SR); mlra = dynamic_range_lra(mL, mR, msr); rlra = dynamic_range_lra(rL2, rR2, SR)
print(f"  {'Dynamic Range LRA (dB)':<30} {olra:>12.2f}  {mlra:>12.2f}  {rlra:>12.2f}")

print(f"\n  {'STEREO':<30} {'ORIGINAL':>12}  {'MASTER v5.4':>12}  {'REFERENCE':>12}")
print(f"  {'-'*70}")
oc2 = corr_broad(oL2, oR2); mc2 = corr_broad(mL, mR); rc2 = corr_broad(rL2, rR2)
print(f"  {'Correlation':<30} {oc2:>12.3f}  {mc2:>12.3f}  {rc2:>12.3f}")
ow = width_sm(oL2, oR2); mw = width_sm(mL, mR); rw = width_sm(rL2, rR2)
print(f"  {'Width (S/M ratio)':<30} {ow:>12.3f}  {mw:>12.3f}  {rw:>12.3f}")

print(f"\n  {'SPECTRAL SLOPE':<30} {'ORIGINAL':>12}  {'MASTER v5.4':>12}  {'REFERENCE':>12}")
print(f"  {'-'*70}")
osl = spectral_slope(oL2, oR2, SR); msl = spectral_slope(mL, mR, msr); rsl = spectral_slope(rL2, rR2, SR)
print(f"  {'Actual slope (dB/oct)':<30} {osl:>12.2f}  {msl:>12.2f}  {rsl:>12.2f}")
print(f"  {'Pink noise target':<30} {'  -3.00':>12}  {'  -3.00':>12}  {'  -3.00':>12}")
print(f"  {'Error from target':<30} {osl+3:>+12.2f}  {msl+3:>+12.2f}  {rsl+3:>+12.2f}")

print(f"\n  {'ARTIFACT CHECK':<30} {'ORIGINAL':>12}  {'MASTER v5.4':>12}  {'REFERENCE':>12}")
print(f"  {'-'*70}")
og, opk2 = detect_glitches(oL2, oR2, SR)
mg, mpk2 = detect_glitches(mL, mR, msr)
rg, rpk2 = detect_glitches(rL2, rR2, SR)
print(f"  {'Anomalous frames':<30} {og:>12d}  {mg:>12d}  {rg:>12d}")
print(f"  {'Max spike ratio':<30} {opk2:>12.1f}x  {mpk2:>12.1f}x  {rpk2:>12.1f}x")

print(f"\n  PINK NOISE COMPLIANCE (deviation from -3dB/oct reference, band by band)")
print(f"  {'Hz':>8}  {'Orig dB':>9}  {'Mast dB':>9}  {'Ref dB':>9}  {'Orig dev':>9}  {'Mast dev':>9}  {'Ref dev':>9}")
print(f"  {'-'*72}")
_, oe, _, od = pink_noise_dev(oL2, oR2, SR)
_, me2, _, md = pink_noise_dev(mL, mR, msr)
_, re2, _, rd = pink_noise_dev(rL2, rR2, SR)
bands_pn = [80, 160, 320, 640, 1280, 2560, 5120, 10240]
for i, hz in enumerate(bands_pn):
    fo = '!' if abs(od[i]) > 3 else ' '
    fm = '!' if abs(md[i]) > 3 else ' '
    fr = '!' if abs(rd[i]) > 3 else ' '
    print(f"  {hz:>6}Hz  {oe[i]:>+9.1f}  {me2[i]:>+9.1f}  {re2[i]:>+9.1f}  "
          f"{od[i]:>+8.1f}{fo}  {md[i]:>+8.1f}{fm}  {rd[i]:>+8.1f}{fr}")

print(f"\n  SPECTRAL BANDS (absolute energy per band)")
print(f"  {'Band':<14}{'Range':>11}  {'Orig':>8}  {'Master':>8}  {'Ref':>8}  {'M-O':>7}  {'M-R':>7}")
print(f"  {'-'*70}")
bands_spec = [
    ("Deep Sub",  "20-60Hz",    20,    60),
    ("Sub Bass",  "60-120Hz",   60,   120),
    ("Kick Body", "120-200Hz",  120,  200),
    ("Low Mid",   "200-500Hz",  200,  500),
    ("Mid Low",   "500-1kHz",   500,  1000),
    ("Mid",       "1-3kHz",     1000, 3000),
    ("Presence",  "3-6kHz",     3000, 6000),
    ("Hi Mid",    "6-10kHz",    6000, 10000),
    ("Air",       "10-16kHz",   10000,16000),
    ("Ultra Air", "16-20kHz",   16000,20000),
]
for nm, rng, lo, hi in bands_spec:
    ob = band_db(oL2, oR2, lo, hi, SR)
    mb_ = band_db(mL, mR, lo, hi, msr)
    rb = band_db(rL2, rR2, lo, hi, SR)
    mo = mb_ - ob; mr_ = mb_ - rb
    fo = '!!' if abs(mo) > 4 else '! ' if abs(mo) > 2 else '  '
    print(f"  {nm:<14}{rng:>11}  {ob:>+8.1f}  {mb_:>+8.1f}  {rb:>+8.1f}  {mo:>+7.1f}{fo}  {mr_:>+7.1f}")

print(f"\n  TECHNICAL")
print(f"  {'Sample rate (Hz)':<30} {osr:>12}  {msr:>12}  {rsr:>12}")
print(f"  {'Duration (s)':<30} {len(oL)/osr:>12.1f}  {len(mL)/msr:>12.1f}  {len(rL)/rsr:>12.1f}")
dc_o = abs(float(np.mean(oL2))); dc_m = abs(float(np.mean(mL))); dc_r = abs(float(np.mean(rL2)))
print(f"  {'DC offset':<30} {dc_o:>12.6f}  {dc_m:>12.6f}  {dc_r:>12.6f}")
print(sep)
