import numpy as np, soundfile as sf

def full_analysis(path, label):
    d, sr = sf.read(path, dtype='float32', always_2d=True)
    if d.shape[1] == 1:
        L, R = d[:,0], d[:,0]
    else:
        L, R = d[:,0], d[:,1]
    mono = (L + R) * 0.5
    N = len(mono)

    peak_db  = 20*float(np.log10(float(np.max(np.abs(d)))+1e-12))
    rms_db   = 20*float(np.log10(float(np.sqrt(np.mean(mono**2)))+1e-12))
    crest_db = peak_db - rms_db

    M = (L + R) * 0.5
    S = (L - R) * 0.5
    width = float(np.sqrt(np.mean(S**2)) / (np.sqrt(np.mean(M**2))+1e-12))

    fft  = np.abs(np.fft.rfft(mono))
    freq = np.fft.rfftfreq(N, 1.0/sr)
    def band(lo, hi):
        m = (freq>=lo)&(freq<hi)
        return 20*float(np.log10(float(np.mean(fft[m]))+1e-12)) if m.any() else -99.0
    centroid = float(np.sum(freq*fft)/(np.sum(fft)+1e-9))

    hop = sr//4
    rms_blocks = np.array([20*float(np.log10(float(np.sqrt(np.mean(mono[i*hop:(i+1)*hop]**2)))+1e-12))
                           for i in range(N//hop)])
    dr = float(np.percentile(rms_blocks, 95)) - float(np.percentile(rms_blocks, 5))

    corr_len = min(N, sr*30)
    corr = float(np.corrcoef(L[:corr_len], R[:corr_len])[0,1])

    # Octave-band breakdown
    bands = [
        ('Sub    20-60',   20,   60),
        ('Bass   60-250',  60,  250),
        ('LowMid250-800',  250, 800),
        ('Vocal  800-3k5', 800, 3500),
        ('HiMid  3k5-8k',3500, 8000),
        ('Air    8k-16k', 8000,16000),
    ]

    sep = '='*62
    print('')
    print(sep)
    print('  ' + label)
    print(sep)
    print(f'  Duration : {N/sr:.1f}s   SR={sr}Hz   Channels={d.shape[1]}')
    print(f'  Peak     : {peak_db:.2f} dBFS')
    print(f'  RMS      : {rms_db:.2f} dBFS')
    print(f'  Crest    : {crest_db:.1f} dB   (target EDM: 8-12 dB)')
    print(f'  DR (250ms): {dr:.1f} dB  (loudness range across track)')
    print(f'  Width    : {width:.3f}   (0=mono  0.2=narrow  0.5=normal  1.0=wide)')
    print(f'  Mono corr: {corr:.3f}   (>0.9=great  >0.7=ok  <0.5=phase issues)')
    print(f'  Centroid : {centroid:.0f} Hz   (EDM ref: ~3000-5000 Hz)')
    print('  --- Spectral balance ---')
    results = {}
    for name, lo, hi in bands:
        val = band(lo, hi)
        results[name] = val
        print(f'  {name}: {val:.1f} dB')
    bass_e  = band(60,  250)
    lowmid_e= band(250, 800)
    vocal_e = band(800, 3500)
    print(f'  Bass vs Vocal delta : {bass_e - vocal_e:+.1f} dB  (ref ~+8 to +12 dB)')
    print(f'  Bass vs LowMid delta: {bass_e - lowmid_e:+.1f} dB  (ref ~+2 to +6 dB)')

    return {'label':label,'peak':peak_db,'rms':rms_db,'crest':crest_db,'width':width,
            'centroid':centroid,'dr':dr,'corr':corr,
            'sub':band(20,60),'bass':bass_e,'lowmid':lowmid_e,
            'vocal':vocal_e,'himid':band(3500,8000),'air':band(8000,16000)}

orig = full_analysis(
    r'C:\Users\equat\Downloads\Transfinite (Agent WALL) Master.wav',
    'ORIGINAL  (Suno input, pre-processing)')

ref  = full_analysis(
    r'E:\SunoMaster\references\normalized reference tracks\# Guy J - Worlds Apart (Original Mix) Normalized -8 LUFS.wav',
    'REFERENCE (Guy J - Worlds Apart, -8 LUFS norm)')

out  = full_analysis(
    r'C:\Users\equat\Desktop\MUSIC OUTPUT\Latest Mastered Songs\Transfinite (Agent WALL) Master_master_v5.4.wav',
    'OUTPUT    (SunoMaster v5.4 + Hailey vocal)')

sep = '='*62
print('')
print(sep)
print('  DELTA TABLE  (Output vs Original  |  Output vs Reference)')
print(sep)
keys = ['peak','rms','crest','width','centroid','dr','corr',
        'sub','bass','lowmid','vocal','himid','air']
thresholds = {'peak':1,'rms':1,'crest':2,'width':0.08,'centroid':400,
              'dr':4,'corr':0.05,'sub':2,'bass':2,'lowmid':2,
              'vocal':2,'himid':2,'air':2}
for k in keys:
    dO = out[k] - orig[k]
    dR = out[k] - ref[k]
    thr = thresholds.get(k, 2)
    flag = '  <<< PROBLEM' if abs(dO) > thr else ''
    print(f'  {k:10s}  orig={orig[k]:8.2f}  ref={ref[k]:8.2f}  out={out[k]:8.2f}  '
          f'vs_orig={dO:+.2f}  vs_ref={dR:+.2f}{flag}')
