import pathlib,ast
for p in ['store.py','server.py']:ast.parse(pathlib.Path(p).read_text())
assert pathlib.Path('vendor/leaflet.js').is_file()
print('Server sources and bundled Leaflet available')
