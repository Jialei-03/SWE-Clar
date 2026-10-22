"""Observe genuine SMF/PCM artifacts and batch behavior through the public CLI."""
import array
import hashlib
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import wave
sys.path.insert(0,'/public_tests')
from audio_support import Batch,make_midi,metadata,notes,read_artifact,artifact_entries
from test_public import public_contract,preflight
import mido


def fixture(path):
    events=[(0,'note_on',0,69,1),(120,'note_off',0,69,0),
            (120,'note_on',0,69,127),(121,'note_off',0,69,0),
            (150,'note_on',2,72,10),(155,'note_on',2,72,0),
            (240,'note_on',0,64,70),(240,'note_on',0,67,90),
            (960,'note_off',0,64,0),(960,'note_off',0,67,0),
            (960,'note_on',0,69,80),(1200,'note_off',0,69,0)]
    track=[];last=0
    for tick,kind,channel,pitch,velocity in events:
        track.append(mido.Message(kind,time=tick-last,channel=channel,note=pitch,velocity=velocity));last=tick
    track.append(mido.MetaMessage('end_of_track',time=3600-last))
    return make_midi(path,[[mido.MetaMessage('set_tempo',tempo=500000),
            mido.MetaMessage('marker',text='Synthetic marker',time=90),
            mido.MetaMessage('set_tempo',tempo=400000,time=390)],track,
            [mido.Message('note_on',note=69,velocity=60,time=60),
             mido.Message('note_off',note=69,time=1380)]])


def paired(source,produced):
    original=notes(source);actual=notes(produced)
    assert len(actual)==len(original),'Changed note count'
    def groups(values):
        result={}
        for n in values:result.setdefault((n['track'],n['channel'],n['pitch']),[]).append(n)
        return result
    expected_groups,actual_groups=groups(original),groups(actual)
    assert expected_groups.keys()==actual_groups.keys(),'Changed track, channel or pitch'
    result=[]
    for key,wanted in expected_groups.items():
        seen=actual_groups[key];assert len(seen)==len(wanted),'Changed same-key note count'
        result.extend(zip(wanted,seen))
    return sorted(result,key=lambda pair:(pair[0]['track'],pair[0]['ordinal']))


def controls(note,seed):
    digest=hashlib.sha256(('%d:%d:%d'%(seed,note['track'],note['ordinal'])).encode('ascii')).hexdigest()
    return int(digest[:2],16)%25-12,int(digest[2:4],16)%17-8


def single_result(rows,name='score.mid'):
    assert len(rows)==1 and rows[0]['input']==name and rows[0]['status']=='ok',rows
    assert rows[0]['error'] is None and type(rows[0]['notes']) is int


def public_and_formats():
    public_contract()
    for tracks,kind,ppqn in [
        ([[]],1,480),
        ([[mido.Message('note_on',channel=0,note=60,velocity=80)],
          [mido.Message('note_off',channel=0,note=60,time=480)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80)]],1,480),
        ([[mido.Message('note_off',note=60,time=240)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80),mido.Message('note_on',note=60,velocity=70,time=1),mido.Message('note_off',note=60,time=10),mido.Message('note_off',note=60,time=10)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80,channel=9),mido.Message('note_off',note=60,channel=9,time=240)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60,time=240)]],2,480),
        ([[mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60,time=240)]],1,-6360),
        ([[mido.MetaMessage('set_tempo',tempo=0),mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60,time=240)]],1,480),
        ([[mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60,time=116160)]],1,480),
    ]:
        with Batch() as batch:
            make_midi(batch.input/'invalid.mid',tracks,kind=kind,ppqn=ppqn)
            rows=batch.run(expected_exit=1)
            assert len(rows)==1 and rows[0]['status']=='error' and rows[0]['error']=='invalid_midi',rows
            assert not artifact_entries(batch.output),'Invalid MIDI published artifacts'
    with Batch() as batch:
        make_midi(batch.input/'large.mid',[[event for _ in range(10001)
            for event in [mido.Message('note_on',note=60,velocity=80,time=1),mido.Message('note_off',note=60,time=1)]]],kind=0)
        rows=batch.run(expected_exit=1);assert rows[0]['error']=='invalid_midi'
    for case in ['same','nested','ancestor','missing','file']:
        with Batch() as batch:
            if case=='same':batch.output=batch.input
            elif case=='nested':batch.output=batch.input/'results'
            elif case=='ancestor':batch.output=batch.root
            elif case=='missing':batch.input=batch.root/'absent'
            else:batch.output=batch.root/'file';batch.output.write_text('keep')
            before=sorted(p.relative_to(batch.root).as_posix() for p in batch.root.rglob('*'))
            batch.run(expected_exit=2)
            assert sorted(p.relative_to(batch.root).as_posix() for p in batch.root.rglob('*'))==before


