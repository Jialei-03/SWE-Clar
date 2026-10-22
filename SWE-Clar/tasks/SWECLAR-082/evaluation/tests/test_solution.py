from copy import deepcopy
import hashlib
from candidate_proxy import call,cli

def base():return {'users':{'teacher':{'role':'teacher'},'other':{'role':'teacher'},'alice':{'role':'student'},'bob':{'role':'student'},'outsider':{'role':'student'}}}
def action(operation,actor='teacher',**fields):return {'type':operation,'actor_id':actor,'class_id':'lesson',**fields}
def created():
 s=call(base(),action('create_class',code='Sample'))
 for user in ['alice','bob']:s=call(s,action('join',user,code='sAmPlE'))
 return s

def running():return call(created(),action('start',clock=100))
def denied(s,a,**kw):
 out=call(s,a,**kw);assert out.get('error')
 for key,value in s.items():
  if key not in ('result','error'):assert out.get(key)==value
 return out

def test_ru_001_immutable_entry_and_sqlite_cli():
 a=action('create_class',code='Sample');s=base();out=call(s,a);assert out['result']['class_id']=='lesson' and out['classes']['lesson']['code']=='SAMPLE'
 rows=cli(s,[{'command':'act','value':a},{'command':'act','value':action('join','alice',code='sample')},{'command':'show'},{'command':'act','value':action('start','alice',clock=0)},{'command':'show'},{'command':'init','value':{}},{'command':'show'}])['observations']
 assert all(r['returncode']==0 for r in rows)
 assert rows[1]['output']['result']['class_id']=='lesson' and rows[3]['output']['classes']['lesson']['students']==['alice']
 assert rows[4]['output'].get('error') and rows[5]['output']==rows[3]['output']==rows[7]['output'] and rows[6]['output'].get('error')
 assert not set(rows[1]['output'])&{'users','classes'}
 denied(s,action('unknown'))

def test_ru_002_roles_codes_and_join():
 s=created();assert s['classes']['lesson']['code']=='SAMPLE'
 assert call(s,action('join','alice',code='sample'))['classes']['lesson']['students']==['alice','bob']
 for actor in ['alice','other','outsider','unknown']:denied(s,action('start',actor,clock=0))
 for a in [action('create_class','alice',class_id='new',code='Other'),action('create_class',class_id='new',code='sample'),action('create_class',class_id='new',code='ABC1'),action('join','other',code='Sample'),action('join','outsider',code='missing')]:denied(s,a)

def test_ru_003_timer_and_click_timestamp():
 s=running();s=call(s,action('question_click','alice',question_id='q',elapsed=4));s=call(s,action('question_submit','alice',question_id='q',text='Explain the shape',elapsed=999));assert s['classes']['lesson']['questions'][0]['timestamp']==4
 denied(s,action('question_submit','bob',question_id='q',text='Not mine'));denied(s,action('question_click','alice',question_id='q',elapsed=5));denied(s,action('pause',clock=True))
 s=call(s,action('pause',clock=106));assert s['classes']['lesson']['elapsed']==6
 s=call(s,action('resume',clock=120));s=call(s,action('complete',clock=125));assert s['classes']['lesson']['elapsed']==11 and s['classes']['lesson']['last_clock'] is None
 denied(s,action('resume',clock=150));denied(s,action('question_click','alice',question_id='late',elapsed=15))
 s=call(running(),action('pause',clock=90));assert s['classes']['lesson']['elapsed']==0

def test_ru_004_actual_audio_replay_feedback_and_views():
 s=running()
 for user in ['alice','bob']:
  s=call(s,action('question_click',user,question_id=user,elapsed=2));s=call(s,action('question_submit',user,question_id=user,text='Synthetic question'))
 for sid,path,words,stamp in [('speech','lesson.wav',['triangle','three','sides'],0),('second','science.wav',['water','ice'],8)]:
  a=action('transcribe',segment_id=sid,audio_path=path,elapsed=stamp,text='Forged caller transcript');s=call(s,a);assert all(w in s['result']['text'].lower() for w in words) and 'forged' not in s['result']['text'].lower()
  segment=next(x for x in s['classes']['lesson']['transcript'] if x['id']==sid);assert segment['timestamp']==stamp and segment['audio_sha256']==hashlib.sha256(open('/opt/sweclar/speech/'+path,'rb').read()).hexdigest()
  replay=call(s,a,binary='/does-not-exist');assert replay['result']['duplicate'] is True and replay['classes']==s['classes']
 denied(s,action('transcribe',segment_id='speech',audio_path='science.wav',elapsed=0))
 for path in ['silent.wav','malformed.wav','missing.wav','../outside.wav']:denied(s,action('transcribe',segment_id='bad',audio_path=path,elapsed=1))
 denied(s,action('transcribe','alice',segment_id='bad',audio_path='lesson.wav',elapsed=1))
 for actor,value in [('alice','up'),('bob','down'),('alice','down')]:s=call(s,action('feedback',actor,value=value))
 assert s['result']['understanding_rate']==0
 s=call(s,action('complete',clock=120))
 completed_transcription_boundary(s)
 t=call(s,action('post_class_view'))['result'];u=call(s,action('post_class_view','alice'))['result']
 assert t['students']==['alice','bob'] and len(t['questions'])==2 and len(t['transcript'])==2
 assert len(u['questions'])==1 and u['questions'][0]['student_id']=='alice' and u['transcript']==t['transcript'];denied(s,action('post_class_view','outsider'))

def completed_transcription_boundary(s):
 a=action('transcribe',segment_id='speech',audio_path='lesson.wav',elapsed=0)
 replay=call(s,a,binary='/does-not-exist')
 assert replay['result']['duplicate'] is True
 for key,value in s.items():
  if key not in ('result','error'):assert replay.get(key)==value
 # Fresh segments use valid audio and the real recognizer: a missing binary
 # must not accidentally make an invalid completed-state implementation pass.
 for change in [{'segment_id':'late'},{'elapsed':1},{'audio_path':'science.wav'}]:
  denied(s,{**a,**change})

def test_ru_005_materials_and_real_translation_cache():
 s=created()
 for kind in ['note','document']:s=call(s,action('add_material',kind=kind,material_id=kind,content='Synthetic '+kind))
 view=call(s,action('post_class_view','alice'))['result'];assert view['notes'][0]['content']=='Synthetic note' and view['documents'][0]['content']=='Synthetic document';denied(s,action('add_material','outsider',kind='note',material_id='bad',content='x'))
 a=action('translate','alice',text='Sample lesson',language='es',translated_text='Forged caller output');ops=[{'command':'act','value':a},{'command':'act','value':a},{'command':'show'}]
 observed=cli(s,ops,response={'text':'Texto de ejemplo'});rows=observed['observations'];assert rows[1]['output']['result']['text']=='Texto de ejemplo' and rows[1]['output']['result']['cache_hit'] is False and rows[2]['output']['result']['cache_hit'] is True
 assert len(observed['requests'])==1 and all(observed['requests'][0][k]==v for k,v in {'text':'Sample lesson','language':'es'}.items());saved=rows[3]['output']
 for response in [{'status':503},{'body':{'source_text':'wrong'}},{'body':{'language':'fr'}}]:
  bad=cli(saved,[{'command':'act','value':{**a,'text':'New lesson'}},{'command':'show'}],response=response);assert bad['observations'][1]['output'].get('error') and bad['observations'][2]['output']['translations']==saved['translations']
 denied(s,{**a,'actor_id':'outsider'})
