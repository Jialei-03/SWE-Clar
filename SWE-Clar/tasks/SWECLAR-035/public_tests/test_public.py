"""Public regressions for the provided account lifecycle and JSON adapter."""
import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

WORKSPACE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path.cwd()
sys.path.insert(0, str(WORKSPACE))
spec = importlib.util.spec_from_file_location("candidate_solution", WORKSPACE / "solution.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Accounts(unittest.TestCase):
    def test_account_lifecycle_and_input_preservation(self):
        for provider in ("email", "social", "fast_checkout"):
            with self.subTest(provider=provider):
                state = {"products": {}, "coupons": {}}
                action = {"type": "create_account", "user_id": "sample-user", "email": "member@example.org",
                          "phone": "synthetic-contact", "provider": provider,
                          "card": {"number": "synthetic-pan-do-not-store", "security_code": "synthetic-cvv-do-not-store"}}
                before = copy.deepcopy((state, action))
                first = module.process_membership_action(state, action)
                self.assertEqual((state, action), before)
                self.assertNotIn("synthetic-pan-do-not-store", json.dumps(first))
                self.assertNotIn("synthetic-cvv-do-not-store", json.dumps(first))
                second = module.process_membership_action(first, dict(action, email="other@example.org", phone="other-contact"))
                account = second["users"]["sample-user"]
                self.assertEqual(account["email"].casefold(), action["email"].casefold())
                self.assertEqual(account["phone"], action["phone"])
                self.assertEqual(len(second["users"]), 1)
                deleted = module.process_membership_action(second, {"type": "delete_account", "user_id": "sample-user"})
                self.assertEqual(deleted["users"]["sample-user"]["status"], "inactive")
                replay = module.process_membership_action(deleted, action)
                self.assertEqual(replay["users"]["sample-user"]["status"], "inactive")

    def test_cli(self):
        fixture = json.loads((WORKSPACE / "examples/account.json").read_text())
        result = subprocess.run([sys.executable, str(WORKSPACE / "solution.py")], cwd=WORKSPACE,
                                input=json.dumps(fixture), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["users"]["sample-user"]["email"], "member@example.org")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
