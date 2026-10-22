from copy import deepcopy
from candidate_proxy import call,browser
from scene_content import scene_content

def base():return {'puzzles':{'cubes':{'answer':'7'},'tetra':{'answer':'4'}},'required_puzzles':['cubes','tetra'],'solved':[],'exit_open':False,'escaped':False,'presentation':'standalone','rotate_prompt':False,'texts':{'en':{'title':'Geometry chamber','cubes':'Count all gold and blue cubes','tetra':'Count the tetrahedron vertices','exit':'Leave the room','rotate':'Rotate to landscape'},'es':{'title':'Sala de geometria','cubes':'Cuenta los cubos dorados y azules','exit':'Salir de la sala','rotate':'Gira a horizontal'}}}
def same(a,b):
 for k in ['puzzles','required_puzzles','solved','exit_open','escaped','texts','presentation','rotate_prompt','aspect_supported']:
  assert a.get(k)==b.get(k),k
def ok(s,a):
 out=call(s,a);assert 'error' not in out,out;return out
def denied(s,a):
 out=call(s,a);assert out.get('error',{}).get('code');same(out,s);return out
def solve(p,a):return [{'op':'fill','selector':'#answer-'+p,'value':a},{'op':'click','selector':'#solve-'+p}]
def solved():return ok(ok(base(),dict(type='solve',puzzle='cubes',answer='7')),dict(type='solve',puzzle='tetra',answer='4'))

def test_ru_001_puzzle_and_3d():
 s=base()
 for action in [dict(type='solve',puzzle='missing',answer='7'),dict(type='solve',puzzle='cubes',answer='5'),dict(type='solve',puzzle='cubes',answer=7),dict(type='unknown')]:denied(s,action)
 out=ok(s,dict(type='solve',puzzle='tetra',answer=' 4 '));assert out['solved']==['tetra'];out=ok(out,dict(type='solve',puzzle='tetra',answer='4'));assert out['solved'].count('tetra')==1
 rows=browser(s,[{'op':'inspect'}]+solve('cubes','2')+solve('cubes','7'));assert rows[0]['webgl']['present'] and rows[0]['webgl']['depth'];assert rows[2]['state']['solved']==[];assert set(rows[4]['state']['solved'])=={'cubes'};assert {x['id']:x['solved'] for x in rows[4]['locks']}['lock-cubes']=='true';assert rows[0]['canvas']!=rows[4]['canvas']
 scene_content(rows[0]['canvas']);scene_content(rows[4]['canvas'])

def test_ru_002_exit():
 s=base();denied(s,dict(type='exit'));s=ok(s,dict(type='solve',puzzle='cubes',answer='7'));assert s['exit_open'] is False;denied(s,dict(type='exit'));s=ok(s,dict(type='solve',puzzle='tetra',answer='4'));assert s['exit_open'] is True;assert ok(s,dict(type='exit'))['escaped'] is True
 s=base();s['solved']=['cubes','cubes','unrelated'];denied(s,dict(type='exit'))
 rows=browser(base(),[{'op':'inspect'}]+solve('tetra','4')+solve('cubes','7')+[{'op':'click','selector':'#exit'}]);assert rows[0]['exit_enabled'] is False and rows[2]['exit_enabled'] is False;assert rows[4]['exit_enabled'] is True;assert rows[5]['completed'] and rows[5]['state']['escaped'] is True;assert rows[4]['canvas']!=rows[5]['canvas']
 scene_content(rows[0]['canvas']);scene_content(rows[4]['canvas']);scene_content(rows[5]['canvas'])

def test_ru_003_orientation():
 s=base()
 for w,h,rotate,aspect in [(360,640,True,False),(1280,720,False,True),(800,800,False,False),(1000,500,False,False)]:
  out=ok(s,dict(type='viewport',width=w,height=h));assert out['rotate_prompt'] is rotate and out['aspect_supported'] is aspect
 for w,h in [(0,100),(-1,100),(True,100),(float('inf'),10)]:denied(s,dict(type='viewport',width=w,height=h))
 rows=browser(s,solve('cubes','7')+[{'op':'resize','width':390,'height':844},{'op':'resize','width':1280,'height':720}]);assert rows[2]['rotate_visible'] and rows[2]['room_inert'];assert not rows[3]['rotate_visible'] and not rows[3]['room_inert'];assert 'cubes' in rows[3]['state']['solved'];g=rows[3]['webgl'];assert abs(g['width']/g['height']-16/9)<.02

def test_ru_004_embed():
 s=base()
 for mode in ['standalone','embedded']:assert ok(s,dict(type='presentation',mode=mode))['presentation']==mode
 denied(s,dict(type='presentation',mode='popup'))
 rows=browser(s,solve('cubes','7')+solve('tetra','4')+[{'op':'click','selector':'#exit'}],path='/embed');assert rows[-1]['frame_count']>=2 and rows[-1]['presentation']=='embedded' and rows[-1]['state']['presentation']=='embedded';assert rows[-1]['completed'] and rows[-1]['state']['escaped'] is True

def test_ru_005_locale():
 s=base();s['texts']['es']['blank']='';s['texts']['en']['blank']='fallback'
 for locale,key,expected in [('es','title','Sala de geometria'),('es','tetra','Count the tetrahedron vertices'),('zz','title','Geometry chamber'),('zz','absent','absent'),('es','blank','')]:
  out=ok(s,dict(type='text',locale=locale,key=key));assert out['text']==expected;same(out,s)
 denied(s,dict(type='text',locale=None,key='title'))
 s['texts']['en'].pop('tetra');rows=browser(s,solve('cubes','7')+[{'op':'locale','value':'es'},{'op':'locale','value':'zz'}]);assert rows[2]['labels']['title']=='Sala de geometria' and rows[2]['labels']['tetra']=='tetra';assert rows[3]['labels']['title']=='Geometry chamber';assert rows[2]['state']['solved']==rows[3]['state']['solved']==['cubes']
