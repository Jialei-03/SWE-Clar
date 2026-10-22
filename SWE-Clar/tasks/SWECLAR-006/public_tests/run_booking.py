"""Render and operate the real Flutter component from a public JSON session."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import argparse,base64,json,pathlib
from booking_support import run_session


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script',type=pathlib.Path,required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args();script=json.loads(args.script.read_text())
    if args.output.exists() and any(args.output.iterdir()):raise SystemExit('Choose an empty output directory to preserve previous observations')
    result=run_session(script['operations'],initial=script.get('initial'),actor=script.get('actor','member'),platform=script.get('platform','android'))
    args.output.mkdir(parents=True,exist_ok=True)
    for name,data in result.pop('captures_base64').items():(args.output/name).write_bytes(base64.b64decode(data))
    (args.output/'observations.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'completed':True,'output':str(args.output),'operations':len(result['observations'])}))


if __name__=='__main__':main()
