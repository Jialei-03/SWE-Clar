from pathlib import Path
import json,subprocess,hashlib,tempfile,shutil,math
from urllib.request import Request,urlopen
from src.goal_policy import detect_goal_events

def probe(path,ffprobe='ffprobe'):
    p=subprocess.run([ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate:format=duration','-of','json',str(path)],capture_output=True,text=True,timeout=10,check=True)
    d=json.loads(p.stdout);s=d['streams'][0];n,den=s['avg_frame_rate'].split('/');fps=float(n)/float(den)
    duration=float(d['format']['duration']);w=s['width'];h=s['height']
    if not 0<fps<=60 or not 0<duration<=30 or not 0<w<=640 or not 0<h<=480:raise ValueError('video outside benchmark limits')
    return w,h,fps,duration

def observations(video,line_x,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    w,h,fps,duration=probe(video,ffprobe)
    if not isinstance(line_x,(int,float)) or isinstance(line_x,bool) or not math.isfinite(line_x) or not 0<=line_x<w:raise ValueError('invalid line')
    p=subprocess.run([ffmpeg,'-v','error','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30,check=True)
    size=w*h*3
    if not p.stdout or len(p.stdout)%size:raise ValueError('invalid frames')
    rows=[]
    for i,start in enumerate(range(0,len(p.stdout),size)):
        rgb=p.stdout[start:start+size];xs=[]
        for offset in range(0,size,3):
            r,g,b=rgb[offset:offset+3]
            if r>160 and g<90 and b<90:xs.append((offset//3)%w)
        rows.append({'timestamp':i/fps,'goal_candidate':bool(xs) and sum(xs)/len(xs)>=line_x})
    return rows

def run_pipeline(detection_video,recording_video,output_dir,line_x,delivery_url,*,cooldown_seconds=5.0,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    output=Path(output_dir)
    if output.exists():raise ValueError('output exists')
    if not isinstance(cooldown_seconds,(int,float)) or isinstance(cooldown_seconds,bool) or not math.isfinite(cooldown_seconds) or cooldown_seconds<0:raise ValueError('invalid cooldown')
    width,height,fps,duration=probe(recording_video,ffprobe)
    observations_list=observations(detection_video,line_x,ffmpeg,ffprobe)
    triggers=detect_goal_events(observations_list,cooldown_seconds=cooldown_seconds)
    if any(t>=duration for t in triggers):raise ValueError('recording does not cover trigger')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.clips-',dir=output.parent) as tmp:
        stage=Path(tmp);clips=[]
        for index,t in enumerate(triggers):
            start=max(0,t-5);end=min(duration,t+2);name=f'clip-{index:03}.mp4';dest=stage/name
            raise NotImplementedError('Create and deliver the clip')
            clips.append({'file':name,'trigger':t,'start':start,'end':end,'sha256':digest})
        (stage/'manifest.json').write_text(json.dumps({'clips':clips},sort_keys=True))
        stage.rename(output)
    return {'clips':clips}
