from copy import deepcopy
from candidate_proxy import call

def error(out):
    assert isinstance(out.get('error'),dict)
    assert isinstance(out['error'].get('code'),str) and out['error']['code'].strip()

def ru001():
    for action in ['vehicle_check','install','unknown','']:
        result=call({'status':'created','history':[]},{'type':action})
        error(result)

def ru002():
    history=[{'type':'import','status':'created'}]
    state={'id':'parcel-synthetic','status':'created','history':history}
    for kind,status in [('assign','assigned'),('pickup','picked_up'),('deliver','delivered')]:
        before=deepcopy(state)
        state=call(state,{'type':kind,'receiver':'Receiver sample','signature':'proof-ref'})
        assert not state.get('error') and state['status']==status
        assert state['history'][:-1]==before['history'] and len(state['history'])==len(before['history'])+1
        assert state['history'][-1]['type']==kind and state['history'][-1]['status']==status
    for status in ['assigned','picked_up']:
        out=call({'status':status},{'type':'reject','reason':'parcel damaged'})
        assert out['status']=='rejected'
    allowed={('created','assign'),('assigned','pickup'),('picked_up','deliver'),('assigned','reject'),('picked_up','reject')}
    for status in ['created','assigned','picked_up','delivered','rejected']:
        for kind in ['assign','pickup','deliver','reject']:
            if (status,kind) not in allowed:
                error(call({'status':status,'history':[]},{'type':kind,'receiver':'Sample','photo':'ref','reason':'reason'}))

def ru003():
    state={'status':'picked_up','history':[]}
    for proof in [{'photo':'photo-ref'},{'signature':'signature-ref'},{'photo':'photo-ref','signature':'signature-ref'}]:
        out=call(state,{'type':'deliver','receiver':'Sample receiver',**proof})
        assert not out.get('error') and out['status']=='delivered'
        assert out['proof']['receiver']=='Sample receiver'
        for key in ['photo','signature']:assert out['proof'].get(key)==proof.get(key)
    for receiver in [None,'','  ',23,[]]:
        error(call(state,{'type':'deliver','receiver':receiver,'photo':'ref'}))
    for proof in [{},{'photo':''},{'signature':' '},{'photo':False},{'signature':{}},{'photo':None,'signature':None}]:
        error(call(state,{'type':'deliver','receiver':'Sample',**proof}))
    for valid,invalid in [('photo','signature'),('signature','photo')]:
        for malformed in ['', ' \t ', False, 23, [], {}]:
            original={**state,'meta':{'keep':[1,2]}}
            out=call(original,{'type':'deliver','receiver':'Sample',valid:'valid-ref',invalid:malformed})
            error(out)
            for key,value in original.items():assert out[key]==value
            assert not out.get('proof')

def ru004():
    for status in ['assigned','picked_up']:
        for reason in [None,'',' \t ',42,False,[],{}]:
            error(call({'status':status},{'type':'reject','reason':reason}))
        for reason in ['box damaged','  recipient unavailable  ','拒收测试']:
            out=call({'status':status},{'type':'reject','reason':reason})
            assert not out.get('error') and out['status']=='rejected'
            assert out['rejection']['reason'].strip()==reason.strip()

def ru005():
    for status,action in [('created',{'type':'deliver','receiver':'Sample','photo':'ref'}),('picked_up',{'type':'deliver','receiver':'Sample'}),('assigned',{'type':'reject','reason':' '}),('unknown',{'type':'assign'})]:
        order={'id':'synthetic','status':status,'history':[{'type':'previous'}],'proof':{'photo':'old'},'rejection':{'reason':'old'},'meta':{'nested':[1,2]}}
        out=call(order,action);error(out)
        for key,value in order.items():assert out[key]==value
    prior={'status':'created','history':[],'error':{'code':'previous'},'meta':{'nested':[1,2]}}
    out=call(prior,{'type':'assign'})
    assert not out.get('error') and out['meta']==prior['meta'] and out['status']=='assigned'
