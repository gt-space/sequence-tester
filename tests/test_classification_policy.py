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

class DynamicBindings(unittest.TestCase):
    def test_opaque_attribute_and_rebound_api_are_not_false_passes(self):
        for source in ['holder=[valve]\nx=holder[0].name', 'import common\ncommon.wait_for = lambda: None\ncommon.wait_for()', 'valve_alias=valve\nvalve_alias.extra=True']:
            result=run_sequence(source,ENV,False)
            self.assertNotEqual(result['checks']['api'],'pass',result)
    def test_rebound_api_is_not_falsely_rejected_as_original_signature(self):
        result=run_sequence('wait_for = lambda: None\nwait_for()',ENV,True)
        self.assertEqual(result['checks']['api'],'partial',result)
        self.assertEqual(result['checks']['runtime'],'pass',result)
    def test_valid_unpacked_timeout_is_partial_but_executes(self):
        result=run_sequence('wait_until(**{"condition": lambda: True, "timeout": 1*s})',ENV,True)
        self.assertEqual(result['checks']['api'],'partial',result)
        self.assertEqual(result['checks']['runtime'],'pass',result)

class SimulationLimits(unittest.TestCase):
    def test_valid_but_unmodeled_import_and_exception_paths_are_partial(self):
        for source in ['import json\nprint(json.dumps({}))', '# exceptions\ntry:\n    valve.open()\nexcept Exception:\n    pass']:
            result=run_sequence(source,ENV,False)
            self.assertEqual(result['checks']['api'],'partial',result)

class FunctionScope(unittest.TestCase):
    def test_local_parameter_can_shadow_api(self):
        result=run_sequence('# local callback\ndef f(wait_for):\n    wait_for()\nf(lambda: None)',ENV,True)
        self.assertEqual(result['checks']['api'],'partial',result)
        self.assertEqual(result['checks']['runtime'],'pass',result)
    def test_unexecuted_function_failure_is_partial(self):
        result=run_sequence('# unused helper\ndef unused():\n    valve.open(True)',ENV,True)
        self.assertEqual(result['checks']['api'],'partial',result)
        self.assertEqual(result['checks']['runtime'],'pass',result)
