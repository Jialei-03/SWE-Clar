"""Run the supplied synthetic archive through the actual PDF entry point."""
from pathlib import Path
import sys,json
root=Path.cwd();sys.path.insert(0,str(root));from solution import build_article_package
params={'title':'Synthetic reading collection','start_date':'2030-01-01','end_date':'2030-12-31','include_summaries':True}
print(json.dumps(build_article_package(params,'local-example',root/'output',fetch_text=lambda url:(root/'example.html').read_text())))
