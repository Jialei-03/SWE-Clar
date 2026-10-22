from pathlib import Path
import os,sys,copy
sys.path.insert(0,os.environ.get('CANDIDATE_ROOT','/workspace'))
from solution import process_presave_action as run
s={};a={'type':'create_artist','artist_id':'artist'};before=copy.deepcopy(a);s=run(s,a);assert a==before
s=run(s,{'type':'create_release','artist_id':'artist','release_id':'release','release_at':10,'now':0,'spotify_uri':'spotify:track:'+'A'*22});s=run(s,{'type':'publish_campaign','release_id':'release','slug':'song'})
assert s['campaigns']['song']['release_id']=='release'
assert 'error' in run(s,{'type':'publish_campaign','release_id':'release','slug':'other'})
s['listeners']['listener']={'provider_user_id':'synthetic','scopes':['user-library-modify']}
e={'type':'presave','slug':'song','listener_id':'listener','consent':True};first=run(s,e);second=run(first,e)
assert first['presaves']==second['presaves'] and all(first['result'][k]==second['result'][k] for k in ['slug','listener_id','consent','fulfilled'])
print('PASS: artist/release smoke, campaign uniqueness and presave replay regression')
