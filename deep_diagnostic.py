"""
Deep diagnostic — compares original, current master, and reference track.
Identifies exact frequency, dynamic, and stereo problems.
"""
import numpy as np, soundfile as sf, librosa, warnings
from scipy import signal
from scipy.signal import butter, sosfilt
from scipy.ndimage import median_filter
warnings.filterwarnings('ignore')

ORIG  = r"C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav"
MAST  = r"E:\SunoMaster\output\Transfinite (Agent WALL) Master\master\Transfinite (Agent WALL) Master_master_v5.4.wav"
REF   = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"
SR    = 48000

def load_at(path, target_sr=SR):
    d, sr = sf.read(path, always_2d=True, dtype='float32')
    L, R = d[:,0], d[:,1]
    if sr != target_sr:
        L = librosa.resample(L.astype(np.float64), orig_sr=sr, target_sr=target_sr).astype(np.float32)
        R = librosa.resample(R.astype(np.float64), orig_sr=sr, target_sr=target_sr).astype(np.float32)
    return L, R, target_sr

def lufs(L, R, sr):
    BS=np.array([1.53512485958697,-2.69169618940638,1.19839281085285])
    AS=np.array([1.0,-1.69065929318241,0.73248077421585])
    BH=np.array([1.0,-2.0,1.0]); AH=np.array([1.0,-1.99004745483398,0.99007225036603])
    kL=signal.lfilter(BH,AH,signal.lfilter(BS,AS,L.astype(np.float64)))
    kR=signal.lfilter(BH,AH,signal.lfilter(BS,AS,R.astype(np.float64)))
    bl=int(0.4*sr); hop=int(0.1*sr); n=(len(kL)-bl)//hop
    ms=np.array([0.5*(np.mean(kL[i*hop:i*hop+bl]**2)+np.mean(kR[i*hop:i*hop+bl]**2)) for i in range(n)])
    g1=ms[ms>1e-7]
    if not len(g1): return -70.0
    g2=ms[ms>np.mean(g1)*10**(-10/10)]
    return float(-0.691+10*np.log10(np.mean(g2))) if len(g2) else -70.0

def peak(L,R):   return float(20*np.log10(max(np.max(np.abs(L)),np.max(np.abs(R)))+1e-12))
def rms(L,R):    return float(10*np.log10((np.mean(L.astype(np.float64)**2)+np.mean(R.astype(np.float64)**2))/2+1e-12))
def crest(L,R,sr): return peak(L,R)-lufs(L,R,sr)
def lra(L,R,sr):
    mono=(L.astype(np.float64)+R.astype(np.float64))/2
    bl=int(3*sr); hop_=int(sr); n=(len(mono)-bl)//hop_
    lvl=np.array([10*np.log10(np.mean(mono[i*hop_:i*hop_+bl]**2)+1e-12) for i in range(n)])
    lvl=lvl[lvl>-70]
    return float(np.percentile(lvl,95)-np.percentile(lvl,10)) if len(lvl)>4 else 0.0

def corr(L,R):
    n=min(len(L),len(R)); lz=L[:n]-np.mean(L[:n]); rz=R[:n]-np.mean(R[:n])
    d=np.sqrt(np.sum(lz.astype(np.float64)**2)*np.sum(rz.astype(np.float64)**2))
    return float(np.sum(lz.astype(np.float64)*rz.astype(np.float64))/d) if d>0 else 0.0

def width(L,R):
    m=(L+R)/2; s=(L-R)/2
    return float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-12))

def band_db(L,R,lo,hi,sr):
    hi=min(hi,sr/2*0.99)
    sos=butter(4,[lo/(sr/2),hi/(sr/2)],btype='band',output='sos')
    bl=sosfilt(sos,L.astype(np.float64)); br=sosfilt(sos,R.astype(np.float64))
    return 10*np.log10((np.mean(bl**2)+np.mean(br**2))/2+1e-12)

def pink_slope(L,R,sr):
    mono=((L+R)/2).astype(np.float32)
    D=librosa.stft(mono.astype(np.float64))
    freqs=librosa.fft_frequencies(sr=sr,n_fft=D.shape[0]*2-2)
    mm=np.mean(np.abs(D),axis=1); mm_db=20*np.log10(mm+1e-9)
    mask=(freqs>100)&(freqs<10000)
    return float(np.polyfit(np.log2(freqs[mask]),mm_db[mask],1)[0]) if mask.sum()>2 else 0.0

def detect_glitches(L,R,sr):
    mono=np.abs((L+R)/2); hop=int(sr*0.01)
    n=len(mono)//hop
    frames=np.array([np.max(mono[i*hop:(i+1)*hop]) for i in range(n)])
    med=np.median(frames)+1e-12
    spikes=int(np.sum(frames>med*8))
    silences=int(np.sum(frames<med*0.005))
    return spikes, silences, float(np.max(frames)/med)

