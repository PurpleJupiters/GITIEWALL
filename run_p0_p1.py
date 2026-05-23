import argparse,gc,subprocess,sys
import numpy as np
import soundfile as sf
import librosa
from scipy import signal as sp
from scipy.signal import find_peaks
from pathlib import Path
SR=48000
def hp(y,hz,o=4): return sp.sosfiltfilt(sp.butter(o,hz,'hp',fs=SR,output='sos'),y).astype(np.float32)
def lp(y,hz,o=4): return sp.sosfiltfilt(sp.butter(o,hz,'lp',fs=SR,output='sos'),y).astype(np.float32)
def notch(y,hz,Q=3.5):
    b,a=sp.iirnotch(hz,Q,SR); return sp.sosfiltfilt(sp.tf2sos(b,a),y).astype(np.float32)
def peak_eq(y,hz,g,Q=2):
    A=10**(g/40);w=2*3.14159*hz/SR;al=np.sin(w)/(2*Q)
    b=[1+al*A,-2*np.cos(w),1-al*A];a=[1+al/A,-2*np.cos(w),1-al/A]
    return sp.sosfiltfilt(sp.tf2sos(b,a),y).astype(np.float32)
def hi_shelf(y,hz,g):
    sos=sp.butter(2,hz,'hp',fs=SR,output='sos')
    wet=sp.sosfiltfilt(sos,y).astype(np.float32)
    return (y+(wet*10**(g/20)-wet)).astype(np.float32)
CONSOLES={'neve':(80,.8,.7,15000,-1.,'even',1.),'ssl':(120,.5,1.,18000,-.5,'mix',.85),'api':(200,.6,1.5,12000,-.8,'mix',1.1)}
STEM_CONSOLE={'drums':'ssl','bass':'ssl','other':'neve','vocals':'neve','guitar':'api','piano':'neve'}
def va(y,con='neve',drv=5.,w=.20):
    lf0,lf1,lf2,hf0,hf1,sat,ds=CONSOLES[con];orig=float(np.max(np.abs(y)))+1e-12
    y=peak_eq(y,lf0,lf1,lf2);y=hi_shelf(y,hf0,hf1)
    d=10**((drv*ds)/20);pi=float(np.max(np.abs(y)))+1e-12;yn=y.astype(np.float64)/pi*d
    sh=np.tanh(yn+.07*yn**2).astype(np.float32) if sat=='even' else np.tanh(yn-.03*yn**3).astype(np.float32)
    sh=sh/(float(np.max(np.abs(sh)))+1e-12)*pi;y=(y*(1-w)+sh*w).astype(np.float32)
    return (y*(orig/(float(np.max(np.abs(y)))+1e-12))).astype(np.float32)
def p0(L,R,sr,nm):
    print(f' P0:{nm}')
    if sr!=SR:
        L=librosa.resample(L.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
        R=librosa.resample(R.astype(np.float64),orig_sr=sr,target_sr=SR).astype(np.float32)
    # [SV-01] LP@18kHz NOT applied per-stem — applied once on final master below
    L=hp(L,18,2);R=hp(R,18,2)
    pk=max(float(np.max(np.abs(L))),float(np.max(np.abs(R))))
    if pk>10**(-.5/20):sc=np.float32(10**(-.5/20)/pk);L,R=L*sc,R*sc
    return L,R
def p1(L,R,sn):
    con=STEM_CONSOLE.get(sn,'neve');print(f' P1:{sn}[{con}]')
    L=hp(L,5,2);R=hp(R,5,2)
    y_m=((L+R)*.5).astype(np.float32)
    S=np.abs(librosa.stft(y_m[:SR*30].astype(np.float64),n_fft=4096))
    freqs=librosa.fft_frequencies(sr=SR,n_fft=4096)
    lmag=20*np.log10(np.mean(S,axis=1)+1e-9)
    pks,pr=find_peaks(lmag,prominence=9.,width=(1,10))
    # [SV-02] Notch only drums stem, only above 8kHz (cymbal shrill only)
    # Notching 300-16kHz on ALL stems removes musical content, not artefacts
    if sn=='drums':
        res=sorted([(freqs[i],pr['prominences'][j]) for j,i in enumerate(pks) if 8000<freqs[i]<16000],key=lambda x:-x[1])[:2]
    else:
        res=[]
    del S;gc.collect()
    for fr,pm in res:L=notch(L,fr);R=notch(R,fr);print(f'  notch{fr:.0f}Hz')
    sm=((lp(L,100)+lp(R,100))*.5).astype(np.float32)
    L=(sm+hp(L,100)).astype(np.float32);R=(sm+hp(R,100)).astype(np.float32)
    L=va(L,con);R=va(R,con)
    pk=max(float(np.max(np.abs(L))),float(np.max(np.abs(R))))
    if pk>10**(-.5/20):sc=np.float32(10**(-.5/20)/pk);L,R=L*sc,R*sc
    return L,R
def main():
    pa=argparse.ArgumentParser();pa.add_argument('--input',required=True);pa.add_argument('--output',required=True)
    a=pa.parse_args();src=Path(a.input);out=Path(a.output);nm=src.stem
    sd=out/nm/'stems';d0=out/nm/'P0';d1=out/nm/'P1'
    for d in[sd,d0,d1]:d.mkdir(parents=True,exist_ok=True)
    print(f'\nRunning: {nm}')
    try:
        subprocess.run([sys.executable,'-m','demucs.separate','--name','htdemucs_6s','--out',str(sd),'--int24',str(src)],check=True,timeout=2700)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Demucs timed out (45 min). Try a shorter track or GPU.')
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'Demucs failed (exit {e.returncode}).')
    stem_files=sorted((sd/'htdemucs_6s'/nm).glob('*.wav'))
    print('Stems: '+', '.join(s.stem for s in stem_files))
    proc=[]
    for sp2 in stem_files:
        sn=sp2.stem;dat,sr=sf.read(str(sp2),dtype='float32',always_2d=True)
        L,R=dat[:,0].copy(),dat[:,1].copy();del dat;gc.collect()
        L,R=p0(L,R,sr,sn);sf.write(str(d0/f'{nm}_P0_{sn}.wav'),np.stack([L,R],1),SR,subtype='PCM_24')
        L,R=p1(L,R,sn);sf.write(str(d1/f'{nm}_P1_{sn}.wav'),np.stack([L,R],1),SR,subtype='PCM_24')
        proc.append((sn,L,R));del L,R;gc.collect()
    N=min(len(L) for _,L,_ in proc)
    mL=sum(L[:N] for _,L,_ in proc).astype(np.float32)
    mR=sum(R[:N] for _,_,R in proc).astype(np.float32)
    pk=max(float(np.max(np.abs(mL))),float(np.max(np.abs(mR))))
    if pk>0:sc=np.float32(10**(-.5/20)/pk);mL*=sc;mR*=sc
    # [SV-01] LP@18kHz applied ONCE on final master, not per-stem
    mL=lp(mL,18000,order=4);mR=lp(mR,18000,order=4)
    mp=out/nm/f'{nm}_master.wav';sf.write(str(mp),np.stack([mL,mR],1),SR,subtype='PCM_24')
    print(f'\nDONE: {mp}')
if __name__=='__main__':main()