"""Public process and MIDI helpers; contains no hidden policies or grading data."""
import json
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import mido

PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def make_midi(path, tracks=None, *, kind=1, ppqn=480):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    midi=mido.MidiFile(type=kind,ticks_per_beat=ppqn)
    if tracks is None:
        tracks=[[mido.MetaMessage('set_tempo',tempo=500000,time=0)],
                [mido.Message('note_on',note=69,velocity=80,time=120),
                 mido.Message('note_off',note=69,time=480)]]
    midi.tracks=[mido.MidiTrack(messages) for messages in tracks]
    midi.save(path)
    return path


def _inspect_artifact(path,operation):
    reader = """import json,pathlib,sys
p=pathlib.Path(sys.argv[1]);operation=sys.argv[2]
if operation=='read':
    assert p.is_file() and not p.is_symlink(), 'Artifact must be a regular self-contained file'
    sys.stdout.buffer.write(p.read_bytes())
else:
    entries=[]
    def visit(directory):
        for entry in sorted(directory.iterdir()):
            kind='link' if entry.is_symlink() else 'directory' if entry.is_dir() else 'file'
            entries.append({'path':entry.relative_to(p).as_posix(),'kind':kind})
            if kind=='directory':visit(entry)
    visit(p)
    print(json.dumps(entries))
"""
    identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    result=subprocess.run([sys.executable,'-I','-c',reader,str(path),operation],
                          capture_output=True,timeout=15,**identity)
    assert result.returncode==0,'Missing or unreadable artifact: '+str(path.name)
    return result.stdout


def read_artifact(path):
    return _inspect_artifact(path,'read')


def artifact_entries(path):
    return json.loads(_inspect_artifact(path,'entries'))


def notes(path):
    midi=mido.MidiFile(file=io.BytesIO(read_artifact(path)));result=[]
    for t,track in enumerate(midi.tracks):
        tick=ordinal=0;active={}
        for event in track:
            tick+=event.time
            if event.type=='note_on' and event.velocity>0:
                key=(event.channel,event.note)
                assert key not in active,'Output has overlapping same-key notes'
                active[key]={'track':t,'ordinal':ordinal,'channel':event.channel,
                             'pitch':event.note,'velocity':event.velocity,'start':tick}
                ordinal+=1
            elif event.type=='note_off' or event.type=='note_on' and event.velocity==0:
                key=(event.channel,event.note);assert key in active,'Unmatched output release'
                note=active.pop(key);note['end']=tick;assert note['end']>note['start']
                result.append(note)
        assert not active,'Output has unterminated notes'
    return sorted(result,key=lambda n:(n['track'],n['ordinal']))


def metadata(path):
    midi=mido.MidiFile(file=io.BytesIO(read_artifact(path)));tracks=[]
    for track in midi.tracks:
        tick=0;items=[]
        for event in track:
            tick+=event.time
            if event.type not in ['note_on','note_off']:
                items.append((tick,event.copy(time=0).dict()))
        tracks.append(items)
    return midi.type,midi.ticks_per_beat,tracks


class Batch:
    def __enter__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='audio-batch-',ignore_cleanup_errors=True)
        self.root=Path(self.temp.name);self.root.chmod(0o755)
        self.input=self.root/'input';self.input.mkdir()
        self.output=self.root/'output';self.output.mkdir();self.output.chmod(0o777)
        return self

    def run(self, *, seed=0, articulation='normal', expected_exit=0, env=None, extra=None):
        args=[sys.executable,'app.py',str(self.input),str(self.output),
              '--seed',str(seed),'--articulation',articulation]+list(extra or [])
        identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
        process=subprocess.Popen(args,cwd=PROJECT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':str(self.root),
            'PYTHONDONTWRITEBYTECODE':'1',**(env or {})},**identity)
        try:
            stdout,stderr=process.communicate(timeout=60)
        except subprocess.TimeoutExpired as error:
            raise AssertionError('Application exceeded its command time limit') from error
        finally:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
            process.stdout.close();process.stderr.close()
        assert process.returncode==expected_exit, f'expected exit {expected_exit}, got {process.returncode}: {stderr[-1800:]}'
        if expected_exit==2:
            assert stderr.strip(),'Invalid arguments must explain the error'
            return None
        try:payload=json.loads(stdout.strip().splitlines()[-1])
        except (ValueError,IndexError) as error:raise AssertionError('Missing valid final JSON result') from error
        assert isinstance(payload,dict) and isinstance(payload.get('results'),list)
        return payload['results']

    def __exit__(self,*_):
        repair = """import os, pathlib, sys
uid=os.getuid()
def visit(path):
    for entry in path.iterdir():
        if entry.is_symlink():
            continue
        if entry.stat().st_uid==uid:
            entry.chmod(0o777 if entry.is_dir() else 0o666)
        if entry.is_dir():
            visit(entry)
visit(pathlib.Path(sys.argv[1]))
"""
        identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
        result=subprocess.run([sys.executable,'-I','-c',repair,str(self.root)],
            capture_output=True,text=True,timeout=10,**identity)
        if result.returncode:
            raise RuntimeError('Protected fixture cleanup failed: '+result.stderr[-500:])
        self.temp.cleanup()
