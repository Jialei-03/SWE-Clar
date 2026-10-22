"""Private semantic oracle communicating only through public unprivileged C ABI."""
from collections import deque
import csv
import io
import json
import math
import os
from pathlib import Path
import sys
sys.path.insert(0,'/public_tests')
from native_support import Project,run,PUBLIC,read_artifact
from bridge_support import Bridge,encode,decode

class Checks:
    def __init__(self):self.count=0
    def require(self,value,message):
        if not value:raise AssertionError(message)
        self.count+=1

def lifecycle(c):
    for sanitized in (False,True):
        with Project() as project:
            project.build(sanitized)
            demo=json.loads(project.execute([project.path/'build/graph_demo']))
            c.require(demo.get('ok') is True and demo.get('nodes')==2 and demo.get('edges')==1,'Actual demo result')
            with Bridge(project) as one,Bridge(project) as two:
                c.require(one.call('counts')==[0,0],'NULL graph counts')
                c.require(one.call('destroy') is True,'NULL destruction')
                c.require(one.call('create',1) and two.call('create',0),'Both directedness modes construct')
                c.require(one.call('counts')==two.call('counts')==[0,0],'Initially empty independent graphs')
                identity=one.call('add',encode('first'))
                c.require(identity!=0 and two.call('counts')==[0,0],'Independent instances')
                c.require(one.call('destroy') and one.call('create',1) and one.call('counts')==[0,0],'Destroy and fresh lifecycle')
            if not sanitized:
                observer=project.path/'build/observer.o'
                compiled=run(['cc',*project.flags,'-I'+str(project.path/'include'),'-c',PUBLIC/'measurement_probe.c','-o',observer],project.path)
                c.require(compiled.returncode==0,'Public ABI observer compiles')
                symbols=['fcb_graph_add_node','fcb_graph_get_node','fcb_graph_update_node','fcb_graph_remove_node','clock_gettime']
                linked=run(['make','-B','all','CFLAGS='+' '.join(project.flags),'LDFLAGS='+str(observer)+' '+' '.join('-Wl,--wrap='+symbol for symbol in symbols)+' '+str(project.path/'build/libfcb_graph.a')],project.path)
                c.require(linked.returncode==0,'Documented linker overrides work: '+linked.stderr)
                log=project.path/'demo-observation.json'
                observed=run([project.path/'build/graph_demo'],project.path,extra_env={'GRAPH_PROBE_LOG':str(log)})
                c.require(observed.returncode==0 and log.is_file(),'Demo actually calls graph ABI')
                calls=json.loads(read_artifact(project,log));c.require(calls['add']==3 and calls['update']>=1 and calls['delete']==1,'Demo actually mutates graph before reporting')
                failed=run([project.path/'build/graph_demo'],project.path,extra_env={'GRAPH_PROBE_FAIL_ADD':'1','GRAPH_PROBE_LOG':str(log)})
                c.require(failed.returncode!=0,'Demo checks failed operations instead of printing fixed success')


def nodes(c):
    with Project() as project:
        project.build(True)
        with Bridge(project) as b:
            c.require(b.call('create',1),'Create')
            values=['','Case Sensitive','line\nquote " 雨','x'*4096]
            ids=[b.call('add',encode(value)) for value in values]
            c.require(all(type(i) is int and i>0 for i in ids) and len(set(ids))==len(ids),'Nonzero unique opaque IDs')
            c.require(b.call('counts')==[4,0],'Node count')
            for identity,value in zip(ids,values):c.require(decode(b.call('get',identity))==value,'Copied exact bytes')
            c.require(b.call('hold_node',ids[0])=='','Borrow empty value')
            c.require(b.call('update',ids[1],encode('new')),'Update other node')
            c.require(b.call('held')=='','Other mutation preserves borrowed pointer')
            c.require(b.call('node_alias',ids[2]),'Self borrowed update')
            c.require(decode(b.call('get',ids[2]))==values[2],'Alias preserves bytes')
            for value in (None,'z'*4097):
                c.require(b.call('add',encode(value))==0,'Invalid add fails')
                c.require(b.call('update',ids[1],encode(value)) is False,'Invalid update fails')
            c.require(decode(b.call('get',ids[1]))=='new' and b.call('counts')==[4,0],'Failure leaves state unchanged')
            c.require(b.call('remove',ids[2]) and b.call('get',ids[2]) is None,'Remove')
            c.require(b.call('remove',ids[2]) is False and b.call('update',0,encode('x')) is False,'Missing mutation')
            added=b.call('add',encode('replacement'));c.require(added not in [ids[0],ids[1],ids[3]] and added!=0,'New ID does not alias live node')

