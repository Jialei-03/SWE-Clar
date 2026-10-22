import argparse,json,sys
from pathlib import Path
from sync_service import SyncService
from solution import process_cashless_action

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--server-db',default='runtime/server.db');args=parser.parse_args()
    path=Path(args.server_db);path.parent.mkdir(parents=True,exist_ok=True)
    request=json.load(sys.stdin);action=dict(request['action'])
    with SyncService(path) as service:
        if action.get('type')=='sync':action['sync_url']=service.url+'/sync'
        result=process_cashless_action(request['state'],action)
    print(json.dumps(result,allow_nan=False))
if __name__=='__main__':main()
