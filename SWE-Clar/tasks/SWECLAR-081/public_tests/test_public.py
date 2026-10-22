import ast
from pathlib import Path
for n in ['directory_planner.py','cli.py']:ast.parse(Path(n).read_text())
print('Public Python source check passed')
