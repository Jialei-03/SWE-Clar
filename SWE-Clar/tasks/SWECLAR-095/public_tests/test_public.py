from pathlib import Path
assert all(Path(n).is_file() for n in ['server.py','App.jsx','build.mjs','index.html'])
print('Actual React/service starter files available')
