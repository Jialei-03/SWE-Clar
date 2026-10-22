import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Slot
from run_interaction import disclosure_schedule, observable_coding_summary, seed_patch


class ProtocolTests(unittest.TestCase):
    def slot(self, id, public=False, private=False):
        return Slot(slot_id=id, initially_visible=public, private_or_non_disclosable=private,
                    temporal_origin='initially_public' if public else 'preexisting_private', prepared_answer='fact')

    def test_order_and_round_zero(self):
        rows = disclosure_schedule([self.slot('3'), self.slot('1', True), self.slot('2')])
        self.assertEqual([[s.slot_id for s in row] for row in rows], [['1'], ['2'], ['3']])

    def test_zero_public_is_not_replaced_by_hidden(self):
        self.assertEqual(disclosure_schedule([self.slot('1')])[0], [])

    def test_private_not_disclosed(self):
        self.assertEqual(disclosure_schedule([self.slot('1', private=True)]), [[]])

    def test_no_future_goal_in_earlier_round(self):
        rows = disclosure_schedule([self.slot('1'), self.slot('2')])
        self.assertNotIn('2', [s.slot_id for row in rows[:2] for s in row])

    def test_summary_does_not_copy_tests_or_audit(self):
        d = {'evaluation': {'secret': 123}, 'branches': {'audit': {'answer': 'secret'},
             'coding': {'actions': [{'done': True, 'message': 'mine',
                 'delivery_submission': {'checks': ['own check']}, 'test_results': 'SECRET'}]}}}
        self.assertEqual(observable_coding_summary(d), [{'summary': 'mine', 'own_checks': ['own check']}])

    def test_snapshot_allowlist_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'previous'; runtime = source/'_runtime'; runtime.mkdir(parents=True)
            (runtime/'task.patch').write_text('patch'); (runtime/'runtime.json').write_text('{}')
            (runtime/'verifier.json').write_text('SECRET')
            hashes = [seed_patch(source, root/name) for name in ['audit', 'coding', 'inspect']]
            self.assertEqual(len(set(hashes)), 1)
            self.assertEqual(sorted(p.name for p in (root/'audit/_runtime').iterdir()), ['runtime.json', 'task.patch'])
            with self.assertRaises(AssertionError): seed_patch(source, root/'audit')

    def test_missing_code_stops_instead_of_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError): seed_patch(Path(tmp)/'old', Path(tmp)/'new')

    def test_initial_snapshot_is_pristine(self):
        self.assertIsNone(seed_patch(None, Path('/unused')))


if __name__ == '__main__': unittest.main()