def compression_index(L,R,sr):
    """Ratio of LRA to crest factor — closer to 1.0 = more natural, lower = more squashed."""
    l=lra(L,R,sr); c=crest(L,R,sr)
    return l/c if c>0 else 0.0

oL,oR,osr = load_at(ORIG)
mL,mR,msr = load_at(MAST)
rL,rR,rsr = load_at(REF)

S="="*76
print(S)
print("  DEEP DIAGNOSTIC — ORIGINAL / MASTER v5.4 / REFERENCE (Guy J)")
print(S)

def row(label, ov, mv, rv, warn_delta=None):
    ov=float(ov); mv=float(mv); rv=float(rv)
    delta_om = mv - ov;  delta_mr = mv - rv
    flag_om = " !!" if warn_delta and abs(delta_om)>warn_delta else ("  !" if warn_delta and abs(delta_om)>warn_delta*0.6 else "   ")
    flag_mr = " !!" if warn_delta and abs(delta_mr)>warn_delta else ("  !" if warn_delta and abs(delta_mr)>warn_delta*0.6 else "   ")
    print(f"  {label:<28} {ov:>+10.2f}  {mv:>+12.2f}  {rv:>+12.2f}  {delta_om:>+8.2f}{flag_om}  {delta_mr:>+7.2f}{flag_mr}")

print(f"\n  {'METRIC':<28} {'ORIGINAL':>10}  {'MASTER v5.4':>12}  {'REFERENCE':>12}  {'M-O':>8}  {'M-R':>7}")
print(f"  {'-'*74}")
row("Integrated LUFS",       lufs(oL,oR,SR), lufs(mL,mR,SR), lufs(rL,rR,SR), warn_delta=1.0)
row("True Peak (dBTP)",      peak(oL,oR),    peak(mL,mR),    peak(rL,rR),    warn_delta=1.0)
row("RMS Level (dB)",        rms(oL,oR),     rms(mL,mR),     rms(rL,rR),     warn_delta=2.0)
row("Crest Factor (dB)",     crest(oL,oR,SR),crest(mL,mR,SR),crest(rL,rR,SR),warn_delta=1.5)
row("LRA Dynamic Range",     lra(oL,oR,SR),  lra(mL,mR,SR),  lra(rL,rR,SR),  warn_delta=2.0)
row("Compression Index",     compression_index(oL,oR,SR), compression_index(mL,mR,SR), compression_index(rL,rR,SR), warn_delta=0.15)
row("Stereo Correlation",    corr(oL,oR),    corr(mL,mR),    corr(rL,rR),    warn_delta=0.1)
row("Width (S/M ratio)",     width(oL,oR),   width(mL,mR),   width(rL,rR),   warn_delta=0.08)
row("Spectral Slope dB/oct", pink_slope(oL,oR,SR), pink_slope(mL,mR,SR), pink_slope(rL,rR,SR), warn_delta=0.8)

og,os_,opk = detect_glitches(oL,oR,SR)
mg,ms2,mpk = detect_glitches(mL,mR,SR)
rg,rs_,rpk = detect_glitches(rL,rR,SR)
print(f"  {'Spike frames (>8x median)':<28} {og:>10d}  {mg:>12d}  {rg:>12d}  {mg-og:>+8d}  {mg-rg:>+7d}")
print(f"  {'Silence frames (<0.5%)':<28} {os_:>10d}  {ms2:>12d}  {rs_:>12d}  {ms2-os_:>+8d}  {ms2-rs_:>+7d}")
print(f"  {'Max spike ratio':<28} {opk:>10.1f}x  {mpk:>12.1f}x  {rpk:>12.1f}x")

print(f"\n  SPECTRAL BANDS — How master compares to ORIGINAL and REFERENCE")
print(f"  {'Band':<13}{'Range':>11}  {'Orig':>8}  {'Master':>8}  {'Ref':>8}  {'M-O':>7}  {'M-R':>7}  Status")
print(f"  {'-'*74}")
bands=[("Deep Sub","20-60Hz",20,60),("Sub Bass","60-120Hz",60,120),
       ("Kick Body","120-200Hz",120,200),("Low Mid","200-500Hz",200,500),
       ("Mid Low","500-1kHz",500,1000),("Mid","1-3kHz",1000,3000),
       ("Presence","3-6kHz",3000,6000),("Hi Mid","6-10kHz",6000,10000),
       ("Air","10-16kHz",10000,16000),("Ultra Air","16-20kHz",16000,20000)]