def edges(c):
    with Project() as project:
        project.build(True)
        with Bridge(project) as b:
            for directed in (0,1):
                c.require(b.call('create',directed),'Create')
                a,d,e=[b.call('add',encode(x)) for x in ('A','B','C')]
                c.require(b.call('edge_add',a,d,encode('label\n雨')),'Add relationship')
                c.require(b.call('edge_add',a,d,encode('duplicate')) is False,'Duplicate ordered pair rejected')
                if directed:
                    c.require(b.call('edge_get',d,a) is None and b.call('edge_add',d,a,encode('reverse')),'Directed reverse distinct')
                else:
                    c.require(decode(b.call('edge_get',d,a))=='label\n雨','Undirected reverse lookup')
                    c.require(b.call('edge_add',d,a,encode('reverse')) is False,'Undirected reverse duplicate')
                c.require(b.call('hold_edge',a,d)==encode('label\n雨'),'Borrow label')
                c.require(b.call('update',e,encode('changed')) and decode(b.call('held'))=='label\n雨','Other mutation preserves edge label')
                c.require(b.call('edge_alias',a,d),'Aliased label update')
                c.require(b.call('edge_update',a,d,encode('')) and b.call('edge_get',a,d)=='','Empty label valid')
                for invalid in (None,'x'*4097):c.require(b.call('edge_update',a,d,encode(invalid)) is False,'Invalid label rejected')
                c.require(b.call('edge_add',a,0,encode('x')) is False,'Missing endpoint rejected')
                c.require(b.call('edge_add',a,a,encode('loop')) and b.call('edge_add',d,e,encode('survives')),'Self loop and unrelated edge')
                c.require(b.call('remove',a) and b.call('counts')==[2,1],'Incident edges removed once')
                c.require(decode(b.call('edge_get',d,e))=='survives','Unrelated edge remains')
                c.require(b.call('edge_remove',d,e) and b.call('edge_remove',d,e) is False,'Edge removal and missing replay')

def legal_order(adjacency,start,actual,kind):
    if len(actual)!=len(set(actual)) or not actual or actual[0]!=start:return False
    if any(node not in adjacency for node in actual):return False
    rank={node:i for i,node in enumerate(actual)}
    neighbors=lambda node:sorted(adjacency[node],key=lambda n:(rank.get(n,len(actual)),n))
    seen={start};expected=[]
    if kind=='bfs':
        queue=deque([start])
        while queue:
            node=queue.popleft();expected.append(node)
            for following in neighbors(node):
                if following not in seen:seen.add(following);queue.append(following)
    else:
        expected=[start];stack=[(start,iter(neighbors(start)))]
        while stack:
            node,iterator=stack[-1]
            following=next(iterator,None)
            if following is None:stack.pop();continue
            if following not in seen:
                seen.add(following);expected.append(following);stack.append((following,iter(neighbors(following))))
    return expected[:len(actual)]==actual

