"""Cases discovered against compiled PyO3 0.21.2, not simulator-derived expectations."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from engine import Simulator, run_sequence

MAPPING = {'valves':['valve'], 'sensors':[{'name':'FTPT','unit':'psi','samples':[{'at':0,'value':300}]}]}

class AuditRegressions(unittest.TestCase):
    def test_compiled_reflected_sensor_boundary(self):
        m=Simulator({'valve':'CLOSED'}, {'FTPT':{'unit':'psi','samples':[{'at':0,'value':300}], 'interpolation':'step'}}).make_module()
        sensor=m.Sensor('FTPT'); p=300*m.psi
        for expr, expected in [('p < sensor',False),('p <= sensor',True),('p == sensor',True),('p != sensor',False),('p > sensor',False),('p >= sensor',True)]:
            with self.subTest(expr=expr): self.assertEqual(eval(expr),expected)

    def test_current_keyword_names_execute(self):
        for source in ['valve.actuate(open=True)', 'p = Pressure(raw=2)', 'create_abort_stage(stage_name="a", abort_condition="False", safe_valve_states={})', 'set_servo_disconnect_abort(enabled=True)', 'launch_lug_arm(sam_hostname="synthetic", should_enable=True)']:
            with self.subTest(source=source):
                r=run_sequence(source,MAPPING,True)
                self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_dynamic_unpacking_cannot_claim_full_verification(self):
        r=run_sequence('args = (500*ms,)\nwait_for(*args)',MAPPING,True)
        self.assertEqual(r['checks']['api'],'partial',r['diagnostics'])

    def test_unknown_reading_matches_float_semantics(self):
        mapping={'valves':[], 'sensors':[{'name':'x','unit':'unknown','samples':[{'at':0,'value':400}]}]}
        r=run_sequence('assert x.read() > 300',mapping,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_wrong_unit_equality_is_legal_false(self):
        r=run_sequence('assert (300*psi == 1*V) is False',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_quantity_rejects_numeric_string(self):
        r=run_sequence('values = ["3"]\np = Pressure(values[0])',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'fail',r['diagnostics'])

    def test_flight_first_line_and_unicode_limitations_are_visible(self):
        for source in ['if True:\n    valve.open()', '# café\nvalve.open()']:
            r=run_sequence(source,MAPPING,False)
            self.assertTrue(any(d['stage']=='api' and d['severity']=='error' for d in r['diagnostics']),r)

    def test_quantity_ieee_and_numeric_conversion(self):
        r=run_sequence('assert Pressure(True) == 1*psi\nassert (1*psi / 0) > 300*psi\nassert Pressure(-0.0) < Pressure(0.0)',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_unexpected_device_attribute_is_rejected(self):
        r=run_sequence('x = valve.name',MAPPING,True)
        self.assertEqual(r['checks']['api'],'fail',r['diagnostics'])

if __name__=='__main__': unittest.main()

class AdditionalAuditRegressions(unittest.TestCase):
    def test_unknown_constructors_do_not_read_mapping(self):
        r=run_sequence('unused = Sensor("missing")\nunused_valve = Valve("missing")',MAPPING,True)
        self.assertNotEqual(r['checks']['api'],'fail',r['diagnostics'])
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_unit_inplace_mutates_alias_like_pyo3(self):
        r=run_sequence('a = 2*psi\nb = a\na += 1*psi\nassert b == 3*psi',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_unreachable_invalid_call_is_partial(self):
        r=run_sequence('# unreachable branch fixture\nif False:\n    valve.open(True)',MAPPING,True)
        self.assertEqual(r['checks']['api'],'partial',r['diagnostics'])
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

    def test_omitted_timeout_exposes_upstream_panic_limit(self):
        r=run_sequence('wait_until(lambda: True)',MAPPING,True)
        self.assertEqual(r['checks']['api'],'fail',r['diagnostics'])

class CompiledEnumAndIdentity(unittest.TestCase):
    def test_valve_identity_and_enum_values(self):
        r=run_sequence('assert valve != Valve("valve")\nassert OPEN == 2\nassert int(CLOSED) == 3\nassert OPEN != "OPEN"',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

class EnumExtractionDetails(unittest.TestCase):
    def test_enum_is_unhashable(self):
        r=run_sequence('hash(OPEN)',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'fail',r['diagnostics'])

class QuantityTypes(unittest.TestCase):
    def test_exported_unit_constructors_are_real_classes(self):
        r=run_sequence('assert isinstance(FTPT.read(), Pressure)\nassert type(1*psi) is Pressure\nassert type(1*ms) is Duration\nassert type(1*psi + 2*psi) is Pressure\nassert not isinstance(1*psi, Duration)',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'pass',r['diagnostics'])

class OpaqueApiAccess(unittest.TestCase):
    def test_quantity_has_no_raw_or_kind_attribute(self):
        for field in ['raw','kind']:
            r=run_sequence('p = 1*psi\nprint(getattr(p, "'+field+'"))',MAPPING,True)
            self.assertTrue(r['checks']['api']=='fail' or r['checks']['runtime']=='fail',r['diagnostics'])

    def test_opaque_constructor_cannot_instantiate_valve_safe_state(self):
        r=run_sequence('classes = [ValveSafeState]\nclasses[0]()',MAPPING,True)
        self.assertEqual(r['checks']['runtime'],'fail',r['diagnostics'])

    def test_unknown_call_target_is_partial(self):
        r=run_sequence('actions = [valve.open]\nactions[0]()',MAPPING,True)
        self.assertEqual(r['checks']['api'],'partial',r['diagnostics'])

class HistoricalNotionFailures(unittest.TestCase):
    def test_invalid_historical_calls_are_rejected(self):
        for source in ['time.time()', 'stop()', 'valve.actuate(true)', 'set_servo_disconnect_monitoring(False)', 'create_abort_stage("a", "False", {valve: (CLOSED, 5*s)})']:
            with self.subTest(source=source):
                result=run_sequence(source,MAPPING,True)
                self.assertTrue(any(d['severity']=='error' for d in result['diagnostics']),result)

    def test_original_launch_v1_is_not_silently_repaired(self):
        source=(Path(__file__).parent/'fixtures/luna/vespula-launch-v1.py').read_text()
        result=run_sequence(source,MAPPING,False)
        self.assertEqual(result['checks']['syntax'],'fail')
        self.assertEqual(result['diagnostics'][0]['line'],91)

    def test_python_keyword_mapping_is_invalid(self):
        result=run_sequence('pass',{'valves':['class'],'sensors':[]},False)
        self.assertTrue(any(d['severity']=='error' and 'Invalid valve name' in d['message'] for d in result['diagnostics']))
