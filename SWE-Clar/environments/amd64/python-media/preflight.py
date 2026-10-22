"""Independent tool capability check. No task answers or customer materials."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess as sp
import sys
import tempfile
import time
import urllib.request

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def user():return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}

web=json.loads(sp.check_output([sys.executable,'-I','/opt/sweclar/web_preflight.py'],text=True));assert web['passed']
root=Path(tempfile.mkdtemp(prefix='media-health-'));root.chmod(0o755)
recordings=root/'recordings';recordings.mkdir()
if os.geteuid()==0:os.chown(recordings,1000,1000)
rtmp,hls=port(),port()
config={'rtsp':False,'webrtc':False,'srt':False,'moq':False,'rtmpAddress':f'127.0.0.1:{rtmp}','hlsAddress':f'127.0.0.1:{hls}',
    'hlsVariant':'mpegts','hlsAlwaysRemux':True,'hlsSegmentDuration':'1s',
    'pathDefaults':{'record':True,'recordPath':str(recordings/'%path/%Y-%m-%d_%H-%M-%S-%f'),'recordDeleteAfter':'0s'},'paths':{'sample':{}}}
cfg=root/'config.json';cfg.write_text(json.dumps(config));cfg.chmod(0o644)
log=(root/'service.log').open('w');service=publisher=None
try:
    service=sp.Popen(['mediamtx',str(cfg)],stdout=log,stderr=log,**user())
    deadline=time.monotonic()+10
    while True:
        assert service.poll() is None,'Media service exited'
        try:
            with socket.create_connection(('127.0.0.1',rtmp),timeout=.2):break
        except OSError:
            if time.monotonic()>deadline:raise
            time.sleep(.1)
    publisher=sp.Popen(['ffmpeg','-nostdin','-v','error','-re','-f','lavfi','-i','testsrc2=s=160x120:r=15',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','8','-c:v','libx264','-preset','ultrafast','-g','15',
        '-pix_fmt','yuv420p','-c:a','aac','-f','flv',f'rtmp://127.0.0.1:{rtmp}/sample'],stdout=sp.PIPE,stderr=sp.PIPE,**user())
    url=f'http://127.0.0.1:{hls}/sample/index.m3u8';deadline=time.monotonic()+10
    while True:
        try:
            with urllib.request.urlopen(url,timeout=2) as response:assert b'#EXTM3U' in response.read()
            break
        except Exception:
            if time.monotonic()>deadline:raise
            time.sleep(.1)
    frames=sp.check_output(['ffmpeg','-nostdin','-v','error','-i',url,'-frames:v','3','-an','-vf','scale=16:16','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],timeout=15)
    assert len(frames)==16*16*3*3
    _,err=publisher.communicate(timeout=15);assert publisher.returncode==0,err[-300:]
    service.terminate();service.wait(timeout=10)
    files=list(recordings.rglob('*.mp4'));assert files
    meta=json.loads(sp.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(files[0])],text=True))
    assert {'video','audio'}<={s['codec_type'] for s in meta['streams']}
    assert float(meta['format']['duration'])>7
    sp.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(files[0]),'-f','null','-'],check=True,capture_output=True,timeout=15)
    browser_health=json.loads(sp.check_output([sys.executable,'-I','/opt/sweclar/browser_health.py',str(files[0])],text=True,timeout=30,env=dict(os.environ,HOME=str(recordings)),**user()))
    assert browser_health['passed']
    print(json.dumps({'passed':True,'web_preflight':web,'browser_media':browser_health,'mediamtx':sp.check_output(['mediamtx','--version'],text=True).strip(),
        'ffmpeg':sp.check_output(['ffmpeg','-version'],text=True).splitlines()[0],'rtmp_hls_recording':True,'media_service_uid':1000,
        'recorded_seconds':float(meta['format']['duration']),'synthetic_media_only':True,'network':'loopback only'}))
finally:
    for process in [publisher,service]:
        if process and process.poll() is None:process.kill();process.wait()
    log.close()
    sp.run([sys.executable,'-I','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]',str(recordings)],**user(),check=True)
    shutil.rmtree(root)
