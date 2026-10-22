import importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from solution import process_voice_event
from server import make_server,demo_audio
import io,wave,threading
from urllib.request import urlopen
state={'admins':['admin'],'rooms':{}};out=process_voice_event(state,{'type':'create_room','admin_id':'admin','room_id':'public','private':False,'turn_limit':5})
assert out['result']['room_id']=='public' and state['rooms']=={}
with wave.open(io.BytesIO(demo_audio())) as audio:assert audio.getnframes()>0 and audio.getframerate()==8000
server=make_server(0);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
try:
 with urlopen('http://127.0.0.1:'+str(server.server_port)+'/health') as response:assert json.load(response)['ok'] is True
finally:server.shutdown();server.server_close();worker.join()
print('Room creation, generated WAV and HTTP health baseline passed')
