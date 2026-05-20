import argparse,json,os,time,warnings
warnings.filterwarnings('ignore')
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d
from scipy.interpolate import interp1d
import librosa
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt

FMIN,FMAX,N_BINS,DETREND_WIN=5000,16000,128,18
D_NOISE_DB=-58.0;D_STEREO_RATE=0.07;D_STEREO_DEPTH=0.03
D_DRIVE_DB=1.0;D_GRID_DIV=128;D_THRESHOLD=0.15;QCF=256

def fingerprint(mono,sr,fmax=FMAX):
    f,_,Z=signal.stft(mono,fs=sr,nperseg=4096,noverlap=3072,window='hann')
    avg=np.mean(np.abs(Z),axis=1)
    mask=(f>=FMIN)&(f<=fmax)
    bf=np.linspace(FMIN,fmax,N_BINS)
    s=interp1d(f[mask],avg[mask],kind='linear',bounds_error=False,fill_value=0.0)(bf)
    lm=minimum_filter1d(s,size=DETREND_WIN)
    raw=s-lm;peak=raw.max()
    norm=raw/peak if peak>0 else raw.copy()
    return dict(norm=norm,raw=raw,bf=bf,peak=float(peak))

def proxy(fp):
    t=np.sort(fp['norm'])[-8:]
    return float(1/(1+np.exp(-(t.mean()-0.35)*8)))