def traversal(c):
    with Project() as project:
        project.build(True)
        with Bridge(project) as b:
            for directed in (0,1):
                b.call('create',directed);ids=[b.call('add',encode(str(i))) for i in range(8)];adj={i:set() for i in ids}
                for first,second in [(0,1),(0,2),(1,3),(2,4),(3,5),(4,5),(5,0),(1,1),(6,7)]:
                    a,d=ids[first],ids[second];c.require(b.call('edge_add',a,d,encode('edge')),'Traversal fixture edge')
                    adj[a].add(d)
                    if not directed:adj[d].add(a)
                for kind in ('bfs','dfs'):
                    for capacity in (1,2,4,8):
                        result=b.call(kind,ids[0],capacity)
                        c.require(result['bounded'] and result['tail_untouched'],'Traversal output bounds')
                        c.require(result['count']==min(6,capacity),'Exactly reachable prefix length')
                        c.require(legal_order(adj,ids[0],result['ids'],kind),'Legitimate '+kind+' order without reference ties')
                    for start,capacity,null in [(0,8,False),(ids[0],0,False),(ids[0],8,True)]:
                        result=b.call(kind,start,capacity,*(['null'] if null else []));c.require(result['count']==0 and result['tail_untouched'],'Null/missing/zero-capacity traversal')
                c.require(b.call('counts')==[8,9],'Traversal leaves graph unchanged')
            b.call('create',1);chain=[b.call('add',encode('n')) for _ in range(10000)]
            for a,d in zip(chain,chain[1:]):c.require(b.call('edge_add',a,d,encode('e')),'Chain edge')
            c.require(b.call('dfs',chain[0],10000)['ids']==chain,'Deep DFS actual ordered chain')
            c.require(b.call('bfs',chain[0],10000)['ids']==chain,'Full BFS actual ordered chain')
            c.require(b.call('bfs',chain[-1],10000)['ids']==[chain[-1]],'Directed sink cannot reach incoming node')

def write_bytes(project,path,contents):
    result=run([sys.executable,'-I','-c','from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))',path,contents.hex()],project.path)
    assert result.returncode==0,result.stderr

