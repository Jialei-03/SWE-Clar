"""Neutral unprivileged file reader for files produced by submitted code."""
import os,sys,base64
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
print(base64.b64encode(open(sys.argv[1],'rb').read()).decode())
