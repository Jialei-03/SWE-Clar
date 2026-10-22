"""Public mode and persistence regression checks."""
from control_support import Application
seed={'users':{'parent':{'role':'parent'},'child':{'role':'child','parent_id':'parent'},'other':{'role':'parent'}}}
with Application(seed) as app:
    args={'type':'configure_mode','user_id':'parent','child_id':'child','device_id':'device','mode':'parent_child'}
    result=app.request('/action',args)
    assert result['devices']['device']['owner_id']=='child'
    assert result['devices']['device']['parent_id']=='parent'
    saved=app.request('/state')
    assert app.request('/action',{**args,'device_id':'cross','user_id':'other'})['error']['code']=='link_denied'
    assert app.request('/state')==saved
    app.restart();assert app.request('/state')==saved
print('Public mode and persistence checks passed')
