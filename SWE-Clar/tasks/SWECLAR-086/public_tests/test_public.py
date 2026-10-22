import ast
from pathlib import Path
for name in ['main.py','itinerary_generator.py','place_service.py']:ast.parse(Path(name).read_text())
print('Public streaming sources parsed')
