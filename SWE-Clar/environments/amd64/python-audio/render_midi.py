"""Protected SMF tempo-aware adapter for the prepared VST3 instrument."""
import argparse,collections,subprocess,tempfile
from fractions import Fraction
from pathlib import Path
import mido

def schedule(path):
    midi=mido.MidiFile(path)
    if midi.type not in (0,1) or midi.ticks_per_beat<=0:raise ValueError('Use metrical MIDI type 0 or 1')
    events=[]
    for track_index,track in enumerate(midi.tracks):
        tick=0
        for event_index,event in enumerate(track):
            tick+=event.time
            events.append((tick,track_index,event_index,event))
    elapsed=Fraction(0);last_tick=0;tempo=500000
    active=collections.defaultdict(collections.deque);notes=[];ordinal=0
    for tick,track_index,event_index,event in sorted(events,key=lambda row:row[:3]):
        elapsed+=Fraction((tick-last_tick)*tempo,midi.ticks_per_beat*1000000)
        last_tick=tick
        samples=elapsed*44100
        frame=(samples.numerator*2+samples.denominator)//(2*samples.denominator)
        if elapsed>120:raise ValueError('MIDI duration limit')
        if event.type=='set_tempo':
            if event.tempo<=0:raise ValueError('Tempo must be positive')
            tempo=event.tempo
        elif event.type=='note_on' and event.velocity>0:
            active[(track_index,event.channel,event.note)].append((frame,event.velocity,ordinal));ordinal+=1
            if ordinal>10000:raise ValueError('MIDI note limit')
        elif event.type=='note_off' or event.type=='note_on' and event.velocity==0:
            key=(track_index,event.channel,event.note)
            if not active[key]:raise ValueError('Unmatched MIDI note off')
            start,velocity,order=active[key].popleft()
            notes.append((start,max(start+1,frame),event.note,velocity,order))
    if any(active.values()):raise ValueError('Unterminated MIDI note')
    if not notes:raise ValueError('MIDI contains no notes')
    notes.sort(key=lambda row:(row[0],row[4]))
    return notes,max(n[1] for n in notes)+22050

def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--host',type=Path,default=Path('/opt/sweclar/clar_render'));p.add_argument('--plugin',type=Path,default=Path('/opt/sweclar/ClarPiano.vst3'));args=p.parse_args()
    notes,frames=schedule(args.input)
    with tempfile.TemporaryDirectory(prefix='clar-midi-') as directory:
        path=Path(directory)/'notes.tsv'
        path.write_text(''.join(' '.join(str(v) for v in row[:4])+'\n' for row in notes))
        subprocess.run([str(args.host),str(args.plugin),str(path),str(args.output),str(frames)],check=True)

if __name__=='__main__':main()
