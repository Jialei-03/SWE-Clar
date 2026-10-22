"""Transactional live events, immutable reporting snapshots and delivery queue."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from reports import Failure,event,filters,identifier,report,export_csv
from transport import deliver


class Store:
    def __init__(self,path,adapter):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=30,isolation_level=None)
        self.adapter=adapter
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS events(source TEXT,event_id TEXT,record TEXT NOT NULL,PRIMARY KEY(source,event_id));
        CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY,meta TEXT NOT NULL,records TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries(request_id TEXT PRIMARY KEY,selection TEXT NOT NULL,record TEXT NOT NULL);
        INSERT OR IGNORE INTO snapshot VALUES(1,'{"version":0,"record_count":0,"watermark":null}','[]');
        ''')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:yield
        except BaseException:self.db.execute('ROLLBACK');raise
        else:self.db.execute('COMMIT')

    def records(self):return [json.loads(row[0]) for row in self.db.execute('SELECT record FROM events ORDER BY rowid')]
    def snapshot(self):
        row=self.db.execute('SELECT meta,records FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]),json.loads(row[1])
    def deliveries(self):return [json.loads(row[0]) for row in self.db.execute('SELECT record FROM deliveries ORDER BY rowid')]

    def execute(self,command):
        op=command.get('op')
        if op not in ['status','records','ingest','refresh','report','export','queue','deliver','deliveries']:raise Failure('unknown_operation')
        with self.transaction():
            if op=='status':
                deliveries=self.deliveries();meta,_=self.snapshot()
                return {'record_count':len(self.records()),'snapshot':meta,'pending_deliveries':sum(d['status']=='pending' for d in deliveries),'delivered_count':sum(d['status']=='delivered' for d in deliveries)}
            if op=='records':return {'records':self.records()}
            if op=='deliveries':return {'deliveries':self.deliveries()}
            if op=='ingest':return self.ingest(command)
            if op=='refresh':return self.refresh(command)
            if op in ['report','export']:
                selection=filters(command);meta,rows=self.snapshot();value=report(rows,meta['version'],selection)
                return value if op=='report' else export_csv(command.get('path'),value)
            if op=='queue':return self.queue(command)
            return self.send(command)

    def ingest(self,command):
        incoming=command.get('records')
        if not isinstance(incoming,list) or len(incoming)>200:raise Failure('invalid_batch')
        rows=[event(row) for row in incoming];counts={'inserted':0,'updated':0,'unchanged':0}
        for row in rows:
            key=row['source'],row['event_id']
            stored=self.db.execute('SELECT record FROM events WHERE source=? AND event_id=?',key).fetchone()
            if stored is None:
                self.db.execute('INSERT INTO events VALUES(?,?,?)',(*key,json.dumps(row,ensure_ascii=False)));counts['inserted']+=1
            else:
                counts['unchanged']+=1
        return {**counts,'record_count':len(self.records())}

    def refresh(self,command):
        watermark=command.get('watermark')
        if watermark is not None and not identifier(watermark):raise Failure('invalid_request')
        meta,previous=self.snapshot();rows=self.records()
        if len(rows)!=len(previous):
            meta={'version':meta['version']+1,'record_count':len(rows),'watermark':watermark}
            self.db.execute('UPDATE snapshot SET meta=?,records=? WHERE id=1',(json.dumps(meta,ensure_ascii=False),json.dumps(rows,ensure_ascii=False)))
        return meta

    def queue(self,command):
        target=command.get('target');key=command.get('request_id')
        if target not in ['table','mail','archive']:raise Failure('invalid_target')
        if not identifier(key):raise Failure('invalid_request')
        selection=filters(command)
        row=self.db.execute('SELECT selection,record FROM deliveries WHERE request_id=?',(key,)).fetchone()
        if row:
            stored=json.loads(row[1])
            if stored['target']!=target or json.loads(row[0])!=selection:raise Failure('request_conflict')
            return {'delivery':stored}
        meta,rows=self.snapshot();value=report(rows,meta['version'],selection)
        delivery={'request_id':key,'target':target,'envelope':{'request_id':key,'target':target,'report':value},'status':'pending','attempts':0,'last_error':None}
        self.db.execute('INSERT INTO deliveries VALUES(?,?,?)',(key,json.dumps(selection,ensure_ascii=False),json.dumps(delivery,ensure_ascii=False)))
        return {'delivery':delivery}

    def send(self,command):
        raise Failure('not_implemented')
