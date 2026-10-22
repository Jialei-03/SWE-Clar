"""Smoke checks for the disclosed MIDI and command-line contract."""
import json
import io
from pathlib import Path
import subprocess
import sys
import wave
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audio_support import Batch,make_midi,notes,metadata,read_artifact
import mido


def public_contract():
    with Batch() as batch:
        path=make_midi(batch.input/'phrase.mid')
        before=metadata(path)
        rows=batch.run()
        assert len(rows)==1 and rows[0]['input']=='phrase.mid' and rows[0]['status']=='ok'
        output=batch.output/'phrase.mid'
        assert read_artifact(output/'performance.mid') and read_artifact(output/'render.wav')
        assert metadata(output/'performance.mid')==before
        observed=notes(output/'performance.mid')
        assert len(observed)==1 and observed[0]['pitch']==69 and observed[0]['channel']==0 and observed[0]['track']==1
        with wave.open(io.BytesIO(read_artifact(output/'render.wav'))) as wav:
            assert wav.getnchannels()==2 and wav.getsampwidth()==2 and wav.getframerate()==44100
            assert wav.getnframes()>0 and any(wav.readframes(wav.getnframes()))
    for args in [{'seed':-1},{'seed':4294967296},{'articulation':'unknown'}]:
        with Batch() as batch:
            make_midi(batch.input/'phrase.mid')
            batch.run(expected_exit=2,**args)
            assert list(batch.output.iterdir())==[]
    with Batch() as batch:
        make_midi(batch.input/'phrase.mid',[[mido.Message('note_on',note=60,velocity=50),
                  mido.Message('note_on',note=60,velocity=0,time=300)]],kind=0,ppqn=960)
        rows=batch.run();assert rows[0]['status']=='ok'
        assert mido.MidiFile(file=io.BytesIO(read_artifact(batch.output/'phrase.mid/performance.mid'))).type==0


def preflight():
    p=subprocess.run([sys.executable,'-I','/opt/sweclar/preflight.py'],capture_output=True,text=True,check=True,timeout=60)
    result=json.loads(p.stdout);assert result['passed'] is True
    return result


if __name__=='__main__':
    preflight();public_contract();print('Public MIDI application checks passed')
