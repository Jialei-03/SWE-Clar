"""Public regression checks: authentication, visible UI and slot publication only."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clinic_support import CandidateFailure, ClinicSession, EnvironmentFailure

NOW = 2051222400000


def check(condition, message):
    if not condition:
        raise CandidateFailure(message)


def run_checks():
    results = []
    with ClinicSession(now_ms=NOW) as s:
        def login(username, password):
            response = s.api('POST', '/api/login', {'username': username, 'password': password})
            check(response['status'] == 200, 'A documented synthetic account could not log in')
            return response['body']['token']
        patient = login('patient.one', 'synthetic-patient-one')
        staff = login('staff.amber', 'synthetic-staff-amber')
        other_staff = login('staff.teal', 'synthetic-staff-teal')
        check(s.api('GET', '/api/catalog')['status'] == 401, 'Catalog must require authentication')
        check(s.api('POST', '/api/login', {'username':'patient.one','password':'wrong'})['status'] == 401, 'Incorrect credentials were accepted')
        me = s.api('GET', '/api/me', token=patient)
        check(me['body']['user']['id'] == 'patient_one' and me['body']['user']['role'] == 'patient', 'Authenticated profile has the wrong identity')
        catalog = s.api('GET', '/api/catalog', token=patient)
        check(catalog['status'] == 200 and catalog['body']['now_ms'] == NOW, 'Catalog does not use the supplied clock')
        check(len(catalog['body']['clinics']) == 2 and len(catalog['body']['providers']) == 3 and 'users' not in catalog['body'], 'Catalog structure or private fields changed')
        results.append('Authenticated HTTP profile/catalog regression')

        slot = {'id': 'public_slot', 'provider_id': 'provider_one', 'start_ms': NOW + 3600000}
        check(s.api('POST', '/api/slots', slot, patient)['status'] == 403, 'A patient published a slot')
        check(s.api('POST', '/api/slots', slot, other_staff)['status'] == 403, 'Staff published outside their clinic')
        response = s.api('POST', '/api/slots', slot, staff)
        check(response['status'] == 201 and response['body']['slot']['end_ms'] == NOW + 5400000, 'Staff slot creation or 30-minute duration is wrong')
        check(s.api('POST', '/api/slots', slot, staff)['status'] == 409, 'Duplicate slot identifier was accepted')
        check(s.api('POST', '/api/slots', {**slot, 'id':'overlap', 'start_ms':NOW + 3660000}, staff)['status'] == 409, 'Overlapping provider intervals were accepted')
        check(s.api('POST', '/api/slots', {**slot, 'id':'adjacent', 'start_ms':NOW + 5400000}, staff)['status'] == 201, 'Adjacent half-open slot interval was rejected')
        for value in [NOW, NOW + 1, True]:
            check(s.api('POST', '/api/slots', {**slot, 'id':'invalid_time', 'start_ms':value}, staff)['status'] == 400, 'Invalid/nonfuture/minute time was accepted')
        available = s.api('GET', '/api/slots?clinic_id=clinic_amber&provider_id=provider_one', token=patient)
        slots = available['body']['slots']
        check(available['status'] == 200 and [r['id'] for r in slots[:2]] == ['public_slot', 'adjacent'], 'Available slots are not ordered or filtered correctly')
        check(s.api('GET', '/api/slots?clinic_id=clinic_amber&provider_id=provider_three', token=patient)['status'] == 400, 'Cross-clinic provider filter was not rejected')
        results.append('Staff scope, slot time boundaries, overlap and availability regression')

        s.restart_backend()
        check(s.api('GET', '/api/me', token=patient)['status'] == 200, 'Session did not survive service restart')
        after = s.api('GET', '/api/slots?clinic_id=clinic_amber&provider_id=provider_one', token=patient)
        check(after['body']['slots'] == slots, 'Published slots did not persist across restart')
        check(s.api('POST', '/api/logout', {}, patient)['status'] == 200, 'Logout failed')
        check(s.api('GET', '/api/me', token=patient)['status'] == 401, 'Logged-out token remained usable')
        check(s.api('GET', '/api/me', token=staff)['status'] == 200, 'Logout invalidated another session')
        results.append('Restart persistence and independent session logout')

        s.ui({'op':'mount'})
        s.ui({'op':'enter_text','key':'login-username','text':'staff.amber'})
        s.ui({'op':'enter_text','key':'login-password','text':'synthetic-staff-amber'})
        row = s.ui({'op':'tap','key':'login-submit'})
        check(row['error'] is None and 'Synthetic Staff Amber' in row['texts'], 'Staff UI login did not render the authenticated identity')
        s.ui({'op':'tap','key':'nav-publish'})
        s.ui({'op':'enter_text','key':'slot-id','text':'public_ui_slot'})
        s.ui({'op':'enter_text','key':'slot-start','text':str(NOW + 7200000)})
        row = s.ui({'op':'tap','key':'publish-submit'})
        check(row['error'] is None and 'slot-public_ui_slot' in row['keyed_texts'], 'Real staff UI did not render the newly published slot')
        actual = s.api('GET','/api/slots?clinic_id=clinic_amber&provider_id=provider_one',token=staff)['body']['slots']
        check(any(r['id']=='public_ui_slot' and r['start_ms']==NOW+7200000 for r in actual), 'Staff UI did not actually persist the new slot through HTTP')
        s.ui({'op':'capture','name':'public-staff.png'})
        row = s.ui({'op':'tap','key':'logout'})
        check('login-username' in row['keyed_texts'] and 'nav-publish' not in row['keyed_texts'], 'Logout did not clear staff controls')
        results.append('Actual Flutter login, publication, rendered capture and logout')
    return results


def main():
    try:
        results = run_checks()
        print(json.dumps({'passed':True,'public_regressions':results,'hidden_business_requirements_tested':False}))
        return 0
    except CandidateFailure as exc:
        print(json.dumps({'passed':False,'failure_type':'candidate_regression','error':str(exc)}))
        return 1
    except (KeyError, TypeError, IndexError) as exc:
        print(json.dumps({'passed':False,'failure_type':'candidate_regression','error':'Application response shape is incompatible: '+str(exc)}))
        return 1
    except Exception as exc:
        print(json.dumps({'passed':False,'failure_type':'environment_or_public_test_error','error':repr(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
