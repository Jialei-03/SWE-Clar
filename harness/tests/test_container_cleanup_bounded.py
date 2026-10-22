import json
import subprocess
import types
import unittest
from pathlib import Path
import ast
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.container_cleanup import BoundedRemoval, RemovalError

def runtime_class(base):
    source = Path(__file__).resolve().parents[1] / 'runtime/task_runtime.py'
    module = ast.parse(source.read_text())
    original = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'OfficialTaskRuntime')
    selected = [n for n in original.body if isinstance(n, ast.FunctionDef)
                and n.name in ('run_verifier', '_cleanup_owned')]
    scope = dict(globals())
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), scope)
    return type('MockRuntime', (base,), {**{n.name: scope[n.name] for n in selected},
                '_remove_container': lambda self, name: self.remover.remove(name)})


CID = 'a' * 64
NAME = 'owned-test'


class MockDocker:
    def __init__(self, mode):
        self.mode, self.now, self.calls, self.removed = mode, 0, [], False
    def sleep(self, seconds):
        self.now += seconds
    def run(self, args, **kw):
        self.calls.append(args)
        if args[1] == 'rm':
            self.removed = True
            if self.mode in ('timeout', 'permanent'):
                self.now += kw['timeout']
                raise subprocess.TimeoutExpired(args, kw['timeout'])
            if self.mode == 'in-progress':
                return subprocess.CompletedProcess(args, 1, '', 'removal is already in progress')
            return subprocess.CompletedProcess(args, 0, CID, '')
        target = args[-1]
        if self.mode == 'daemon':
            return subprocess.CompletedProcess(args, 1, '', 'Cannot connect to the Docker daemon')
        if self.mode == 'missing' or (self.removed and self.mode != 'permanent'):
            if self.mode == 'replacement' and target == NAME:
                data = [{'Id': 'b' * 64, 'State': {}}]
            else:
                return subprocess.CompletedProcess(args, 1, '', 'Error: No such container: ' + target)
        else:
            data = [{'Id': CID, 'State': {'Status': 'running'}}]
        return subprocess.CompletedProcess(args, 0, json.dumps(data), '')


class Regression(unittest.TestCase):
    def helper(self, mode, expected=lambda _: True):
        docker = MockDocker(mode)
        helper = BoundedRemoval(expected, lambda _: None, run=docker.run,
                                clock=lambda: docker.now, sleep=docker.sleep, budget=35)
        return helper, docker
    def test_success_missing_timeout_and_in_progress(self):
        for mode in ('success', 'missing', 'timeout', 'in-progress'):
            with self.subTest(mode=mode):
                helper, docker = self.helper(mode)
                helper.remove(NAME)
                helper.remove(NAME)
                removals = [x for x in docker.calls if x[1] == 'rm']
                self.assertEqual(len(removals), 0 if mode == 'missing' else 1)
                self.assertTrue(all(x[-1] == CID for x in removals))
    def test_permanent_is_bounded_and_not_retried(self):
        helper, docker = self.helper('permanent')
        with self.assertRaises(RemovalError): helper.remove(NAME)
        count = len(docker.calls)
        with self.assertRaises(RemovalError): helper.remove(NAME)
        self.assertEqual(count, len(docker.calls))
        self.assertLessEqual(docker.now, 35)
        self.assertEqual(sum(x[1] == 'rm' for x in docker.calls), 1)
    def test_daemon_failure_and_wrong_owner_do_not_delete(self):
        for mode, expected in [('daemon', lambda _: True), ('success', lambda _: False)]:
            helper, docker = self.helper(mode, expected)
            with self.assertRaises(RemovalError): helper.remove(NAME)
            self.assertFalse(any(x[1] == 'rm' for x in docker.calls))
    def test_replacement_not_deleted(self):
        helper, docker = self.helper('replacement')
        with self.assertRaises(RemovalError): helper.remove(NAME)
        self.assertEqual([x[-1] for x in docker.calls if x[1] == 'rm'], [CID])
    def test_original_error_survives_cleanup_failure(self):
        original = ValueError('verifier failure')
        class Base:
            spec = types.SimpleNamespace(phase_sealed_support=True, provenance=lambda: {})
            def _run_verifier(self, *args): raise original
            def _container_name(self, sid): return NAME
            def _persist_verifier_evidence(self, work, evidence):
                self.saved = evidence
                return {'sha256': 'mock'}
        runtime = runtime_class(Base)()
        runtime.remover = types.SimpleNamespace(remove=lambda name: (_ for _ in ()).throw(RemovalError('cleanup failure')))
        with self.assertRaises(ValueError) as caught:
            runtime.run_verifier('sid', '.', '.')
        self.assertIs(caught.exception, original)
        self.assertEqual(runtime.saved['cleanup_error']['message'], 'cleanup failure')

    def test_only_own_pinned_unstarted_seed_is_eligible(self):
        class Base:
            spec = types.SimpleNamespace(image_ref='image@sha256:pinned')
            def _is_expected_container(self, c): return False
        runtime = runtime_class(Base)()
        runtime.owned_seeds = {'own-seed': CID}
        seed = {'Id': CID, 'Name': '/own-seed', 'Config': {'Image': 'image@sha256:pinned'},
                'HostConfig': {'NetworkMode': 'none'}, 'State': {'Status': 'created', 'Running': False}}
        self.assertTrue(runtime._cleanup_owned(seed))
        swapped = dict(seed, Id='b' * 64)
        self.assertFalse(runtime._cleanup_owned(swapped))
        for section, key, value in [('Config', 'Image', 'other'), ('HostConfig', 'NetworkMode', 'host'),
                                     ('State', 'Running', True)]:
            changed = json.loads(json.dumps(seed)); changed[section][key] = value
            self.assertFalse(runtime._cleanup_owned(changed))
        seed['Name'] = '/other-worker-seed'
        self.assertFalse(runtime._cleanup_owned(seed))


if __name__ == '__main__':
    unittest.main()
