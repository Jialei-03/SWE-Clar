"""Bounded immutable-ID container removal; no task/test semantics."""
import json
import re
import subprocess
import time

class RemovalError(RuntimeError):
    pass

class BoundedRemoval:
    """One removal request per immutable ID, with a shared 120-second budget."""
    def __init__(self, expected, emit, run=subprocess.run,
                 clock=time.monotonic, sleep=time.sleep, budget=120):
        self.expected, self.emit, self.run = expected, emit, run
        self.clock, self.sleep, self.budget = clock, sleep, budget
        self.blocked = set()

    def remove(self, name):
        if name in self.blocked:
            raise RemovalError('Previous cleanup exhausted/failed; no repeated removal: ' + name)
        deadline = self.clock() + self.budget

        def command(args, limit=10):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise RemovalError('Removal deadline exhausted: ' + name)
            try:
                p = self.run(args, capture_output=True, text=True,
                             timeout=min(limit, remaining))
            except subprocess.TimeoutExpired:
                self.emit({'args': args, 'timeout': True})
                raise
            self.emit({'args': args, 'rc': p.returncode,
                       'stdout': p.stdout, 'stderr': p.stderr})
            return p

        def inspect(target):
            p = command(['docker', 'container', 'inspect', target])
            if p.returncode:
                if re.search(r'(?im)^Error(?: response from daemon)?: No such (?:container|object):\s*'
                             + re.escape(target) + r'\s*$', p.stderr.strip()):
                    return None
                raise RemovalError('Inspect did not confirm absence: ' + p.stderr)
            data = json.loads(p.stdout)
            if not isinstance(data, list) or len(data) != 1 or not data[0].get('Id'):
                raise RemovalError('Malformed container metadata')
            return data[0]

        try:
            original = inspect(name)
            if original is None:
                return
            if not self.expected(original):
                raise RemovalError('Container ownership/fingerprint mismatch: ' + name)
            cid = original['Id']
            if not re.fullmatch('[0-9a-f]{64}', cid):
                raise RemovalError('Expected immutable full container ID')
            if original.get('State', {}).get('Status') != 'removing':
                try:
                    p = command(['docker', 'rm', '-f', cid], 30)
                    if p.returncode and not any(s in p.stderr.lower() for s in
                            ['already in progress', 'no such container', 'no such object']):
                        raise RemovalError('Removal failed: ' + p.stderr)
                except subprocess.TimeoutExpired:
                    pass  # Docker daemon may still be removing the fixed ID.
            while True:
                if inspect(cid) is None:
                    replacement = inspect(name)
                    if replacement is not None:
                        raise RemovalError('Name reused during removal; replacement left untouched')
                    return
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise RemovalError('Removal deadline exhausted: ' + name)
                self.sleep(min(1, remaining))
        except Exception:
            self.blocked.add(name)
            raise
