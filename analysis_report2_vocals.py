"""Report 2: Detailed vocal analysis vs professional standards"""
import numpy as np, soundfile as sf, librosa, warnings
from scipy import signal
from scipy.signal import butter, sosfilt, find_peaks
from scipy.ndimage import median_filter
warnings.filterwarnings('ignore')

VOC_PATH = r"C:\Users\equat\Desktop\Latest Mastered Songs\Transfinite_vocals.wav"
SR = 48000

def load_mono(p):
    d,sr=sf.read(p,always_2d=True,dtype='float32')
    L,R=d[:,0],d[:,1]
    if sr!=SR:
        L=librosa.resample(L.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
        R=librosa.resample(R.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
    return L, R, (L+R)*0.5

vL,vR,vmono = load_mono(VOC_PATH)

print("="*80)
print("  REPORT 2: VOCAL TRACK DEEP ANALYSIS vs PROFESSIONAL STANDARDS")
print(f"  File: Transfinite_vocals.wav")
print("="*80)

# ── 1. ATTACK ANALYSIS ──────────────────────────────────────────────────────
print(f"\n  1. ATTACK SHARPNESS ANALYSIS")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
hop_a = int(SR*0.001)  # 1ms hop
env = np.array([float(np.sqrt(np.mean(vmono[i*hop_a:(i+1)*hop_a]**2)+1e-20))
                for i in range(len(vmono)//hop_a)])
db_env = 20*np.log10(env+1e-9)
# Detect onsets as places where level rises > 20dB in 10ms
rises=[]
for i in range(10,len(db_env)-1):
    rise = db_env[i] - db_env[max(0,i-10)]
    if rise > 20:
        rises.append(rise)
avg_rise = float(np.mean(rises)) if rises else 0
max_rise = float(np.max(rises)) if rises else 0
n_abrupt = sum(1 for r in rises if r > 30)

def sym(val, ok, warn):
    return "  [OK]" if val<=ok else (" [!!] " if val<=warn else " [!!!]")

print(f"  {'Num of detected onsets':<40} {len(rises):>12d}  {'varies':>14}")
print(f"  {'Avg onset rise (dB in 10ms)':<40} {avg_rise:>12.1f}  {'15-25dB':>14} {sym(avg_rise,25,35)}")
print(f"  {'Max onset rise (dB in 10ms)':<40} {max_rise:>12.1f}  {'<35dB':>14} {sym(max_rise,35,50)}")
print(f"  {'Abrupt attacks (>30dB in 10ms)':<40} {n_abrupt:>12d}  {'<10':>14} {sym(n_abrupt,10,25)}")

# ── 2. CLICK AND POP DETECTION ───────────────────────────────────────────────
print(f"\n  2. CLICK / POP / GLITCH DETECTION")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
hop_c = int(SR*0.002)
frames_c = np.array([float(np.max(np.abs(vmono[i*hop_c:(i+1)*hop_c])))
                     for i in range(len(vmono)//hop_c)])
med_c = np.median(frames_c)+1e-12
spikes = int(np.sum(frames_c > med_c*6))
silences = int(np.sum(frames_c < med_c*0.003))
max_ratio = float(np.max(frames_c)/med_c)
# Find zero-crossing anomalies (clicks = sudden high ZCR spike)
zc_frames = np.array([float(np.sum(np.diff(np.sign(vmono[i*hop_c:(i+1)*hop_c]))!=0))
                       for i in range(len(vmono)//hop_c)])
med_zc = np.median(zc_frames)+1e-12
zc_spikes = int(np.sum(zc_frames > med_zc*4))

print(f"  {'Amplitude spikes (>6x median)':<40} {spikes:>12d}  {'0-5':>14} {sym(spikes,5,15)}")
print(f"  {'Silence gaps (<0.3% median)':<40} {silences:>12d}  {'0-10':>14} {sym(silences,10,20)}")
print(f"  {'Max amplitude ratio to median':<40} {max_ratio:>12.1f}x  {'<4x':>14} {sym(max_ratio,4,8)}")
print(f"  {'Zero-crossing rate spikes':<40} {zc_spikes:>12d}  {'0-20':>14} {sym(zc_spikes,20,50)}")

# ── 3. DE-ESSING ANALYSIS ────────────────────────────────────────────────────
print(f"\n  3. DE-ESSING / SIBILANCE ANALYSIS")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
# Measure energy in sibilance zone vs total
sos_sib = butter(4,[5000/(SR/2),min(12000/(SR/2),0.99)],'band',output='sos')
sib = sosfilt(sos_sib, vmono.astype(np.float64))
sib_rms = float(20*np.log10(np.sqrt(np.mean(sib**2))+1e-12))
tot_rms = float(20*np.log10(np.sqrt(np.mean(vmono.astype(np.float64)**2))+1e-12))
sib_ratio_db = sib_rms - tot_rms  # how much sibilance vs total
# Peak sibilance events
hop_s=int(SR*0.010)
sib_env=np.array([float(np.sqrt(np.mean(sib[i*hop_s:(i+1)*hop_s]**2)+1e-20))
                  for i in range(len(sib)//hop_s)])
tot_env=np.array([float(np.sqrt(np.mean(vmono.astype(np.float64)[i*hop_s:(i+1)*hop_s]**2)+1e-20))
                  for i in range(len(vmono)//hop_s)])
n=min(len(sib_env),len(tot_env))
sib_peaks = int(np.sum((sib_env[:n]/(tot_env[:n]+1e-12)) > 0.35))
# Harsh 3-6kHz presence
sos_h=butter(4,[3000/(SR/2),min(6000/(SR/2),0.99)],'band',output='sos')
harsh=sosfilt(sos_h,vmono.astype(np.float64))
harsh_rms=float(20*np.log10(np.sqrt(np.mean(harsh**2))+1e-12))
harsh_ratio=harsh_rms-tot_rms

print(f"  {'Sibilance RMS vs total (5-12kHz)':<40} {sib_ratio_db:>+12.1f}dB  {'-20 to -14dB':>14} {sym(-sib_ratio_db,-14,-10)}")
print(f"  {'Sibilance peak events':<40} {sib_peaks:>12d}  {'<30':>14} {sym(sib_peaks,30,60)}")
print(f"  {'Harshness ratio (3-6kHz vs total)':<40} {harsh_ratio:>+12.1f}dB  {'-18 to -12dB':>14} {sym(-harsh_ratio,-12,-8)}")

# ── 4. SPECTRAL RESONANCE / AI SHEEN ────────────────────────────────────────
print(f"\n  4. AI SPECTRAL ARTIFACT ANALYSIS")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
n_fft=2048; hop_sp=n_fft//4
D=librosa.stft(vmono.astype(np.float64),n_fft=n_fft,hop_length=hop_sp)
mag=np.abs(D)
freqs=librosa.fft_frequencies(sr=SR,n_fft=n_fft)
# Spectral flatness in AI artifact zone (2-8kHz)
mask_ai=(freqs>=2000)&(freqs<=8000)
geo_mean=np.exp(np.mean(np.log(mag[mask_ai]+1e-9),axis=0))
arith_mean=np.mean(mag[mask_ai],axis=0)+1e-9
sf_ai=float(np.mean(geo_mean/arith_mean))  # 0=tonal, 1=noise-like
# Temporal variance of spectral peaks in 2-8kHz (AI = low variance = unnaturally stable)
peak_hz_per_frame=[]
for fi in range(mag.shape[1]):
    frame=mag[:,fi]
    pks,_=find_peaks(frame[mask_ai],prominence=0.01*np.max(frame)+1e-9)
    if len(pks):
        peak_hz_per_frame.append(freqs[mask_ai][pks[0]])
temporal_var = float(np.std(peak_hz_per_frame)) if peak_hz_per_frame else 0
# Harmonicity (natural voice: 0.6-0.9, AI: 0.9-1.0)
harmonic,percussive=librosa.effects.hpss(vmono.astype(np.float32))
harm_ratio=float(np.sqrt(np.mean(harmonic**2))/(np.sqrt(np.mean(vmono.astype(np.float64)**2))+1e-12))

print(f"  {'Spectral flatness 2-8kHz (0=tonal,1=noise)':<40} {sf_ai:>12.3f}  {'0.05-0.25':>14} {sym(sf_ai,0.25,0.45)}")
print(f"  {'Peak freq temporal variance 2-8kHz':<40} {temporal_var:>12.0f}Hz  {'>200Hz':>14} {'  [OK]' if temporal_var>200 else (' [!!] ' if temporal_var>100 else ' [!!!]')}")
print(f"  {'Harmonicity ratio':<40} {harm_ratio:>12.3f}  {'0.5-0.85':>14} {sym(harm_ratio,0.85,0.95)}")

# ── 5. DYNAMIC RANGE AND LEVEL ───────────────────────────────────────────────
print(f"\n  5. VOCAL DYNAMICS & LEVEL")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
from scipy import signal as sp_
BS=np.array([1.53512485958697,-2.69169618940638,1.19839281085285])
AS=np.array([1.0,-1.69065929318241,0.73248077421585])
BH=np.array([1.0,-2.0,1.0]);AH=np.array([1.0,-1.99004745483398,0.99007225036603])
kL2=sp_.lfilter(BH,AH,sp_.lfilter(BS,AS,vL.astype(np.float64)))
kR2=sp_.lfilter(BH,AH,sp_.lfilter(BS,AS,vR.astype(np.float64)))
bl=int(0.4*SR);hop=int(0.1*SR);n=(len(kL2)-bl)//hop
ms=np.array([0.5*(np.mean(kL2[i*hop:i*hop+bl]**2)+np.mean(kR2[i*hop:i*hop+bl]**2)) for i in range(n)])
g1=ms[ms>1e-7]
voc_lufs = float(-0.691+10*np.log10(np.mean(ms[ms>np.mean(g1)*10**(-10/10)]))) if len(g1) else -70
voc_pk = float(20*np.log10(max(np.max(np.abs(vL)),np.max(np.abs(vR)))+1e-12))
voc_crest = voc_pk - voc_lufs
mono_=((vL+vR)*0.5).astype(np.float64)
bl2=int(3*SR); hop2=int(SR); n2=(len(mono_)-bl2)//hop2
lvl=np.array([10*np.log10(np.mean(mono_[i*hop2:i*hop2+bl2]**2)+1e-12) for i in range(n2)])
lvl=lvl[lvl>-70]
voc_lra=float(np.percentile(lvl,95)-np.percentile(lvl,10)) if len(lvl)>4 else 0

print(f"  {'Integrated LUFS':<40} {voc_lufs:>+12.1f}dB  {'-18 to -14 LUFS':>14} {sym(abs(voc_lufs+16),2,6)}")
print(f"  {'True Peak':<40} {voc_pk:>+12.1f}dBTP  {'<-1.0dBTP':>14} {'  [OK]' if voc_pk<-1.0 else ' [!!!]'}")
print(f"  {'Crest Factor':<40} {voc_crest:>+12.1f}dB  {'12-18dB':>14} {sym(abs(voc_crest-15),3,6)}")
print(f"  {'LRA (section dynamics)':<40} {voc_lra:>+12.1f}dB  {'8-16dB':>14} {sym(abs(voc_lra-12),4,8)}")

# ── 6. STEREO FIELD ──────────────────────────────────────────────────────────
print(f"\n  6. STEREO FIELD")
print(f"  {'Metric':<40} {'Value':>12}  {'Prof Standard':>14}  Flag")
print(f"  {'-'*72}")
n2=min(len(vL),len(vR)); lz=vL[:n2]-np.mean(vL[:n2]); rz=vR[:n2]-np.mean(vR[:n2])
dd=np.sqrt(np.sum(lz.astype(np.float64)**2)*np.sum(rz.astype(np.float64)**2))
vcorr=float(np.sum(lz.astype(np.float64)*rz.astype(np.float64))/dd) if dd>0 else 0
m=(vL+vR)/2; s=(vL-vR)/2
vwidth=float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-12))
print(f"  {'Stereo correlation':<40} {vcorr:>12.3f}  {'0.85-1.0':>14} {'  [OK]' if vcorr>0.85 else (' [!!] ' if vcorr>0.70 else ' [!!!]')}")
print(f"  {'Stereo width S/M':<40} {vwidth:>12.3f}  {'<0.15 (near mono)':>14} {'  [OK]' if vwidth<0.15 else (' [!!] ' if vwidth<0.25 else ' [!!!]')}")

print(f"\n  FLAG LEGEND:  [OK] = professional standard  [!!] = needs attention  [!!!] = fix required")
print("="*80)
