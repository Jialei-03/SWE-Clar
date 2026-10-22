"""Protected offline audio health check, executed before the candidate budget."""
import array
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave
import mido


def candidate_identity():
    if os.getuid() == 0:
        os.setgid(1000)
        os.setuid(1000)


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=45, preexec_fn=candidate_identity)


def main():
    assert int(run([sys.executable, '-c', 'import os;print(os.getuid())']).stdout) == 1000
    with tempfile.TemporaryDirectory(prefix='audio-health-') as directory:
        root=Path(directory)
        root.chmod(0o755)
        (root/"out").mkdir()
        (root/"out").chmod(0o777)
        midi=mido.MidiFile(type=1,ticks_per_beat=480)
        tempo=mido.MidiTrack()
        tempo.extend([mido.MetaMessage('set_tempo',tempo=500000,time=0),
                      mido.MetaMessage('set_tempo',tempo=1000000,time=480)])
        notes=mido.MidiTrack()
        notes.extend([mido.Message('note_on',note=69,velocity=100,time=0),
                      mido.Message('note_off',note=69,time=480),
                      mido.Message('note_on',note=57,velocity=100,time=0),
                      mido.Message('note_on',note=57,velocity=0,time=480)])
        midi.tracks.extend([tempo,notes]);midi.save(root/'input.mid')
        run([sys.executable,'-I','/opt/sweclar/render_midi.py',str(root/'input.mid'),str(root/'out/output.wav')])
        with wave.open(str(root/'out/output.wav')) as wav:
            assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes())==(2,2,44100,88200)
            samples=array.array('h',wav.readframes(wav.getnframes()))
        left=samples[::2]
        def frequency(start,end):
            values=left[int(start*44100):int(end*44100)]
            crossings=sum(a<=0<b for a,b in zip(values,values[1:]))
            return crossings/(end-start)
        freqs=[frequency(.1,.4),frequency(.9,1.3)]
        assert abs(freqs[0]-440)<5 and abs(freqs[1]-220)<5
        assert sum(v*v for v in left)>1000000
        assert max(abs(v) for v in left[int(1.8*44100):])==0
        print(json.dumps({'passed':True,'ready':True,'candidate_uid':1000,'mido':str(mido.version_info),
            'real_vst3_loaded':True,'sample_rate':44100,'channels':2,'frames':88200,
            'tempo_change_frequencies_hz':freqs,'wav_sha256':hashlib.sha256((root/'out/output.wav').read_bytes()).hexdigest()}))


if __name__=='__main__':main()
