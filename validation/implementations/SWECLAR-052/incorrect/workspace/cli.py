"""JSON stdin: {state, events, config}; stdout: final state."""
import json,sys
from solution import process_smartlink_event
from smartlink_client import SmartlinkClient
def main():
    request=json.load(sys.stdin);state=request.get('state',{})
    client=SmartlinkClient(**request['config']) if request.get('config') else None
    for event in request['events']:state=process_smartlink_event(state,event,client)
    print(json.dumps(state,allow_nan=False))
if __name__=='__main__':main()
