from copy import deepcopy
import re

def valid_text(value):return isinstance(value,str) and bool(value.strip())
def clock(value):return isinstance(value,int) and not isinstance(value,bool) and value>=0

def process_class_action(state,action,transcriber=None,translator=None):
    out=deepcopy(state);a=deepcopy(action);out.pop('result',None);out.pop('error',None)
    original=deepcopy(out);out.setdefault('classes',{});out.setdefault('translations',{})
    def fail(code):return {**original,'error':{'code':code}}
    kind=a.get('type');actor=a.get('actor_id');role=out.get('users',{}).get(actor,{}).get('role')
    if kind=='create_class':
        cid=a.get('class_id');code=a.get('code')
        if role!='teacher' or not valid_text(cid) or cid in out['classes'] or not isinstance(code,str) or not re.fullmatch('[A-Za-z]+',code) or any(c['code']==code.upper() for c in out['classes'].values()):return fail('invalid_class')
        out['classes'][cid]={'code':code.upper(),'teacher_id':actor,'students':[],'status':'created','elapsed':0,'last_clock':None,'questions':[],'transcript':[],'feedback':{},'notes':[],'documents':[]};out['result']={'class_id':cid,'code':code.upper()};return out
    if kind=='join':
        code=a.get('code');matches=[c for c in out['classes'].values() if isinstance(code,str) and c['code']==code.upper()]
        if role!='student' or len(matches)!=1:return fail('join_denied')
        if actor not in matches[0]['students']:matches[0]['students'].append(actor)
        out['result']={'joined':True};return out
    c=out['classes'].get(a.get('class_id'))
    if not c:return fail('unknown_class')
    teacher=actor==c['teacher_id'] and role=='teacher';student=actor in c['students'] and role=='student'
    if kind in {'start','resume','pause','complete'}:
        now=a.get('clock')
        if not teacher or not clock(now):return fail('timer_denied')
        allowed={'start':{'created'},'resume':{'paused'},'pause':{'running'},'complete':{'running','paused'}}
        if c['status'] not in allowed[kind]:return fail('timer_denied')
        if c['status']=='running':c['elapsed']+=max(0,now-c['last_clock'])
        c['status']='running' if kind in {'start','resume'} else 'paused' if kind=='pause' else 'completed';c['last_clock']=now if c['status']=='running' else None
        out['result']={'status':c['status'],'elapsed':c['elapsed']}
    elif kind=='question_click':
        qid=a.get('question_id');elapsed=a.get('elapsed')
        if not student or c['status']!='running' or not valid_text(qid) or not clock(elapsed):return fail('question_denied')
        prior=next((q for q in c['questions'] if q['question_id']==qid),None)
        if prior and prior['student_id']!=actor:return fail('question_denied')
        if prior is None:c['questions'].append({'question_id':qid,'student_id':actor,'timestamp':elapsed,'text':''})
        out['result']={'question_id':qid}
    elif kind=='question_submit':
        q=next((q for q in c['questions'] if q['question_id']==a.get('question_id')),None)
        if not student or q is None or q['student_id']!=actor or not valid_text(a.get('text')):return fail('question_denied')
        q['text']=a['text'];q['timestamp']=a.get('elapsed',q['timestamp']);out['result']=deepcopy(q)
    elif kind=='transcribe':
        sid=a.get('segment_id');elapsed=a.get('elapsed')
        if not teacher or c['status']=='created' or not valid_text(sid) or not clock(elapsed) or transcriber is None:return fail('transcript_denied')
        try:
            digest=transcriber.audio_digest(a.get('audio_path'))
            prior=next((r for r in c['transcript'] if r['segment_id']==sid),None)
            if prior:
                if prior['audio_sha256']!=digest or prior['timestamp']!=elapsed:return fail('transcript_conflict')
                out['result']={'duplicate':True,'text':prior['text']};return out
            text=transcriber.transcribe(a['audio_path'])
            if not valid_text(text):raise ValueError('no speech')
        except Exception:return fail('transcript_failed')
        c['transcript'].append({'segment_id':sid,'timestamp':elapsed,'text':text.strip(),'audio_sha256':digest});out['result']={'duplicate':False,'text':text.strip()}
    elif kind=='feedback':
        if not student or a.get('value') not in {'up','down'}:return fail('feedback_denied')
        c['feedback'][actor]=a['value'];out['result']={'understanding_rate':sum(v=='up' for v in c['feedback'].values())/len(c['feedback'])}
    elif kind=='post_class_view':
        if not (teacher or student):return fail('view_denied')
        questions=c['questions'] if teacher else [q for q in c['questions'] if q['student_id']==actor]
        out['result']={'transcript':deepcopy(c['transcript']),'questions':deepcopy(questions),'notes':[],'documents':[]}
        if teacher:out['result']['students']=deepcopy(c['students'])
    elif kind=='add_material':
        if not teacher or a.get('kind') not in {'note','document'} or not valid_text(a.get('material_id')) or not valid_text(a.get('content')):return fail('material_denied')
        rows=c['notes'] if a['kind']=='note' else c['documents'];row={'id':a['material_id'],'content':a['content']}
        if row not in rows:rows.append(row)
        out['result']={'added':True}
    elif kind=='translate':
        text,language=a.get('text'),a.get('language')
        if not (teacher or student) or not valid_text(text) or not valid_text(language):return fail('translation_denied')
        import json
        key=json.dumps([text,language],ensure_ascii=False,separators=(',',':'));hit=key in out['translations']
        if not hit:
            try:
                translated=translator.translate(text,language)
                if not valid_text(translated):raise ValueError('empty translation')
            except Exception:return fail('translation_failed')
            out['translations'][key]=translated
        out['result']={'text':out['translations'][key],'cache_hit':hit}
    else:return fail('unknown_action')
    return out
