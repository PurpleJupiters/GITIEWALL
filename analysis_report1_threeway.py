"""Report 1: Three-way deep comparison — Master vs Original vs Reference"""
import numpy as np, soundfile as sf, librosa, warnings
from scipy import signal
from scipy.signal import butter, sosfilt
warnings.filterwarnings('ignore')

ORIG  = r"C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav"
MAST  = r"C:\Users\equat\Desktop\Latest Mastered Songs\Transfinite (Agent WALL) Master_master_v5.4.wav"
REF   = r"E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav"
SR = 48000

def load(p):
    d,sr=sf.read(p,always_2d=True,dtype='float32')
    L,R=d[:,0],d[:,1]
    if sr!=SR:
        L=librosa.resample(L.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
        R=librosa.resample(R.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
    return L,R

def lufs(L,R):
    BS=np.array([1.53512485958697,-2.69169618940638,1.19839281085285])
    AS=np.array([1.0,-1.69065929318241,0.73248077421585])
    BH=np.array([1.0,-2.0,1.0]);AH=np.array([1.0,-1.99004745483398,0.99007225036603])
    kL=signal.lfilter(BH,AH,signal.lfilter(BS,AS,L.astype(np.float64)))
    kR=signal.lfilter(BH,AH,signal.lfilter(BS,AS,R.astype(np.float64)))
    bl=int(0.4*SR);hop=int(0.1*SR);n=(len(kL)-bl)//hop
    ms=np.array([0.5*(np.mean(kL[i*hop:i*hop+bl]**2)+np.mean(kR[i*hop:i*hop+bl]**2)) for i in range(n)])
    g1=ms[ms>1e-7]
    if not len(g1): return -70.0
    g2=ms[ms>np.mean(g1)*10**(-10/10)]
    return float(-0.691+10*np.log10(np.mean(g2))) if len(g2) else -70.0

def peak(L,R): return float(20*np.log10(max(np.max(np.abs(L)),np.max(np.abs(R)))+1e-12))
def rms(L,R):  return float(10*np.log10((np.mean(L.astype(np.float64)**2)+np.mean(R.astype(np.float64)**2))/2+1e-12))
def crest(L,R): return peak(L,R)-lufs(L,R)
def corr(L,R):
    n=min(len(L),len(R)); lz=L[:n]-np.mean(L[:n]); rz=R[:n]-np.mean(R[:n])
    d=np.sqrt(np.sum(lz.astype(np.float64)**2)*np.sum(rz.astype(np.float64)**2))
    return float(np.sum(lz.astype(np.float64)*rz.astype(np.float64))/d) if d>0 else 0.0
def width(L,R):
    m=(L+R)/2; s=(L-R)/2
    return float(np.sqrt(np.mean(s**2))/(np.sqrt(np.mean(m**2))+1e-12))
def lra(L,R):
    mono=(L.astype(np.float64)+R.astype(np.float64))/2
    bl=int(3*SR);hop_=int(SR);n=(len(mono)-bl)//hop_
    lvl=np.array([10*np.log10(np.mean(mono[i*hop_:i*hop_+bl]**2)+1e-12) for i in range(n)])
    lvl=lvl[lvl>-70]
    return float(np.percentile(lvl,95)-np.percentile(lvl,10)) if len(lvl)>4 else 0.0
def band(L,R,lo,hi):
    hi=min(hi,SR/2*0.99)
    sos=butter(4,[lo/(SR/2),hi/(SR/2)],btype='band',output='sos')
    bl=sosfilt(sos,L.astype(np.float64)); br=sosfilt(sos,R.astype(np.float64))
    return 10*np.log10((np.mean(bl**2)+np.mean(br**2))/2+1e-12)
def slope(L,R):
    mono=((L+R)/2).astype(np.float32)
    D=librosa.stft(mono.astype(np.float64))
    freqs=librosa.fft_frequencies(sr=SR,n_fft=D.shape[0]*2-2)
    mm=np.mean(np.abs(D),axis=1); mm_db=20*np.log10(mm+1e-9)
    mask=(freqs>100)&(freqs<10000)
    return float(np.polyfit(np.log2(freqs[mask]),mm_db[mask],1)[0]) if mask.sum()>2 else 0.0
def dc(L,R): return float((abs(np.mean(L))+abs(np.mean(R)))/2)

oL,oR = load(ORIG)
mL,mR = load(MAST)
rL,rR = load(REF)

def flag(val, ok_range, warn_range):
    """Return flag symbol based on thresholds."""
    if ok_range[0] <= val <= ok_range[1]: return "OK"
    if warn_range[0] <= val <= warn_range[1]: return "WARN"
    return "BAD"

print("="*80)
print("  REPORT 1: THREE-WAY DEEP ANALYSIS")
print("  ORIGINAL  |  MASTER v5.4  |  REFERENCE (Guy J - Worlds Apart)")
print("="*80)

ol=lufs(oL,oR); ml=lufs(mL,mR); rl=lufs(rL,rR)
op=peak(oL,oR); mp=peak(mL,mR); rp=peak(rL,rR)
orm=rms(oL,oR); mrm=rms(mL,mR); rrm=rms(rL,rR)
oc=crest(oL,oR); mc=crest(mL,mR); rc=crest(rL,rR)
olra=lra(oL,oR); mlra=lra(mL,mR); rlra=lra(rL,rR)
oc2=corr(oL,oR); mc2=corr(mL,mR); rc2=corr(rL,rR)
ow=width(oL,oR); mw=width(mL,mR); rw=width(rL,rR)
osl=slope(oL,oR); msl=slope(mL,mR); rsl=slope(rL,rR)

print(f"\n  LOUDNESS & DYNAMICS")
print(f"  {'Metric':<26} {'Original':>10}  {'Master':>10}  {'Reference':>10}  {'M-O':>7}  {'M-R':>7}  Flag")
print(f"  {'-'*78}")

def row(label, ov, mv, rv, mo_ok=1.5, mr_ok=1.5, fmt=".2f"):
    mo=mv-ov; mr=mv-rv
    f_mo = "OK" if abs(mo)<=mo_ok else ("WARN" if abs(mo)<=mo_ok*2 else "BAD")
    f_mr = "OK" if abs(mr)<=mr_ok else ("WARN" if abs(mr)<=mr_ok*2 else "BAD")
    worst = "BAD" if "BAD" in [f_mo,f_mr] else ("WARN" if "WARN" in [f_mo,f_mr] else "OK")
    sym = {"OK":"  [OK]","WARN":" [!!] ","BAD":" [!!!]"}[worst]
    print(f"  {label:<26} {ov:>+10{fmt}}  {mv:>+10{fmt}}  {rv:>+10{fmt}}  {mo:>+7.2f}  {mr:>+7.2f} {sym}")

row("Integrated LUFS",     ol,ml,rl, 1.5, 1.5)
row("True Peak (dBTP)",    op,mp,rp, 0.5, 1.0)
row("RMS Level (dB)",      orm,mrm,rrm, 1.5, 2.0)
row("Crest Factor (dB)",   oc,mc,rc, 1.5, 2.0, ".1f")
row("LRA Dyn Range (dB)",  olra,mlra,rlra, 3.0, 4.0, ".1f")
row("Stereo Corr",         oc2,mc2,rc2, 0.10, 0.10, ".3f")
row("Width S/M ratio",     ow,mw,rw, 0.08, 0.08, ".3f")
row("Spectral Slope dB/oct",osl,msl,rsl, 0.8, 1.5, ".2f")
print(f"  {'DC Offset':<26} {dc(oL,oR):>10.5f}  {dc(mL,mR):>10.5f}  {dc(rL,rR):>10.5f}  {'':>7}  {'':>7}")

print(f"\n  SPECTRAL BANDS vs REFERENCE (M-R = master minus reference)")
print(f"  {'Band':<14}{'Range':>11}  {'Original':>9}  {'Master':>9}  {'Reference':>9}  {'M-O':>7}  {'M-R':>7}  Flag")
print(f"  {'-'*80}")
bands=[("Deep Sub","20-60Hz",20,60),("Sub Bass","60-120Hz",60,120),
       ("Kick Body","120-200Hz",120,200),("Low Mid","200-500Hz",200,500),
       ("Mid Low","500-1kHz",500,1000),("Mid","1-3kHz",1000,3000),
       ("Presence","3-6kHz",3000,6000),("Hi Mid","6-10kHz",6000,10000),
       ("Air","10-16kHz",10000,16000),("Ultra Air","16-20kHz",16000,20000)]
for nm,rng,lo,hi in bands:
    ob=band(oL,oR,lo,hi); mb_=band(mL,mR,lo,hi); rb=band(rL,rR,lo,hi)
    mo=mb_-ob; mr=mb_-rb
    worst="BAD" if abs(mo)>4 or abs(mr)>3 else ("WARN" if abs(mo)>2 or abs(mr)>2 else "OK")
    sym={"OK":"  [OK]","WARN":" [!!] ","BAD":" [!!!]"}[worst]
    print(f"  {nm:<14}{rng:>11}  {ob:>+9.1f}  {mb_:>+9.1f}  {rb:>+9.1f}  {mo:>+7.1f}  {mr:>+7.1f} {sym}")

print(f"\n  PINK NOISE COMPLIANCE (master, deviation from -3dB/oct)")
print(f"  {'Hz':>8}  {'Orig dev':>10}  {'Master dev':>10}  {'Ref dev':>10}  Flag")
print(f"  {'-'*54}")
from scipy.ndimage import median_filter as mf
def pn_dev(L,R):
    mono=((L+R)/2).astype(np.float64)
    ctr=[80,160,320,640,1280,2560,5120,10240]
    e=[]
    for fc in ctr:
        lo=fc/2**0.5; hi=min(fc*2**0.5,SR/2*0.99)
        sos=butter(4,[lo/(SR/2),hi/(SR/2)],'band',output='sos')
        b=sosfilt(sos,mono); e.append(10*np.log10(np.mean(b**2)+1e-12))
    ref=[e[0]+i*(-3.0) for i in range(len(e))]
    return [80,160,320,640,1280,2560,5120,10240],[v-r for v,r in zip(e,ref)]
_,od=pn_dev(oL,oR); _,md=pn_dev(mL,mR); hz,rd=pn_dev(rL,rR)
for i,h in enumerate(hz):
    worst="BAD" if abs(md[i])>6 else ("WARN" if abs(md[i])>3 else "OK")
    sym={"OK":"  [OK]","WARN":" [!!] ","BAD":" [!!!]"}[worst]
    print(f"  {h:>6}Hz  {od[i]:>+10.1f}  {md[i]:>+10.1f}  {rd[i]:>+10.1f} {sym}")

print(f"\n  FLAG LEGEND:  [OK] = within tolerance  [!!] = warning  [!!!] = problem")
print("="*80)
