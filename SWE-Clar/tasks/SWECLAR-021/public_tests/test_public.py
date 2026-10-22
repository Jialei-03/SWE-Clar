"""Visible real CLI ingestion, snapshot and CSV regression; no hidden policy oracle."""
import csv,io,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pipeline_support import Pipeline

def run():
    with Pipeline() as pipe:
        event={'source':'sales','event_id':'event-a','customer_id':'Synthetic, "Account"','booking_id':'booking-a','amount_cents':1200,'date':'2024-02-29','revision':0}
        rows=pipe.run([{'op':'status'},{'op':'ingest','records':[event]},{'op':'records'},{'op':'report'},{'op':'refresh'},{'op':'report'},{'op':'export','path':str(pipe.project/'result.csv')}])
        assert len(rows)==7 and all(r['ok'] is True for r in rows)
        assert rows[0]['result']['record_count']==0 and rows[0]['result']['snapshot']['version']==0
        assert rows[2]['result']['records']==[event]
        assert rows[3]['result']['event_count']==0
        assert rows[5]['result']['event_count']==1 and rows[5]['result']['total_cents']==1200
        parsed=list(csv.reader(io.StringIO(pipe.read('result.csv'))))
        assert parsed==[['customer_id','booking_id','event_count','total_cents'],[event['customer_id'],'booking-a','1','1200']]
        again=pipe.run([{'op':'records'},{'op':'report'}]);assert again[0]['result']['records']==[event] and again[1]['result']['total_cents']==1200
        framing=pipe.run(raw=b'bad\n\n{"op":"status"}\n');assert len(framing)==3 and not framing[0]['ok'] and not framing[1]['ok'] and framing[2]['ok']
    return {'passed':True,'scope':'Visible streaming CLI, actual durable snapshot and parsed CSV baseline only'}

if __name__=='__main__':print(json.dumps(run()))
