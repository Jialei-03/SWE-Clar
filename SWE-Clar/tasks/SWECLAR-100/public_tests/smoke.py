import ast
from pathlib import Path
for name in ['server.py','store.py']:ast.parse(Path(name).read_text())
print('Public Python syntax passed')
