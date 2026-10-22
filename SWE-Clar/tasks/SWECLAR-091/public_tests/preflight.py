import shutil,subprocess,json
needed=['c++','cmake','wx-config','xvfb-run']
assert all(shutil.which(n) for n in needed),'Prepared GUI tools missing'
print(json.dumps({'ready':True,'compiler':subprocess.check_output(['c++','--version'],text=True).splitlines()[0],'wx':subprocess.check_output(['wx-config','--version'],text=True).strip(),'platform':'Linux C++11, not VS2013'}))
