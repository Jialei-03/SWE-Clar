from copy import deepcopy
from conftest import load_solution

def _fcb_contains_expected_fields(actual, expected):
    return isinstance(actual, dict) and all((key in actual and actual[key] == value for key, value in expected.items()))

def _collection_values(value):
    if isinstance(value, dict):
        return list(value.values())
    return list(value) if isinstance(value, list) else []

def base():
    return {'users': {'l': {'profile_image': 'l0'}, 'r': {'profile_image': 'r0'}}, 'sessions': ['l', 'r'], 'fee_rate': 0.15}

def active(m):
    s = m.process_review_action(base(), {'type': 'create_listing', 'listing_id': 'x', 'owner_id': 'l', 'price': 100})
    s = m.process_review_action(s, {'type': 'apply', 'application_id': 'a', 'listing_id': 'x', 'reviewer_id': 'r'})
    return m.process_review_action(s, {'type': 'accept', 'application_id': 'a', 'owner_id': 'l'})

def paid(m):
    return m.process_review_action(active(m), {'type': 'payment', 'event_id': 'p', 'listing_id': 'x', 'payer_id': 'l', 'amount': 100})

def test_ru_001():
    m = load_solution()
    m.process_review_action = _assert_result_contract(m.process_review_action)
    s = base()
    old = deepcopy(s)
    m.process_review_action(s, {'type': 'profile_image', 'user_id': 'l', 'image_ref': 'new'})
    assert s == old

def test_ru_002():
    m = load_solution()
    s = active(m)
    assert s['applications']['a']['status'] == 'accepted' and s['listings']['x']['status'] == 'awaiting_payment'
    assert m.process_review_action(s, {'type': 'apply', 'application_id': 'z', 'listing_id': 'x', 'reviewer_id': 'r'})['error']['code']

def test_ru_003():
    m = load_solution()
    s = paid(m)
    submission = {'type': 'submit_review', 'review_id': 'a', 'reviewer_id': 'r', 'images': ['1', '2', '3', '4', '5']}
    r = m.process_review_action(s, submission)
    expected = {'image_count': len(submission['images']), 'url_skipped': not bool(submission.get('url'))}
    assert _fcb_contains_expected_fields(r['result'], expected)
    assert m.process_review_action(paid(m), {'type': 'submit_review', 'review_id': 'a', 'reviewer_id': 'r', 'images': ['1', '2', '3', '4', '5', '6']})['error']['code']
    assert 'error' in m.process_review_action(active(m), submission)

def test_ru_004():
    m = load_solution()
    active_state = active(m)
    payment_command = {'type': 'payment', 'event_id': 'p', 'listing_id': 'x', 'payer_id': 'l', 'amount': 100}
    s = paid(m)
    fee = round(payment_command['amount'] * active_state['fee_rate'], 2)
    expected_payment = {'event_id': payment_command['event_id'], 'payer_id': payment_command['payer_id'], 'receiver_id': active_state['applications']['a']['reviewer_id'], 'gross': float(payment_command['amount']), 'eligible': round(payment_command['amount'] - fee, 2), 'platform_fee': fee, 'status': 'held'}
    matching_payments = [row for row in _collection_values(s['payments']) if _fcb_contains_expected_fields(row, expected_payment)]
    assert len(matching_payments) == 1
    s = m.process_review_action(s, {'type': 'payment', 'event_id': 'p', 'listing_id': 'x', 'payer_id': 'l', 'amount': 100})
    assert s['processed_events'] == ['p']
    assert 'error' in m.process_review_action(s, {'type': 'approve_review', 'listing_id': 'x', 'owner_id': 'l'})
    s = m.process_review_action(s, {'type': 'submit_review', 'review_id': 'a', 'reviewer_id': 'r', 'images': []})
    s = m.process_review_action(s, {'type': 'approve_review', 'listing_id': 'x', 'owner_id': 'l'})
    s = m.process_review_action(s, {'type': 'approve_review', 'listing_id': 'x', 'owner_id': 'l'})
    expected_payout = {'listing_id': payment_command['listing_id'], 'receiver_id': expected_payment['receiver_id'], 'amount': expected_payment['eligible']}
    matching_payouts = [row for row in _collection_values(s['payouts']) if _fcb_contains_expected_fields(row, expected_payout)]
    assert len(matching_payouts) == 1

def test_ru_005():
    m = load_solution()
    s = base()
    s = m.process_review_action(s, {'type': 'profile_image', 'user_id': 'l', 'image_ref': 'new'})
    assert s['users']['l']['profile_image'] == 'new' and s['users']['r']['profile_image'] == 'r0'
    s = m.process_review_action(s, {'type': 'delete_account', 'user_id': 'l'})
    assert 'l' not in s['users'] and s['sessions'] == ['r'] and (s['users']['r']['profile_image'] == 'r0')


def _assert_result_contract(function):
    """Verify the declared JSON-object entry contract on the RU-001 calls."""
    from copy import deepcopy
    import json

    def checked(*args, **kwargs):
        before = deepcopy((args, kwargs))
        result = function(*args, **kwargs)
        assert isinstance(result, dict), "entry point must return a JSON object"
        assert (args, kwargs) == before, "entry point mutated its inputs"
        json.dumps(result, allow_nan=False)
        # Metadata may vary across invocations; verify the actual profile transition.
        state, action = args
        if action.get('type') == 'profile_image':
            expected_users = deepcopy(state['users'])
            expected_users[action['user_id']]['profile_image'] = action['image_ref']
            assert not result.get('error')
            for user_id, fields in expected_users.items():
                assert _fcb_contains_expected_fields(result['users'][user_id], fields)
            assert set(result['users']) == set(expected_users)
            assert result['sessions'] == state['sessions']
        return result

    return checked
