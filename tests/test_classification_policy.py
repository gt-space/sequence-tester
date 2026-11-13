"""Compatibility decisions, distinct from simulating a valid Python program."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from engine import run_sequence
ENV={'valves':['valve'],'sensors':[]}
class ClassificationPolicy(unittest.TestCase):
    def test_deterministic_path_failures_block_execution(self):
        for source in ['if True:\n    valve.open()', '@staticmethod\ndef f():\n    pass', 'from __future__ import annotations\nvalve.open()', '# café\nvalve.open()', '# 🚀\nvalve.open()']:
            with self.subTest(source=source):
                r=run_sequence(source,ENV,True)
                self.assertEqual(r['checks']['api'],'fail',r)
                self.assertEqual(r['checks']['runtime'],'not_run',r)
    def test_timeout_must_be_explicit_finite_nonnegative(self):
        for call in ['wait_until(lambda: True)','wait_until(lambda: True, None)','wait_until(lambda: True, float("inf")*s)','wait_until(lambda: True, float("nan")*s)','wait_until(lambda: True, -1*s)','pause = wait_until\npause(lambda: True)']:
            with self.subTest(call=call):
                r=run_sequence(call,ENV,True)
                self.assertEqual(r['checks']['api'],'fail',r)
        self.assertEqual(run_sequence('wait_until(lambda: True, 0*s)',ENV,True)['checks']['runtime'],'pass')
    def test_dynamic_timeout_is_never_fully_verified(self):
        for source in ['d = [1*s]\nwait_until(lambda: True, d[0])','calls = [wait_until]\ncalls[0](lambda: True)']:
            r=run_sequence(source,ENV,True)
            self.assertNotEqual(r['checks']['api'],'pass',r)
    def test_dynamic_access_scopes_and_flow_are_partial(self):
        for source in ['# helper\ndef f(x):\n    x.open()\nf(valve)', 'name="open"\ngetattr(valve,name)()', 'a=vars(valve)', 'x = valve.__dict__', '# branch\nif False:\n    x=valve\nelse:\n    x=valve\nx.open()', 'fn = lambda: valve.open()\nfn()']:
            with self.subTest(source=source):
                r=run_sequence(source,ENV,False)
                self.assertNotEqual(r['checks']['api'],'pass',r)
    def test_blocked_code_does_not_mutate_source(self):
        text='# café\nvalve.open()\n'
        run_sequence(text,ENV,True)
        self.assertEqual(text,'# café\nvalve.open()\n')
