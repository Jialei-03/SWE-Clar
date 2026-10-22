import ast
from pathlib import Path
for name in ['solution.py','server.py','studio_client.py']:ast.parse(Path(name).read_text())
print('Public studio sources parsed')
