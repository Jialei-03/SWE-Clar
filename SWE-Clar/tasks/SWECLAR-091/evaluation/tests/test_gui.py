#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import json
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CANDIDATE = Path(sys.argv[1]).resolve()
TEST_DIR = Path(__file__).resolve().parent
sys.argv = [sys.argv[0]]


def _cpp_lexical_source(source: str, *, keep_string_contents: bool) -> str:
    """Remove C++ comments and optionally retain literal contents."""
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            raw = re.match(r'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(', source[index:])
            if raw:
                end = source.find(')' + raw.group(1) + '"', index + raw.end())
                if end >= 0:
                    end += len(raw.group(1)) + 2
                    text = source[index:end]
                    output.append(text if keep_string_contents else ''.join('\n' if c == '\n' else ' ' for c in text))
                    index = end
                    continue
            if char == "/" and nxt == "/":
                output.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and nxt == "*":
                output.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char in {'"', "'"}:
                quote = char
                output.append(char)
                index += 1
                state = "literal"
                continue
            output.append(char)
            index += 1
            continue
        if state == "line_comment":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "code"
            continue
        if state == "block_comment":
            if char == "*" and nxt == "/":
                output.extend("  ")
                index += 2
                state = "code"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if state == "literal":
            if char == "\\" and nxt:
                output.extend((char, nxt) if keep_string_contents else "  ")
                index += 2
            elif char == quote:
                output.append(char)
                index += 1
                state = "code"
            else:
                output.append(char if keep_string_contents else ("\n" if char == "\n" else " "))
                index += 1
    return "".join(output)


def code_without_comments_or_strings(source: str) -> str:
    """Keep C++ tokens while removing comments and literal contents."""
    return _cpp_lexical_source(source, keep_string_contents=False)


def code_without_comments(source: str) -> str:
    """Keep C++ code and string literals while removing comments."""
    return _cpp_lexical_source(source, keep_string_contents=True)


def pane_layout(panes):
    """Compare active placement by pane name, not manager insertion order.

    wxAUI may retain dormant floating coordinates after docking a window.
    Those coordinates do not describe the visible docked layout.
    """
    result = {}
    for pane in panes:
        keys = ['shown', 'floating']
        keys += (['float_x', 'float_y', 'float_w', 'float_h'] if pane['floating']
                 else ['direction', 'layer', 'row', 'position', 'proportion'])
        result[pane['name']] = {key: pane[key] for key in keys}
    return result


_CPP_STRING = r'(?:u8|u|U|L)?"(?:\\.|[^"\\])*"'
_CPP_STRING_SEQUENCE = re.compile(rf'{_CPP_STRING}(?:\s*{_CPP_STRING})*')
_CPP_STRING_TOKEN = re.compile(_CPP_STRING)


def cpp_string_sequence_values(source: str) -> set[str]:
    """Return values of C++ string literals, including adjacent concatenation.

    The delivery contract requires tooltip text to live in ``MainWindowG.h``
    but deliberately does not prescribe constant names.  Looking for one
    exact quoted spelling rejects valid C++ such as ``"Refresh " "modules"``.
    This small lexical reader keeps the structural check name-agnostic while
    matching the language's adjacent-literal semantics.
    """

    source = code_without_comments(source)
    raw_pattern = re.compile(r'(?:u8|u|U|L)?R"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\((?P<body>.*?)\)(?P=delimiter)"', re.DOTALL)
    values: set[str] = set()
    parts: list[str] = []
    index = 0
    while index < len(source):
        raw = raw_pattern.match(source, index)
        regular = _CPP_STRING_TOKEN.match(source, index) if raw is None else None
        if raw:
            parts.append(raw.group('body'))
            index = raw.end()
        elif regular:
            literal = re.sub(r"^(?:u8|u|U|L)", "", regular.group())
            try:
                parts.append(ast.literal_eval(literal))
            except (SyntaxError, ValueError):
                pass
            index = regular.end()
        else:
            if not source[index].isspace() and parts:
                values.add("".join(parts))
                parts = []
            index += 1
    if parts:
        values.add("".join(parts))
    return values


class WorkspaceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed=['cmake','wx-config','xvfb-run','c++']
        if any(not shutil.which(n) for n in needed) or not Path('/public_tests/launch.py').is_file():raise RuntimeError('Required prepared native GUI tools/helpers unavailable')
        cls.temp=tempfile.TemporaryDirectory(prefix='wx-observation-');cls.root=Path(cls.temp.name);cls.root.chmod(0o777);cls.build=cls.root/'build';cls.build_error='';cls.observer=None;cls.counter=0
        for command in [['cmake','-S',str(CANDIDATE),'-B',str(cls.build)],['cmake','--build',str(cls.build),'--parallel','2']]:
            r=cls._run_raw(command,timeout=90)
            if r.returncode:cls.build_error=r.stderr;break
    @classmethod
    def tearDownClass(cls):
        subprocess.run([sys.executable,'-I','-c',"import pathlib,shutil,sys;root=pathlib.Path(sys.argv[1]);[(shutil.rmtree(p) if p.is_dir() else p.unlink()) for p in root.iterdir()]",str(cls.root)],user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},check=True);cls.temp.cleanup()
    @classmethod
    def _run_raw(cls,command,timeout=30):
        cls.counter+=1;proof=cls.root/('process-'+str(cls.counter)+'.json')
        p=subprocess.Popen([sys.executable,'-I','/public_tests/launch.py',str(cls.root),str(proof),*command],env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_PRIVATE_NATIVE_SENTINEL':'parent-only'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:out,err=p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);out,err=p.communicate();return subprocess.CompletedProcess(command,124,out,err+' timeout')
        observed=json.loads(proof.read_text());assert observed['uid']==1000 and observed['cap_eff']==0 and observed['environment_keys']==['HOME','LANG','PATH']
        Path('/private/results').mkdir(parents=True,exist_ok=True)
        with open('/private/results/native-process.jsonl','a') as target:target.write(json.dumps(observed)+'\n')
        return subprocess.CompletedProcess(command,p.returncode,out,err)
    def observe(self,*args):
        cls=type(self)
        if cls.observer is None:
            flags=shlex.split(self._run_raw(['wx-config','--cxxflags']).stdout);libs=shlex.split(self._run_raw(['wx-config','--libs','std,aui']).stdout)
            binary=self.root/'observer';r=self._run_raw(['c++','-std=c++11','-pedantic-errors',*flags,'-I',str(CANDIDATE/'src'),'/public_tests/observe.cpp',*[str(CANDIDATE/'src'/n) for n in ['MainWindowM.cpp','MainWindowV.cpp','MainWindowC.cpp']],'-o',str(binary),*libs],timeout=90);self.assertEqual(r.returncode,0,r.stderr);cls.observer=binary
        r=self._run_raw(['xvfb-run','-a',str(cls.observer),*args],timeout=25);self.assertEqual(r.returncode,0,r.stderr)
        data=json.loads(r.stdout);self.assertNotIn('error',data);self.assertTrue(data['initial']['shown']);self.assertTrue((self.root/'window.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        return data
    def test_ru_001_build_and_window(self):
        self.assertFalse(self.build_error,self.build_error);self.assertTrue((self.build/'workspace_gui').is_file())
        r=self._run_raw(['xvfb-run','-a',str(self.build/'workspace_gui'),'--smoke'],timeout=20);self.assertEqual(r.returncode,0,r.stderr);self.observe('snapshot')
    def test_ru_002_seven_areas(self):
        r=self.observe('snapshot')['initial'];expected={'module_browser':'Module Browser','toolbar':'Toolbar','code_window':'Code Window','property_window':'Property Window','message_box':'Message Box','command_line':'Command Line Interface','property_manager':'Property Manager'}
        observed={p['name']:p['caption'] for p in r['panes']};self.assertTrue(set(expected).issubset(observed));self.assertEqual({name:observed[name] for name in expected},expected);self.assertTrue(all(p['window'] and p['shown'] for p in r['panes'] if p['name'] in expected));self.assertEqual(r['status'],'Ready')
    def test_ru_003_portable_model(self):
        required=['MainWindowM.h','MainWindowM.cpp','MainWindowV.h','MainWindowV.cpp','MainWindowC.h','MainWindowC.cpp','MainWindowG.h']
        self.assertTrue(all((CANDIDATE/'src'/n).is_file() for n in required));model=''.join((CANDIDATE/'src'/n).read_text() for n in ['MainWindowM.h','MainWindowM.cpp']);self.assertNotRegex(code_without_comments(model),r'#\s*include\s*[<"]wx[/\\]')
        source=self.root/'model-probe.cpp';source.write_text('#include "MainWindowM.h"\nint main(){workspace::MainWindowM model;return 0;}\n')
        r=self._run_raw(['c++','-std=c++11','-pedantic-errors','-I',str(CANDIDATE/'src'),str(source),str(CANDIDATE/'src/MainWindowM.cpp'),'-o',str(self.root/'model-probe')]);self.assertEqual(r.returncode,0,r.stderr)
    def test_ru_003_dynamic_controller(self):
        controller=''.join((CANDIDATE/'src'/n).read_text() for n in ['MainWindowC.cpp','MainWindowC.h']);all_code=''.join(p.read_text() for p in (CANDIDATE/'src').glob('*') if p.suffix in ['.h','.cpp']);code=code_without_comments_or_strings(all_code)
        self.assertRegex(code_without_comments_or_strings(controller),r'\b(?:Bind|Connect)\s*\(');self.assertNotRegex(code,r'wx(?:BEGIN_)?EVENT_TABLE|wxDECLARE_EVENT_TABLE|\b(?:wxDialog|ShowModal|wxMessageBox)\b')
    def test_ru_004_menu_toolbar(self):
        r=self.observe('snapshot')['initial'];self.assertEqual(r['menus'],['File','Edit','Verify','Tools','Windows','Help']);self.assertEqual(len(r['toolbars']),2)
        tools=[t for bar in r['toolbars'] for t in bar];self.assertEqual([t['label'] for t in tools],['Update','Select','Unselect','Cancel','Lint','Analyze','Verify','Auto-Verify'])
        constants=cpp_string_sequence_values((CANDIDATE/'src/MainWindowG.h').read_text());self.assertTrue(all(t['tooltip'] and t['tooltip'] in constants for t in tools))
    def test_ru_005_docking_reset(self):
        r=self.observe('reset','property_manager');panes=r['initial']['panes'];self.assertTrue({1,2,3,4,5}.issubset({p['direction'] for p in panes}))
        for p in panes:
            if p['name']=='command_line' or p['name'].endswith('toolbar'):continue
            self.assertTrue(p['dockable'] and p['close'] and p['maximize'])
        self.assertFalse(next(p for p in r['mutated']['panes'] if p['name']=='property_manager')['shown']);self.assertNotEqual(pane_layout(r['mutated']['panes']),pane_layout(r['initial']['panes']));self.assertEqual(pane_layout(r['restored']['panes']),pane_layout(r['initial']['panes']))
    def test_ru_006_session_perspective(self):
        r=self.observe('roundtrip','property_manager');self.assertTrue(r['saved'] and r['accepted']);self.assertEqual(pane_layout(r['restored']['panes']),pane_layout(r['mutated']['panes']));self.assertNotEqual(pane_layout(r['altered']['panes']),pane_layout(r['mutated']['panes']))
        r=self.observe('menu','property_manager','perspective_name','Synthetic layout','Windows','Save perspective','Default perspective');self.assertEqual(pane_layout(r['default_menu']['panes']),pane_layout(r['initial']['panes']));self.assertEqual(pane_layout(r['restored']['panes']),pane_layout(r['mutated']['panes']))
    def test_ru_007_linux_cpp11(self):
        flags=shlex.split(self._run_raw(['wx-config','--cxxflags']).stdout)
        for source in sorted((CANDIDATE/'src').glob('*.cpp')):
            r=self._run_raw(['c++','-std=c++11','-pedantic-errors',*flags,'-I',str(CANDIDATE/'src'),'-c',str(source),'-o',str(self.root/(source.stem+'.o'))],timeout=60);self.assertEqual(r.returncode,0,r.stderr)


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WorkspaceGuiTests)
    tests = list(_flatten(suite))
    loaded_test_ids = {test.id() for test in tests}
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failed = {test.id() for test, _ in result.failures + result.errors}
    skipped = {test.id() for test, _ in result.skipped}
    infrastructure_errors = [
        {"test_id": test.id(), "detail": detail[-4000:]}
        for test, detail in result.errors
        if test.id() not in loaded_test_ids
    ]
    harness_ok = not infrastructure_errors
    grouped = {}
    for test in tests:
        match = re.search(r"\.test_ru_(\d{3})_", test.id())
        if match:
            grouped.setdefault(f"RU-{match.group(1)}", []).append(test.id())
    print(json.dumps({
        "schema_version": 1,
        "harness_ok": harness_ok,
        "infrastructure_error": not harness_ok,
        "infrastructure_errors": infrastructure_errors,
        "results": [
            {
                "ru_id": ru_id,
                "passed": harness_ok and bool(test_ids) and all(
                    test_id not in failed and test_id not in skipped
                    for test_id in test_ids
                ),
            }
            for ru_id, test_ids in sorted(grouped.items())
        ]
    }))
    raise SystemExit(0 if result.wasSuccessful() else 1)
