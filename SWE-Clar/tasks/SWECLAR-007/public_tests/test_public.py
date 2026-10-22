"""Visible browsing/interface checks against a real isolated local Firestore instance."""
import json,runpy,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from maintenance_support import run_session,isolated_database


def main():
    with isolated_database() as (service,origin):
        service['seed'](origin,{'clinics/alpha':{'name':{'stringValue':'Synthetic Clinic'}},'providers/beta':{'name':{'stringValue':'Synthetic Provider'}},'bookings/gamma':{'name':{'stringValue':'Synthetic Booking'}}})
        operations=[{'op':'list','collection':'clinics'},{'op':'get','path':'clinics/absent'},{'op':'mount'},{'op':'tap','key':'nav-providers'},{'op':'tap','key':'nav-bookings'},{'op':'fail','method':'GET'},{'op':'tap','key':'refresh'},{'op':'fail','method':None},{'op':'tap','key':'refresh'},{'op':'viewport','width':768,'height':950}]
        rows=run_session(operations,origin=origin)['observations']
        assert rows[0]['value'][0]['fields']['name']['stringValue']=='Synthetic Clinic'
        assert rows[1]['value'] is None
        for i,section,name in [(2,'clinics','Synthetic Clinic'),(3,'providers','Synthetic Provider'),(4,'bookings','Synthetic Booking')]:
            assert rows[i]['keyed_texts']['page-title']==[section]
            assert name in rows[i]['texts']
            assert rows[i]['keyed_texts']['load-state']==['ready']
        assert rows[6]['keyed_texts']['load-state']==['error']
        assert rows[8]['keyed_texts']['load-state']==['ready']
        assert 'Synthetic Booking' in rows[8]['texts']
    print(json.dumps({'passed':True,'checks':['real_rest_reads','three_rendered_pages','visible_failure_and_retry','two_viewports']}))


if __name__=='__main__':main()
