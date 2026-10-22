"""Render/operate the local application, or explicitly reset its disposable demo database."""
import argparse,base64,json,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from maintenance_support import run_session


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--origin',default='http://127.0.0.1:8080')
    parser.add_argument('--reset-demo',action='store_true')
    args=parser.parse_args()
    if args.reset_demo:
        if args.script or args.output:parser.error('Reset must be a separate explicit operation')
        if args.origin!='http://127.0.0.1:8080':parser.error('Demo reset is limited to the prepared development endpoint')
        service=runpy.run_path('/opt/sweclar/firestore_service.py')
        status,_=service['request'](args.origin,'DELETE','/emulator/v1/projects/demo-sweclar/databases/(default)/documents')
        if status!=200:raise RuntimeError('Demo reset failed')
        service['seed'](args.origin,json.loads(Path('/opt/sweclar/development_seed.json').read_text()))
        print(json.dumps({'reset':True}));return
    if not args.script or not args.output:parser.error('--script and --output are required')
    script=json.loads(args.script.read_text());result=run_session(script['operations'],origin=args.origin)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,encoded in result.pop('captures_base64').items():(args.output/name).write_bytes(base64.b64decode(encoded))
    (args.output/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'operations':len(result['observations'])}))


if __name__=='__main__':main()