for nm,rng,lo,hi in bands:
    ob=band_db(oL,oR,lo,hi,SR); mb=band_db(mL,mR,lo,hi,SR); rb=band_db(rL,rR,lo,hi,SR)
    mo=mb-ob; mr=mb-rb
    status="OK" if abs(mo)<=2 and abs(mr)<=2 else ("WARN" if abs(mo)<=4 or abs(mr)<=4 else "BAD")
    print(f"  {nm:<13}{rng:>11}  {ob:>+8.1f}  {mb:>+8.1f}  {rb:>+8.1f}  {mo:>+7.1f}  {mr:>+7.1f}  [{status}]")

print(f"\n  PINK NOISE COMPLIANCE — Master (target: all within +-3dB)")
print(f"  {'Hz':>8}  {'Orig dev':>10}  {'Mast dev':>10}  {'Ref dev':>10}")
print(f"  {'-'*44}")
mono_m=((mL+mR)/2).astype(np.float64)
mono_o=((oL+oR)/2).astype(np.float64)
mono_r=((rL+rR)/2).astype(np.float64)
ctr=[80,160,320,640,1280,2560,5120,10240]
def oct_dev(mono,sr,centres):
    e=[]
    for fc in centres:
        lo=fc/2**0.5; hi=min(fc*2**0.5,sr/2*0.99)
        sos=butter(4,[lo/(sr/2),hi/(sr/2)],'band',output='sos')
        b=sosfilt(sos,mono); e.append(10*np.log10(np.mean(b**2)+1e-12))
    ref=[e[0]+i*(-3.0) for i in range(len(e))]
    return [v-r for v,r in zip(e,ref)]
od=oct_dev(mono_o,SR,ctr); md=oct_dev(mono_m,SR,ctr); rd=oct_dev(mono_r,SR,ctr)
for i,hz in enumerate(ctr):
    fo='!' if abs(od[i])>3 else ' '; fm='!' if abs(md[i])>3 else ' '; fr='!' if abs(rd[i])>3 else ' '
    print(f"  {hz:>6}Hz  {od[i]:>+9.1f}{fo}  {md[i]:>+9.1f}{fm}  {rd[i]:>+9.1f}{fr}")

print(f"\n  ROOT CAUSE ANALYSIS")
print(f"  {'-'*74}")
lu_m=lufs(mL,mR,SR); cr_m=crest(mL,mR,SR); lr_m=lra(mL,mR,SR)
lu_o=lufs(oL,oR,SR); cr_o=crest(oL,oR,SR); lr_o=lra(oL,oR,SR)
lu_r=lufs(rL,rR,SR); cr_r=crest(rL,rR,SR)

if cr_o - cr_m > 1.0:
    print(f"  [COMPRESSION]  Crest lost {cr_o-cr_m:.1f}dB vs original — master is over-compressed.")
    print(f"                 Original crest={cr_o:.1f}dB, master={cr_m:.1f}dB, reference={cr_r:.1f}dB")
if lr_o - lr_m > 1.5:
    print(f"  [DYNAMICS]     LRA dropped {lr_o-lr_m:.1f}dB — significant dynamic range loss.")
sl_m=pink_slope(mL,mR,SR); sl_r=pink_slope(rL,rR,SR)
if sl_m < sl_r - 0.5:
    print(f"  [SPECTRUM]     Master slope {sl_m:.2f}dB/oct, reference {sl_r:.2f}dB/oct — master too dark/dull.")
elif sl_m > -2.5:
    print(f"  [SPECTRUM]     Master slope {sl_m:.2f}dB/oct — too bright vs pink noise target of -3.0.")
if mg > og * 1.5:
    print(f"  [GLITCHES]     Master has {mg} spike frames vs original {og} — artifacts introduced by pipeline.")
if ms2 > os_ + 5:
    print(f"  [SILENCE GAPS] Master has {ms2} silence frames vs original {os_} — gating artifacts present.")
w_m=width(mL,mR); w_o=width(oL,oR); w_r=width(rL,rR)
if w_m > w_r + 0.05:
    print(f"  [STEREO]       Master width {w_m:.3f} exceeds reference {w_r:.3f} — too wide for mono compat.")
lo_mid_mo = band_db(mL,mR,200,500,SR) - band_db(oL,oR,200,500,SR)
if lo_mid_mo > 2.5:
    print(f"  [LOW-MID MUD]  Low-mid 200-500Hz is +{lo_mid_mo:.1f}dB vs original — muddy/boxy sound.")
air_mo = band_db(mL,mR,10000,16000,SR) - band_db(rL,rR,10000,16000,SR)
if air_mo < -2.5:
    print(f"  [AIR DEFICIT]  Air band {air_mo:.1f}dB vs reference — master lacks brightness vs ref.")
print(S)
