import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engine import run_sequence


MAPPING = {
    "valves": ["press_valve", "vent_valve"],
    "sensors": [{
        "name": "tank_pt", "unit": "psi",
        "samples": [{"at": 0, "value": 0}, {"at": 2, "value": 310}],
    }],
}


class EngineTests(unittest.TestCase):
    def check(self, source, execute=False, mapping=MAPPING):
        return run_sequence(source, json.dumps(mapping), execute)

    def test_syntax_error(self):
        result = self.check("if True\n    pass")
        self.assertEqual(result["checks"]["syntax"], "fail")
        self.assertEqual(result["diagnostics"][0]["line"], 1)

    def test_missing_time_import(self):
        result = self.check("time.sleep(1)")
        self.assertEqual(result["checks"]["names"], "fail")
        self.assertIn("time", result["diagnostics"][0]["message"])

    def test_missing_time_import_nested(self):
        result = self.check("def fire():\n    time.sleep(1)\nfire()")
        self.assertEqual(result["checks"]["names"], "fail")

    def test_import_time_is_valid(self):
        result = self.check("import time\ntime.sleep(2)", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["virtual_time"], 2)

    def test_unbound_old_sequence_variables(self):
        result = self.check("wait_for(ignitor_wait_time)\nprint(omv_open_time, ran)")
        self.assertEqual(result["checks"]["names"], "fail")
        messages = " ".join(d["message"] for d in result["diagnostics"])
        for name in ("ignitor_wait_time", "omv_open_time", "ran"):
            self.assertIn(name, messages)

    def test_unknown_luna_function(self):
        result = self.check("stop()")
        self.assertEqual(result["checks"]["names"], "fail")

    def test_sensor_method_error(self):
        result = self.check("tank_pt.open()")
        self.assertEqual(result["checks"]["api"], "fail")

    def test_valve_method_error(self):
        result = self.check("press_valve.read()")
        self.assertEqual(result["checks"]["api"], "fail")

    def test_unknown_sensor_mapping(self):
        result = self.check("x = Sensor('missing')\nx.read()")
        self.assertEqual(result["checks"]["api"], "fail")

    def test_mapping_constructor_type(self):
        result = self.check("x = Sensor('tank_pt')\nx.open()")
        self.assertEqual(result["checks"]["api"], "fail")

    def test_luna_prelude_names(self):
        result = self.check("from common import *\npress_valve.open()\nwait_for(2 * ms)\npress_valve.close()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["events"][1]["time"], 0.002)

    def test_tank_press_trace(self):
        source = "press_valve.open()\nwait_until(lambda: tank_pt.read() >= 300*psi, 5*s)\npress_valve.close()"
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertAlmostEqual(result["events"][-1]["time"], 2)
        self.assertEqual(result["valves"]["press_valve"], "CLOSED")

    def test_wait_until_timeout_preserves_luna_semantics(self):
        result = self.check("wait_until(lambda: tank_pt.read() > 500*psi, 1*s)", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertTrue(any(event["kind"] == "timeout" for event in result["events"]))

    def test_wait_until_rejects_invalid_timeout(self):
        result = self.check("wait_until(lambda: False, 1)", True)
        self.assertEqual(result["checks"]["runtime"], "fail")

    def test_abort_stage_configuration(self):
        result = self.check("create_abort_stage('safe', 'manual', {press_valve: (CLOSED, 5)})", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["events"][0]["target"], "create_abort_stage")

    def test_runtime_exception_line(self):
        result = self.check("wait_for(1 * s)\nprint(1/0)", True)
        self.assertEqual(result["checks"]["runtime"], "fail")
        self.assertEqual(result["diagnostics"][-1]["line"], 2)

    def test_unit_type_error(self):
        result = self.check("wait_for(4)", True)
        self.assertEqual(result["checks"]["runtime"], "fail")

    def test_interval(self):
        result = self.check("for i in interval(3, 2*s):\n    print(i)", True)
        self.assertEqual(result["virtual_time"], 4)
        self.assertEqual(result["stdout"], "0\n1\n2\n")

    def test_abort_event_does_not_stop_script(self):
        result = self.check("abort()\npress_valve.close()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["events"][0]["target"], "abort")
        self.assertEqual(result["events"][1]["kind"], "valve")

    def test_invalid_mapping(self):
        result = self.check("press_valve.open()", True, mapping={"valves": ["press_valve"], "sensors": [{"name": "press_valve"}]})
        self.assertEqual(result["checks"]["api"], "fail")

    def test_unsupported_import_is_not_a_luna_error(self):
        result = self.check("import os\nprint('hello')")
        self.assertEqual(result["checks"]["names"], "pass")
        self.assertTrue(any(item["severity"] == "warning" for item in result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
