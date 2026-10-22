"""Generate an independently composed MIDI exercise and matching synthetic video."""
from pathlib import Path
import math,struct,wave,subprocess,os,json,sys
root=Path(sys.argv[1]);root.mkdir(exist_ok=True)
notes=[60,64,67,72];tempo=500000;ppq=480

def vlq(value):
 out=[value&127];value>>=7
 while value:out.insert(0,(value&127)|128);value>>=7
 return bytes(out)
track=b'\x00\xff\x51\x03'+tempo.to_bytes(3,'big')
for i,pitch in enumerate(notes):track+=vlq(192 if i else 0)+bytes([0x90,pitch,90])+vlq(960)+bytes([0x80,pitch,0])
track+=b'\x00\xff\x2f\x00';(root/'demo.mid').write_bytes(b'MThd'+struct.pack('>IHHH',6,0,1,ppq)+b'MTrk'+struct.pack('>I',len(track))+track)
rate=24000;pcm=bytearray()
for i in range(rate*6):
 t=i/rate;index=int(t/1.2);local=t-index*1.2;v=0
 if index<len(notes) and local<1:
  envelope=min(1,local/.015,(1-local)/.015);v=int(8000*max(0,envelope)*math.sin(2*math.pi*440*2**((notes[index]-69)/12)*local))
 pcm+=struct.pack('<h',v)
with wave.open(str(root/'demo.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm)
subprocess.run([os.environ.get('FFMPEG_BIN','ffmpeg'),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=20','-i',str(root/'demo.wav'),'-t','6','-c:v','libvpx-vp9','-deadline','realtime','-cpu-used','8','-pix_fmt','yuv420p','-c:a','libopus',str(root/'demo.webm')],check=True)
(root/'demo.wav').unlink();(root/'config.json').write_text(json.dumps({'charts':[{'id':'exercise','title':'Synthetic practice exercise','midi':'runtime/demo.mid','recording':'runtime/demo.webm'}]},indent=2)+'\n')
