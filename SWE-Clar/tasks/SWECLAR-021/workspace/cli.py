"""One bounded JSON response per physical input line; state persists in SQLite."""
import argparse
import json
import sys
from reports import Failure
from store import Store

LIMIT=262144


def commands(stream):
    while True:
        raw=stream.readline(LIMIT+1)
        if not raw:return
        if len(raw)>LIMIT:
            while raw and not raw.endswith(b'\n'):raw=stream.readline(LIMIT+1)
            yield None;continue
        try:
            value=json.loads(raw.decode('utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(value,dict):raise ValueError()
            yield value
        except (ValueError,UnicodeDecodeError):yield None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',required=True);parser.add_argument('--adapter',required=True)
    args=parser.parse_args();store=Store(args.db,args.adapter)
    try:
        for command in commands(sys.stdin.buffer):
            try:
                if command is None:raise Failure('invalid_request')
                result=store.execute(command)
                if command.get('op')=='deliver' and result['delivery']['status']=='pending':
                    output={'ok':False,'error':{'code':'delivery_failed'},**result}
                else:output={'ok':True,'result':result}
            except Failure as error:output={'ok':False,'error':{'code':error.code}}
            print(json.dumps(output,ensure_ascii=True,allow_nan=False),flush=True)
    finally:store.db.close()

if __name__=='__main__':main()
