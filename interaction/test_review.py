import unittest
from review_adapter import validate_decision
from pathlib import Path

class ReviewTests(unittest.TestCase):
    def d(self,decision='finish_task',status='confirmed',remaining=False):
        return dict(decision=decision,review=[dict(aspect='job',status=status,basis='Client agreement')],
                    implementation_remaining=remaining,message='Which interface?',reason='Grounded review')
    def test_no_finish_before_coding(self):
        with self.assertRaises(ValueError):validate_decision(self.d(),0)
    def test_no_finish_with_open_assumption(self):
        with self.assertRaises(ValueError):validate_decision(self.d(status='open'),1)
    def test_no_finish_with_remaining_work(self):
        with self.assertRaises(ValueError):validate_decision(self.d(remaining=True),1)
    def test_implement_is_not_finish(self):
        self.assertEqual(validate_decision(self.d('implement_next',remaining=True),1)['decision'],'implement_next')
    def test_finish_allowed_without_forced_questions(self):
        self.assertEqual(validate_decision(self.d(),1)['decision'],'finish_task')
    def test_design_choice_not_forced_question(self):
        validate_decision(self.d(status='design_choice'),1)
    def test_ask_allowed(self):
        validate_decision(self.d('ask_client','open',True),1)

if __name__=='__main__':unittest.main()
