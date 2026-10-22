from pathlib import Path
import hashlib,wave,subprocess,tempfile,json,array,sys
class LocalWhisper:
    def __init__(self,binary,model,asset_root):self.binary=str(binary);self.model=str(model);self.root=Path(asset_root).resolve()
    def audio(self,relative):
        if not isinstance(relative,str):raise ValueError('invalid audio')
        path=(self.root/relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():raise ValueError('invalid audio')
        with wave.open(str(path),'rb') as wav:
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=16000 or wav.getcomptype()!='NONE' or not 1<=wav.getnframes()<=480000:raise ValueError('unsupported audio')
            data=wav.readframes(wav.getnframes());samples=array.array('h',data)
            if sys.byteorder!='little':samples.byteswap()
            if not samples or max(abs(x) for x in samples)<20:raise ValueError('no audible speech')
        return path
    def audio_digest(self,relative):return hashlib.sha256(self.audio(relative).read_bytes()).hexdigest()
    def transcribe(self,relative):raise NotImplementedError('Transcribe actual audio')
