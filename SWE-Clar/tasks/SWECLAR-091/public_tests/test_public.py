from pathlib import Path
assert Path('CMakeLists.txt').is_file()
assert all(Path('src',n).is_file() for n in ['MainWindowM.h','MainWindowV.h','MainWindowC.h','MainWindowG.h'])
print('Public native project material check passed')
