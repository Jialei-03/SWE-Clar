import ast
from pathlib import Path
for name in ['solution.py','transcriber.py','translation_client.py','cli.py']:ast.parse(Path(name).read_text())
assert Path('/opt/sweclar/whisper-cli').is_file() and Path('/opt/sweclar/ggml-tiny.en.bin').stat().st_size>70000000
print('Public classroom source and full model availability passed')