def add_noise(audio,sr,db):
    n,nch=audio.shape;amp=10**(db/20)
    rng=np.random.default_rng(42)
    hp=signal.butter(2,40,btype='high',fs=sr,output='sos')
    lp=signal.butter(2,min(18000,sr//2-200),btype='low',fs=sr,output='sos')
    out=np.zeros_like(audio)
    for ch in range(nch):
        x=rng.standard_normal(n)*amp
        x=signal.sosfiltfilt(hp,x);x=signal.sosfiltfilt(lp,x)
        out[:,ch]=x
    return audio+out

def add_stereo(audio,sr,rate,depth):
    if audio.shape[1]<2:return audio.copy()
    t=np.arange(audio.shape[0])/sr
    lfo=1+depth*np.sin(2*np.pi*rate*t)
    mid=(audio[:,0]+audio[:,1])*.5
    side=(audio[:,0]-audio[:,1])*.5*lfo
    out=np.zeros_like(audio);out[:,0]=mid+side;out[:,1]=mid-side
    return out

def add_saturation(audio,db):
    d=10**(db/20);return np.tanh(audio*d)/d

def crossfade(audio,pos,shift,cf):
    n,nch=audio.shape;out=audio.copy()
    fo=np.linspace(1,0,cf);fi=np.linspace(0,1,cf)
    for ch in range(nch):
        os=audio[max(0,pos):min(n,pos+cf),ch]
        ss=max(0,pos+shift);se=min(n,pos+shift+cf)
        sh=audio[ss:se,ch];bl=min(len(os),len(sh),cf)
        if bl<4:continue
        out[pos:pos+bl,ch]=os[:bl]*fo[:bl]+sh[:bl]*fi[:bl]
        ps=pos+bl;ph=ss+bl;cl=min(n-ps,n-ph)
        if cl>0:out[ps:ps+cl,ch]=audio[ph:ph+cl,ch]
    return out

def add_quantize(audio,sr,div,bpm_ov=None):
    n,nch=audio.shape
    mono=np.mean(audio,axis=1).astype(np.float32)
    if bpm_ov:bpm=float(bpm_ov)
    else:
        t,_=librosa.beat.beat_track(y=mono,sr=sr,units='time')
        bpm=float(np.atleast_1d(t)[0])
    if bpm<=0 or bpm>300:
        print(f"  BPM failed ({bpm:.1f}), skipping");return audio.copy(),bpm,0,0.0
    cell=(60/bpm/div)*sr;maxs=int(cell/2)
    onsets=librosa.onset.onset_detect(y=mono,sr=sr,units='samples',
        hop_length=256,backtrack=True,pre_max=3,post_max=3,
        pre_avg=3,post_avg=5,delta=0.07,wait=10)
    res=audio.copy();cum=0;ns=0;ms=0
    for ow in onsets:
        o=ow+cum
        if o<0 or o>=n:continue
        ng=int(round(o/cell)*cell);sh=ng-o
        if abs(sh)>maxs or sh==0:continue
        res=crossfade(res,max(0,o-QCF//2),sh,QCF)
        cum+=sh;ns+=1;ms=max(ms,abs(sh))
    return res,bpm,ns,ms/sr*1000

def make_plot(fb,fa,thr,suf,path):
    fig,ax=plt.subplots(3,1,figsize=(14,9),facecolor='#0d1117')
    fig.suptitle(f"Fingerprint v6.0 - {suf}",color='white',fontsize=12)
    x=np.arange(N_BINS)
    for a,d,c,l in[(ax[0],fb['norm'],'#f85149','Before'),(ax[1],fa['norm'],'#3fb950','After')]:
        a.set_facecolor('#161b22');a.tick_params(colors='#8b949e')
        a.bar(x,d,color=c,alpha=0.85,width=0.85)
        a.axhline(thr,color='#e3b341',ls='--',lw=1.2,label=f'thr {thr}')
        a.set_title(l,color=c,fontsize=10);a.set_ylim(0,1.08)
        a.legend(facecolor='#161b22',labelcolor='white',fontsize=8)
    delta=fa['norm']-fb['norm']
    ax[2].set_facecolor('#161b22');ax[2].tick_params(colors='#8b949e')
    ax[2].bar(x,delta,color=['#3fb950' if d<0 else '#f85149' for d in delta],alpha=0.85,width=0.85)
    ax[2].axhline(0,color='#8b949e',lw=0.8)
    ax[2].set_title('Delta - green=improved',color='#8b949e',fontsize=10)
    ax[2].set_xlabel('Bin (0=5kHz -> 127=16kHz)',color='#8b949e')
    plt.tight_layout();plt.savefig(path,dpi=150,bbox_inches='tight',facecolor='#0d1117')
    plt.close()

def main():
    ap=argparse.ArgumentParser(description='AI Artifact Cleaner v6.0')
    ap.add_argument('input');ap.add_argument('output',nargs='?',default='')
    ap.add_argument('--analyze_only',action='store_true')
    ap.add_argument('--noise_db',type=float,default=D_NOISE_DB)
    ap.add_argument('--no_noise',action='store_true')
    ap.add_argument('--stereo_rate',type=float,default=D_STEREO_RATE)
    ap.add_argument('--stereo_depth',type=float,default=D_STEREO_DEPTH)
    ap.add_argument('--no_stereo',action='store_true')
    ap.add_argument('--drive_db',type=float,default=D_DRIVE_DB)
    ap.add_argument('--no_saturate',action='store_true')
    ap.add_argument('--grid_div',type=int,default=D_GRID_DIV)
    ap.add_argument('--bpm',type=float,default=0.0)
    ap.add_argument('--no_quantize',action='store_true')
    ap.add_argument('--threshold',type=float,default=D_THRESHOLD)
    ap.add_argument('--plot',default='')
    ap.add_argument('--json',default='')
    a=ap.parse_args()
    if not a.analyze_only and not a.output:ap.error('output required')
    print(f"\n{'='*60}\n  AI Artifact Cleaner v6.0\n  Input : {os.path.basename(a.input)}")
    if not a.analyze_only:print(f"  Output: {os.path.basename(a.output)}")
    print('='*60)
    audio,sr=sf.read(a.input,always_2d=True)
    info=sf.info(a.input);n,nch=audio.shape;dur=n/sr
    print(f"  {dur:.1f}s | {sr}Hz | {nch}ch | {info.subtype}")
    sub='PCM_16' if 'PCM_16' in info.subtype else 'PCM_24'
    fmax=min(FMAX,sr//2-200)
    audio=audio.astype(np.float64);mono=np.mean(audio,axis=1)
    print("\n  Computing fingerprint...")
    fb=fingerprint(mono,sr,fmax)
    print(f"  Score proxy: {proxy(fb)*100:.1f}% (test on letssubmit.com)")
    if a.analyze_only:
        high=np.where(fb['norm']>a.threshold)[0]
        for nv,hz,bi in sorted(zip(fb['norm'][high],fb['bf'][high],high),reverse=True):
            print(f"  Bin {bi:>3}  {hz:>7.0f}Hz  {nv:.3f}")
        return
    proc=audio.copy();t0=time.time()
    if not a.no_noise:
        print(f"\n  Stage A  Noise floor    [{a.noise_db} dBFS]")
        proc=add_noise(proc,sr,a.noise_db)
    else:print("\n  Stage A  Noise floor    [SKIPPED]")
    if not a.no_stereo and nch>=2:
        print(f"  Stage B  Stereo movement [{a.stereo_rate}Hz, {a.stereo_depth*100:.1f}% depth]")
        proc=add_stereo(proc,sr,a.stereo_rate,a.stereo_depth)
    else:print("  Stage B  Stereo movement [SKIPPED]")
    if not a.no_saturate:
        print(f"  Stage C  Saturation     [{a.drive_db}dB]")
        proc=add_saturation(proc,a.drive_db)
    else:print("  Stage C  Saturation     [SKIPPED]")
    if not a.no_quantize:
        print(f"  Stage D  Grid quantize  [{a.grid_div} div/beat]")
        proc,bpm,ns,ms=add_quantize(proc,sr,a.grid_div,a.bpm if a.bpm>0 else None)
        print(f"           BPM={bpm:.1f} | {ns} onsets shifted | max={ms:.2f}ms")
    else:print("  Stage D  Grid quantize  [SKIPPED]")
    print(f"\n  Done in {time.time()-t0:.1f}s")
    pk=np.max(np.abs(proc))
    if pk>0.9999:proc/=pk*1.0001;print(f"  Clip guard peak={pk:.5f}")
    fa=fingerprint(np.mean(proc,axis=1),sr,fmax)
    improved=bool(fa['peak']<fb['peak'])
    high=np.where(fb['norm']>a.threshold)[0]
    top=sorted(zip(fb['norm'][high],fb['raw'][high],fb['bf'][high],high),reverse=True)[:12]
    print(f"\n  {'Bin':>5}  {'Hz':>7}  {'Norm_B':>7}  {'Norm_A':>7}  {'Delta':>7}  {'Raw_B':>10}  {'Raw_A':>10}")
    print(f"  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*10}  {'-'*10}")
    for nb,rb,hz,bi in top:
        na=fa['norm'][bi];ra=fa['raw'][bi];d=na-nb
        mk='v' if d<-0.01 else('^' if d>0.01 else ' ')
        print(f"  {bi:>5}  {hz:>7.0f}  {nb:>7.3f}  {na:>7.3f}  {d:>+7.3f}{mk}  {rb:>10.6f}  {ra:>10.6f}")
    pb=proxy(fb);pa=proxy(fa)
    print(f"\n  Score proxy: {pb*100:.1f}% -> {pa*100:.1f}% ({(pa-pb)*100:+.1f}pp)")
    print(f"  Peak raw:   {fb['peak']:.6f} -> {fa['peak']:.6f}")
    print(f"  {'OK' if improved else '!!'} Quality gate {'passed' if improved else 'WARNING'}")
    sf.write(a.output,proc,sr,subtype=sub)
    print(f"\n  Audio -> {os.path.basename(a.output)} [{sub}]")
    pp=a.plot or a.output.replace('.wav','_fingerprint.png')
    make_plot(fb,fa,a.threshold,f"noise={a.noise_db}|stereo={a.stereo_depth*100:.0f}%|drive={a.drive_db}",pp)
    print(f"  Plot  -> {os.path.basename(pp)}")
    jp=a.json or a.output.replace('.wav','_report.json')
    with open(jp,'w') as f:
        json.dump(dict(version='v6.0',improved=improved,score_before=round(pb*100,1),
            score_after=round(pa*100,1),peak_before=round(fb['peak'],6),
            peak_after=round(fa['peak'],6)),f,indent=2)
    print(f"  JSON  -> {os.path.basename(jp)}\n{'='*60}\n")

if __name__=='__main__':main()