def attack_timing():
    fingerprints=[]
    for seed in [0,42,4294967295]:
        for mode in ['normal','staccato']:
            with Batch() as batch:
                source=fixture(batch.input/'score.mid');before=metadata(source)
                single_result(batch.run(seed=seed,articulation=mode))
                produced=batch.output/'score.mid/performance.mid'
                assert metadata(produced)==before,'Changed tempo or non-note events'
                previous={};starts=[]
                for original,actual in paired(source,produced):
                    key=(original['track'],original['channel'],original['pitch'])
                    jitter,_=controls(original,seed)
                    wanted=max(previous.get(key,0),min(original['end']-1,original['start']+jitter))
                    assert actual['start']==wanted,(original,actual,wanted)
                    if mode=='normal':
                        assert actual['end']==original['end'],'Normal release must stay at original tick'
                    previous[key]=original['end'];starts.append(actual['start'])
                fingerprints.append(starts)
    assert len({tuple(x) for x in fingerprints})>1
    with Batch() as batch:
        fixture(batch.input/'z.mid');fixture(batch.input/'a.midi')
        rows=batch.run(seed=42);assert len(rows)==2 and all(r['status']=='ok' for r in rows)
        assert notes(batch.output/'z.mid/performance.mid')==notes(batch.output/'a.midi/performance.mid')


