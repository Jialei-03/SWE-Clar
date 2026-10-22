"""Start the provided local runtime with a writable demo area and a clean environment."""
import argparse,os,sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--root',default='/tmp/comfy-demo');parser.add_argument('--port',type=int,default=8188);a=parser.parse_args();root=Path(a.root).resolve()
for name in ['input','output','temp','user']:(root/name).mkdir(parents=True,exist_ok=True)
command=[sys.executable,'/opt/comfy/main.py','--cpu','--fp16-unet','--fp16-text-enc','--fp32-vae','--cache-none','--disable-auto-launch','--listen','127.0.0.1','--port',str(a.port),'--input-directory',str(root/'input'),'--output-directory',str(root/'output'),'--temp-directory',str(root/'temp'),'--user-directory',str(root/'user')]
env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
os.execve(sys.executable,command,env)