def persistence(c):
    with Project() as project:
        project.build(True)
        for directed in (0,1):
            saved=project.path/f'snapshot {directed} 雨.dat'
            with Bridge(project) as b:
                b.call('create',directed)
                values=['A\n"雨','','deleted','long'*1000];ids=[b.call('add',encode(value)) for value in values]
                c.require(b.call('remove',ids[2]),'Deleted gap')
                c.require(b.call('edge_add',ids[0],ids[1],encode('label\n')) and b.call('edge_add',ids[0],ids[0],encode('')),'Snapshot edges')
                c.require(b.call('save',encode(None)) is False,'NULL save path')
                c.require(b.call('save',encode(str(project.path/'missing-dir'/'x'))) is False,'Unwritable destination fails')
                c.require(b.call('save',encode(str(saved))),'Real save')
                c.require(b.call('update',ids[0],encode('changed after save')),'Original later mutation')
            c.require(saved.is_file() and saved.stat().st_size>0,'Actual disk bytes')
            with Bridge(project) as b:
                c.require(b.call('load',encode(str(saved))),'Fresh-process load')
                c.require(b.call('counts')==[3,2],'Restored counts')
                for index in (0,1,3):c.require(decode(b.call('get',ids[index]))==values[index],'IDs and bytes restored independent of later mutation')
                c.require(b.call('get',ids[2]) is None,'Deleted node remains absent')
                c.require(decode(b.call('edge_get',ids[0],ids[1]))=='label\n','Restored edge label')
                reverse=b.call('edge_get',ids[1],ids[0]);c.require(reverse is None if directed else decode(reverse)=='label\n','Restored directedness')
                added=b.call('add',encode('new'));c.require(added and added not in [ids[0],ids[1],ids[3]],'Loaded allocation does not collide')
                raw=read_artifact(project,saved)
                for data in [b'',b'not a valid graph',raw[:1],raw[:len(raw)//2],raw[:-1]]:
                    broken=project.path/'broken.dat';write_bytes(project,broken,data)
                    c.require(b.call('load',encode(str(broken))) is False,'Reject invalid/truncated snapshot')
                c.require(b.call('counts')==[4,2],'Failed load did not replace current handle')
            with Bridge(project) as b:
                b.call('create',directed);c.require(b.call('save',encode(str(saved))),'Empty graph save')
            with Bridge(project) as b:c.require(b.call('load',encode(str(saved))) and b.call('counts')==[0,0],'Empty graph roundtrip')

def measurement(c):
    with Project() as project:
        project.build(False);binary=project.path/'build/graph_bench'
        for count in (1,17,200):
            output=project.path/'metrics 雨.csv';result=run([binary,'--output',output,'--runs',count],project.path)
            c.require(result.returncode==0 and not result.stderr,'Measurement succeeds')
            summary=json.loads(result.stdout);c.require(summary.get('ok') is True and summary.get('runs')==count and summary.get('rows')==4,'Measurement stdout schema')
            with io.StringIO(read_artifact(project,output).decode('utf-8'),newline='') as handle:
                reader=csv.DictReader(handle);rows=list(reader)
                c.require(reader.fieldnames==['operation','runs','avg_us','min_us','max_us','cpu_seconds','peak_rss_kib'],'CSV columns')
            c.require([row['operation'] for row in rows]==['create','read','update','delete'],'Actual four ordered CSV rows')
            for row in rows:
                c.require(int(row['runs'])==count,'Actual run count')
                average,minimum,maximum,cpu=[float(row[key]) for key in ['avg_us','min_us','max_us','cpu_seconds']]
                c.require(all(math.isfinite(value) and value>=0 for value in [average,minimum,maximum,cpu]) and minimum<=average<=maximum,'Finite ordered measurements')
                c.require(int(row['peak_rss_kib'])>=0,'Peak RSS integer')
        for args in [[],['--runs','0','--output','bad.csv'],['--runs','-1','--output','bad.csv'],['--runs','1.5','--output','bad.csv'],['--runs','10001','--output','bad.csv'],['--runs','1','--runs','2','--output','bad.csv'],['--runs','1','--output',''],['--runs','1','--output',str(project.path/'no-parent'/'out.csv')]]:
            result=run([binary,*args],project.path);c.require(result.returncode!=0,'Invalid measurement invocation fails')
        instrumented=project.path/'build/graph_bench'
        symbols=['fcb_graph_add_node','fcb_graph_get_node','fcb_graph_update_node','fcb_graph_remove_node','clock_gettime']
        probe=project.path/'measurement-probe.o'
        built=run(['cc',*project.flags,'-I'+str(project.path/'include'),'-c',PUBLIC/'measurement_probe.c','-o',probe],project.path)
        c.require(built.returncode==0,'Public ABI probe compiles')
        # Retain the candidate Makefile's complete dependency graph and helper objects.
        # CC/CFLAGS/LDFLAGS overrides are already part of the public build interface.
        # Repeat the archive after the probe: __real references may first appear
        # here when the candidate puts LDFLAGS after its normal archive input.
        flags=' '.join([str(probe),str(project.path/'build/libfcb_graph.a'),*['-Wl,--wrap='+symbol for symbol in symbols]])
        built=run(['make','-B','all','CFLAGS='+' '.join(project.flags),'LDFLAGS='+flags],project.path)
        c.require(built.returncode==0,'Candidate benchmark target links through the public C ABI')
        log=project.path/'calls.json';output=project.path/'instrumented.csv';count=7
        result=run([instrumented,'--runs',count,'--output',output],project.path,extra_env={'GRAPH_PROBE_LOG':str(log),'GRAPH_PROBE_DELAY_NS':'2000000'})
        c.require(result.returncode==0 and not result.stderr,'Instrumented benchmark succeeds')
        calls=json.loads(read_artifact(project,log))
        c.require(calls['add']==calls['update']==calls['delete']==count and calls['read']>=2*count,'Actual CRUD and updated-value validation calls')
        c.require(calls['monotonic']>=8*count and calls['cpu']>=8,'Per-call wall time and per-phase process CPU measured')
        with io.StringIO(read_artifact(project,output).decode('utf-8'),newline='') as handle:rows=list(csv.DictReader(handle))
        c.require(len(rows)==4,'Instrumented CSV four phases')
        for row in rows:c.require(float(row['min_us'])>=1900,'Measured interval includes controlled 2ms API work, not a timing formula')
        failed=run([instrumented,'--runs',3,'--output',project.path/'failed.csv'],project.path,extra_env={'GRAPH_PROBE_LOG':str(log),'GRAPH_PROBE_FAIL_ADD':'1'})
        c.require(failed.returncode!=0,'Injected API failure cannot report successful measurement')

GATES=[('RU-001',lifecycle),('RU-002',nodes),('RU-003',edges),('RU-004',traversal),('RU-005',persistence),('RU-006',measurement)]
def main():
    results=[]
    for name,gate in GATES:
        c=Checks()
        try:gate(c);passed=True;detail='Behavior checks passed'
        except Exception as error:passed=False;detail=type(error).__name__+': '+str(error)
        results.append({'ru_id':name,'passed':passed,'detail':detail,'checks_passed':c.count})
    report={'harness_ok':True,'results':results,'infrastructure_errors':[]};print(json.dumps(report));return report
if __name__=='__main__':main()
