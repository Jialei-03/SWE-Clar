from pathlib import Path
assert all(Path(n).is_file() for n in ['index.html','dashboard.js','dashboard.css','data.js','vendor/bootstrap.min.css'])
print('Public local page assets present')