def velocity_articulation():
    for seed in [0,42,4294967295]:
        for mode in ['normal','staccato']:
            with Batch() as batch:
                source=fixture(batch.input/'score.mid');single_result(batch.run(seed=seed,articulation=mode))
                produced=batch.output/'score.mid/performance.mid'
                for original,actual in paired(source,produced):
                    _,delta=controls(original,seed)
                    assert actual['velocity']==max(1,min(127,original['velocity']+delta)),(original,actual)
                    end=original['end'] if mode=='normal' else actual['start']+max(1,(original['end']-actual['start'])//2)
                    assert actual['end']==end,(mode,original,actual,end)
                assert metadata(produced)==metadata(source)


def batch_recovery():
    with Batch() as batch:
        assert batch.run()==[]
    with Batch() as batch:
        (batch.input/'a-bad.mid').write_bytes(b'not a Standard MIDI File')
        for name in ['b-existing.mid','c-good.mid','deep/d.MIDI','deep/ignored.wav']:
            make_midi(batch.input/name)
        make_midi(batch.root/'external/linked.mid')
        (batch.input/'link.mid').symlink_to(batch.root/'external/linked.mid')
        (batch.input/'linked-directory').symlink_to(batch.root/'external',target_is_directory=True)
        existing=batch.output/'b-existing.mid';existing.mkdir();existing.chmod(0o777)
        (existing/'performance.mid').write_bytes(b'previous MIDI bytes');(existing/'performance.mid').chmod(0o666)
        (existing/'render.wav').write_bytes(b'previous WAV bytes');(existing/'render.wav').chmod(0o666)
        rows=batch.run(expected_exit=1)
        assert [(r['input'],r['status'],r['error']) for r in rows]==[
            ('a-bad.mid','error','invalid_midi'),('b-existing.mid','error','existing_output'),
            ('c-good.mid','ok',None),('deep/d.MIDI','ok',None)],rows
        assert read_artifact(existing/'performance.mid')==b'previous MIDI bytes'
        assert read_artifact(existing/'render.wav')==b'previous WAV bytes'
        assert not (batch.output/'a-bad.mid').exists()
        for name in ['c-good.mid','deep/d.MIDI']:
            assert read_artifact(batch.output/name/'performance.mid') and read_artifact(batch.output/name/'render.wav')
        assert all(not entry['path'].split('/')[-1].startswith('.performance-') for entry in artifact_entries(batch.output))
    with Batch() as batch:
        for name in ['first.mid','deep/second.mid']:make_midi(batch.input/name)
        rows=batch.run(expected_exit=1,env={'CLARSWE_AUDIO_RENDER_ERROR':'1'})
        assert [(r['input'],r['status'],r['error']) for r in rows]==[
            ('deep/second.mid','error','render_failed'),('first.mid','error','render_failed')],rows
        assert not (batch.output/'first.mid').exists() and not (batch.output/'deep/second.mid').exists()
        inventory=artifact_entries(batch.output)
        assert all(entry['kind']=='directory' and entry['path']=='deep' for entry in inventory),'Failed renders left unpublished artifacts'


def pcm(path):
    with wave.open(io.BytesIO(read_artifact(path))) as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(2,2,44100),'Wrong PCM format'
        count=wav.getnframes();samples=array.array('h',wav.readframes(count))
        assert len(samples)==2*count,'Incomplete PCM data'
    return count,samples


def actual_audio():
    signatures=[]
    for mode,seed in [('normal',0),('staccato',42)]:
        with Batch() as batch:
            source=fixture(batch.input/'score.mid')
            if mode=='staccato':
                changed=mido.MidiFile(source)
                for track in changed.tracks:
                    for event in track:
                        if event.type in ['note_on','note_off']:event.note-=5
                changed.save(source)
            single_result(batch.run(seed=seed,articulation=mode))
            produced=batch.output/'score.mid/performance.mid';assert read_artifact(produced)
            observed_count,observed=pcm(batch.output/'score.mid/render.wav')
            # Re-render the delivered MIDI through the protected environment, not candidate code.
            oracle=batch.output/'independent.wav'
            identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
            p=subprocess.run([sys.executable,'-I','/opt/sweclar/render_midi.py',str(produced),str(oracle)],
                text=True,capture_output=True,timeout=45,env={'PATH':os.environ['PATH']},**identity)
            assert p.returncode==0,'Produced MIDI cannot drive the prepared renderer'
            expected_count,expected=pcm(oracle)
            assert observed_count==expected_count,'Audio duration must follow note-off and the fixed tail'
            energy=sum(v*v for v in expected);assert energy>1000000
            difference=sum((a-b)**2 for a,b in zip(observed,expected))
            assert difference/max(1,energy)<1e-8,'PCM waveform does not match the delivered MIDI through the prepared instrument'
            assert max(abs(v) for v in observed[-4000:])==0,'Release tail does not become silent'
            signatures.append(hashlib.sha256(observed.tobytes()).hexdigest())
    assert signatures[0]!=signatures[1],'Distinct MIDI performances produced identical audio'


def main():
    try:prepared=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[type(error).__name__+': '+str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([public_and_formats,attack_timing,velocity_articulation,batch_recovery,actual_audio],1):
        try:test();results.append({'ru_id':f'RU-{i:03}','passed':True})
        except (AssertionError,KeyError,TypeError,ValueError,EOFError,OSError,wave.Error) as error:
            results.append({'ru_id':f'RU-{i:03}','passed':False,'detail':type(error).__name__+': '+str(error)[:1800]})
    print(json.dumps({'harness_ok':True,'preflight':prepared,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
