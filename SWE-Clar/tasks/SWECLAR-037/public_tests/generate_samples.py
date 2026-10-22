"""Generate independent tiny videos before candidate work begins."""
from pathlib import Path
import json,subprocess,sys
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
for kind in ['detection','neutral','recording']:
 frames=[]
 for i in range(40):
  frame=bytearray(bytes((20,40+i*3,70) if kind=='recording' else (0,0,0))*(96*64))
  if kind=='detection' and i in [10,30]:
   for y in range(20,35):
    for x in range(65,80):frame[(y*96+x)*3:(y*96+x)*3+3]=bytes((255,0,0))
  frames.append(bytes(frame))
 subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','96x64','-r','5','-i','-','-an','-c:v','mpeg4','-threads','1','-q:v','1','-map_metadata','-1',str(root/(kind+'.mp4'))],input=b''.join(frames),capture_output=True,check=True,timeout=20)
print(json.dumps({'generated':3,'synthetic':True}))
