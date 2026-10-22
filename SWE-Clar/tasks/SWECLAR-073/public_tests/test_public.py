import subprocess,sys
p=subprocess.run([sys.executable,'cli.py','--help'],capture_output=True,text=True,check=True);assert '--source' in p.stdout and '--destination' in p.stdout;print('Public migration CLI entry passed')
