"""Published real C foundation regression; no hidden business policy oracle."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_support import Project,PUBLIC

def main():
    results=[]
    for sanitized in (False,True):
        with Project() as project:
            project.build(sanitized)
            demo=json.loads(project.execute([project.path/'build/graph_demo']))
            assert demo.get('ok') is True and demo.get('nodes')==2 and demo.get('edges')==1
            driver=project.driver(PUBLIC/'test_graph.c')
            assert json.loads(project.execute([driver]))['passed'] is True
            results.append({'sanitized':sanitized,'passed':True})
    print(json.dumps({'passed':True,'scope':'Visible lifecycle, owned node strings, directed/undirected edges and actual demo','builds':results}))
if __name__=='__main__':main()
