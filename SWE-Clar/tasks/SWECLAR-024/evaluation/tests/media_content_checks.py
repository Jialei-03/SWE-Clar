"""Evaluator-side synthetic content oracle; no candidate schema or path assumptions."""
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess as sp

FF=os.environ.get('FFMPEG_BIN','ffmpeg')
FP=os.environ.get('FFPROBE_BIN','ffprobe')

def run(args, **kwargs):
    return sp.run(args,check=True,capture_output=True,timeout=30,**kwargs).stdout

def make_fixture(path, seed):
    rng=random.Random(seed)
    colors=[tuple(rng.randrange(32,224) for _ in range(3)) for _ in range(3)]
    frequency=rng.choice([330,440,550,660,770])
    args=[FF,'-nostdin','-v','error','-y']
    for color in colors:
        args+=['-f','lavfi','-i','color=c=0x%02x%02x%02x:s=192x128:r=15:d=2'%color]
    args+=['-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=48000:duration=6',
           '-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
           '-map','[v]','-map','3:a','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
           '-g','15','-c:a','aac','-movflags','+faststart',str(path)]
    run(args)
    return {'colors':colors,'frequency':frequency,'seconds':6,'width':192,'height':128,
            'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}

def inspect_content(path, fixture):
    info=json.loads(run([FP,'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)]))
    video=next((s for s in info['streams'] if s.get('codec_type')=='video'),None)
    audio=next((s for s in info['streams'] if s.get('codec_type')=='audio'),None)
    assert video is not None and audio is not None,'missing submitted video or audio'
    assert float(info['format']['duration']) >= fixture['seconds']-.5,'truncated input'
    assert float(info['format']['duration']) <= fixture['seconds']+.7,'unexpected replacement duration'
    observed=[]
    for position,expected in zip([1,3,5],fixture['colors']):
        raw=run([FF,'-nostdin','-v','error','-ss',str(position),'-i',str(path),'-frames:v','1',
                 '-vf','scale=16:16','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
        assert len(raw)==16*16*3,'missing expected image'
        means=[sum(raw[i::3])/256 for i in range(3)]
        assert all(abs(a-b)<22 for a,b in zip(means,expected)),'recorded imagery differs from submitted sequence'
        observed.append(means)
    pcm=run([FF,'-nostdin','-v','error','-ss','1','-i',str(path),'-t','1','-vn','-ac','1','-ar','16000','-f','s16le','pipe:1'])
    samples=array('h',pcm)
    import sys
    if sys.byteorder!='little':samples.byteswap()
    assert len(samples)>=15000,'submitted audio truncated'
    rms=math.sqrt(sum(float(x)*x for x in samples)/len(samples))
    assert rms>100,'submitted audio replaced with silence'
    crossings=sum(a<=0<b for a,b in zip(samples,samples[1:]))
    frequency=crossings/(len(samples)/16000)
    assert abs(frequency-fixture['frequency'])<12,'recorded audio differs from submitted tone'
    run([FF,'-nostdin','-v','error','-xerror','-i',str(path),'-f','null','-'])
    return {'duration':float(info['format']['duration']),'frames':int(video['nb_read_frames']),'colors':observed,'frequency':frequency,'audio_rms':rms,'full_decode':True}
