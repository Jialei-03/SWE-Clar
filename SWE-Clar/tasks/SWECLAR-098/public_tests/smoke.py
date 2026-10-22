from pathlib import Path
for name in ['index.html','cookie-policy.html','css/site.css','js/navigation.js']:assert Path(name).is_file()
print('Two-page local sources available')
