import argparse,json,sys
from pathlib import Path
from local_service import LocalService
from pipeline_client import PipelineClient
from solution import process_pipeline_event

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',default='runtime/provider.db');args=parser.parse_args()
    path=Path(args.database);path.parent.mkdir(parents=True,exist_ok=True)
    request=json.load(sys.stdin);rows=json.loads(Path(__file__).with_name('source.json').read_text())
    with LocalService(path,rows) as provider:
        client=PipelineClient({'source':provider.url+'/source'},{'destination':provider.url+'/destination'},provider.url+'/outreach',provider.token)
        result=process_pipeline_event(request['state'],request['event'],client)
    print(json.dumps(result,allow_nan=False))
if __name__=='__main__':main()
