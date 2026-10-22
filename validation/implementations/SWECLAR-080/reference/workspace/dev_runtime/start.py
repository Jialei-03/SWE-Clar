"""Report the preflight-started local WordPress service."""
import json,urllib.request
from pathlib import Path
r=json.loads(Path('/workspace/runtime/ready.json').read_text());url=r['url']+'/?directory_page=members'
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=5) as response:assert response.status==200
print(url)
