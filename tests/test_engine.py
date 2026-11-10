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

    def test_unknown_public_luna_exports(self):
        for source in (
            "import common\ncommon.nonexistent_function()",
            "import common as luna\nluna.fake_valve_api()",
            "from common import nonexistent_function",
            "from common import nonexistent_function as something_else",
            "from common import OPEN",  # OPEN is injected by flight2, not exported by common.
            "import common\ncommon.CLOSED",
        ):
            with self.subTest(source=source):
                result = self.check(source)
                self.assertEqual(result["checks"]["api"], "fail", result["diagnostics"])

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
        self.assertEqual([event["line"] for event in result["events"]], [2, 4])

    def test_event_source_location_in_loop(self):
        result = self.check("for i in range(2):\n    press_valve.open()\n    wait_for(1*s)\n    press_valve.close()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual([event["line"] for event in result["events"]], [2, 4, 2, 4])

    def test_sensor_source_lines_and_profiles(self):
        result = self.check("wait_for(1*s)\nx = tank_pt.read()\ny = tank_pt.read()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["simulation"]["sensor_read_lines"]["tank_pt"], [2, 3])
        self.assertEqual(result["simulation"]["sensors"]["tank_pt"]["samples"][1]["value"], 310)

    def test_initial_state_is_in_simulation_payload(self):
        mapping = {**MAPPING, "valves": [{"name": "press_valve", "initial": "OPEN"}]}
        result = self.check("print(press_valve.is_open())", True, mapping=mapping)
        self.assertEqual(result["simulation"]["initial_valves"]["press_valve"], "OPEN")

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
        self.assertEqual(result["checks"]["api"], "fail")
        self.assertEqual(result["checks"]["runtime"], "not_run")

    def test_abort_stage_configuration(self):
        result = self.check("create_abort_stage('safe', 'False', {press_valve: (CLOSED, 5)})", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["events"][0]["kind"], "abort_config")

    def test_runtime_exception_line(self):
        result = self.check("wait_for(1 * s)\nprint(1/0)", True)
        self.assertEqual(result["checks"]["runtime"], "fail")
        self.assertEqual(result["diagnostics"][-1]["line"], 2)

    def test_unit_type_error(self):
        result = self.check("wait_for(4)", True)
        self.assertEqual(result["checks"]["api"], "fail")
        self.assertEqual(result["checks"]["runtime"], "not_run")

    def test_interval(self):
        result = self.check("for i in interval(3, 2*s):\n    print(i)", True)
        self.assertEqual(result["virtual_time"], 4)
        self.assertEqual(result["stdout"], "0\n1\n2\n")

    def test_abort_terminates_operator_sequence(self):
        result = self.check("abort()\npress_valve.close()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["events"][0]["kind"], "abort")
        self.assertFalse(any(event["kind"] == "valve" for event in result["events"]))

    def test_invalid_mapping(self):
        result = self.check("press_valve.open()", True, mapping={"valves": ["press_valve"], "sensors": [{"name": "press_valve"}]})
        self.assertEqual(result["checks"]["api"], "fail")

    def test_initial_open_valve_state(self):
        mapping = {**MAPPING, "valves": [{"name": "press_valve", "initial": "OPEN"}, {"name": "vent_valve", "initial": "CLOSED"}]}
        result = self.check("assert press_valve.is_open()\nassert vent_valve.is_closed()", True, mapping=mapping)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual(result["valves"]["press_valve"], "OPEN")

    def test_invalid_initial_valve_state(self):
        mapping = {**MAPPING, "valves": [{"name": "press_valve", "initial": "UNKNOWN"}]}
        result = self.check("press_valve.open()", True, mapping=mapping)
        self.assertEqual(result["checks"]["api"], "fail")

    def test_linear_sensor_profile(self):
        mapping = {**MAPPING, "sensors": [{"name": "tank_pt", "unit": "psi", "interpolation": "linear", "samples": [{"at": 0, "value": 0}, {"at": 2, "value": 300}]}]}
        result = self.check("wait_for(1*s)\nassert tank_pt.read() == 150*psi", True, mapping=mapping)
        self.assertEqual(result["checks"]["runtime"], "pass")

    def test_step_sensor_profile_remains_default(self):
        result = self.check("wait_for(1*s)\nassert tank_pt.read() == 0*psi", True)
        self.assertEqual(result["checks"]["runtime"], "pass")

    def test_unsupported_import_is_not_a_luna_error(self):
        result = self.check("import os\nprint('hello')")
        self.assertEqual(result["checks"]["names"], "pass")
        self.assertTrue(any(item["severity"] == "warning" for item in result["diagnostics"]))

    def test_strict_luna_api_methods_and_types(self):
        for source in (
            "press_valve.get_name()",  # Rust-only helper, not PyO3-exposed
            "press_valve.actuate('OPEN')",
            "press_valve.open(True)",
            "tank_pt.read(1)",
            "wait_for()",
            "wait_for(500)",
            "wait_until(True, 5*s)",
            "interval(2.5, 10*ms)",
            "launch_lug_arm('sam-21', 'True')",
            "sam_camera_toggle(1)",
            "wait_until(lambda: True, invalid_keyword=1)",
        ):
            with self.subTest(source=source):
                result = self.check(source)
                self.assertEqual(result["checks"]["api"], "fail", result["diagnostics"])

    def test_valid_luna_api_signatures(self):
        source = ("press_valve.actuate(True)\n"
                  "wait_until(condition=lambda: tank_pt >= 300*psi, timeout=5*s, poll_interval=20*ms)\n"
                  "launch_lug_arm('sam-21', False)\n"
                  "sam_camera_toggle(True)\n"
                  "set_servo_disconnect_abort(True)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["api"], "pass", result["diagnostics"])
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])

    def test_units_are_checked_statically(self):
        for source in (
            "wait_for(1*psi)",
            "if tank_pt > 450*ms: pass",
            "x = 400*psi + 100*ms",
            "x = tank_pt.read().raw",  # Not exposed by the real PyO3 binding
        ):
            with self.subTest(source=source):
                self.assertEqual(self.check(source)["checks"]["api"], "fail")

    def test_runtime_valve_bool_type_guard(self):
        # Dynamic arguments have to be checked at runtime.
        result = self.check("value = 'OPEN'\npress_valve.actuate(value)", True)
        self.assertEqual(result["checks"]["api"], "fail")

    def test_abort_condition_does_not_see_parent_locals(self):
        source = "limit = 400*psi\ncreate_abort_stage('safe', 'tank_pt > limit', {})"
        result = self.check(source)
        self.assertEqual(result["checks"]["api"], "fail")
        self.assertIn("separate abort process", str(result["diagnostics"]))

    def test_abort_condition_invalid_syntax_and_mappings(self):
        for condition in ("tank_pt >", "unmapped_pt > 50*psi", "tank_pt.open()"):
            with self.subTest(condition=condition):
                source = f"create_abort_stage('safe', {condition!r}, {{}})"
                self.assertEqual(self.check(source)["checks"]["api"], "fail")

    def test_abort_safing_timer_is_unsigned_integer_milliseconds(self):
        for timer in ("500*ms", "-1", "4294967296"):
            with self.subTest(timer=timer):
                source = f"create_abort_stage('safe', 'False', {{press_valve: (CLOSED, {timer})}})"
                self.assertEqual(self.check(source)["checks"]["api"], "fail")

    def test_abort_condition_triggers_with_safe_state_delay(self):
        mapping = {"valves": ["press_valve"], "sensors": [{
            "name": "tank_pt", "unit": "psi", "interpolation": "linear",
            "samples": [{"at": 0, "value": 400}, {"at": 2, "value": 500}],
        }]}
        source = ("create_abort_stage('press', 'tank_pt > 450*psi', {press_valve: (CLOSED, 500)})\n"
                  "set_abort_stage('press')\npress_valve.open()\nwait_for(4*s)\npress_valve.open()")
        result = self.check(source, True, mapping)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        abort = next(event for event in result["events"] if event["kind"] == "abort")
        self.assertAlmostEqual(abort["time"], 1.01)
        self.assertEqual(abort["line"], 1)
        safe = next(event for event in result["events"] if event["kind"] == "abort_safe")
        self.assertAlmostEqual(safe["time"], 1.51)
        self.assertEqual(safe["line"], 1)
        self.assertEqual(result["valves"]["press_valve"], "CLOSED")
        self.assertFalse(any(event["kind"] == "valve" and event["line"] == 5 for event in result["events"]))
        stage = result["simulation"]["abort_stages"][0]
        self.assertEqual(stage["triggered"], abort["time"])

    def test_abort_condition_not_exercised_warning(self):
        source = ("create_abort_stage('press', 'tank_pt > 450*psi', {press_valve: (CLOSED, 500)})\n"
                  "set_abort_stage('press')\nwait_for(5*s)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertTrue(any("ABORT CONDITION NEVER TRIGGERED" in d["message"]
                            for d in result["diagnostics"]))
        self.assertIsNone(result["simulation"]["abort_stages"][0]["triggered"])

    def test_stage_switch_and_multiple_safing_delays(self):
        source = ("create_abort_stage('early', 'tank_pt > 500*psi', {})\n"
                  "create_abort_stage('late', 'tank_pt > 300*psi', "
                  "{press_valve: (CLOSED, 0), vent_valve: (OPEN, 1000)})\n"
                  "set_abort_stage('early')\nwait_for(1*s)\n"
                  "set_abort_stage('late')\npress_valve.open()\nwait_for(3*s)\n"
                  "print('never reached')")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        stages = {stage["name"]: stage for stage in result["simulation"]["abort_stages"]}
        self.assertIsNone(stages["early"]["triggered"])
        self.assertAlmostEqual(stages["late"]["triggered"], 2.0)
        self.assertEqual([event["target"] for event in result["events"] if event["kind"] == "abort_stage"],
                         ["early", "late"])
        safes = [event for event in result["events"] if event["kind"] == "abort_safe"]
        self.assertEqual([(event["target"], event["time"]) for event in safes],
                         [("press_valve", 2.0), ("vent_valve", 3.0)])
        self.assertEqual(result["valves"], {"press_valve": "CLOSED", "vent_valve": "OPEN"})
        self.assertEqual(result["stdout"], "")
        self.assertTrue(any("ABORT CONDITION NEVER TRIGGERED: 'early'" in d["message"]
                            for d in result["diagnostics"]))

    def test_abort_stage_defined_but_not_activated_warning(self):
        result = self.check("create_abort_stage('safe', 'True', {})\nwait_for(1*s)", True)
        self.assertTrue(any("ABORT STAGE NOT ACTIVATED" in d["message"]
                            for d in result["diagnostics"]))
        self.assertFalse(any(event["kind"] == "abort" for event in result["events"]))

    def test_undefined_abort_stage_rejected(self):
        result = self.check("set_abort_stage('missing')", True)
        self.assertEqual(result["checks"]["runtime"], "fail")
        self.assertIn("Unknown abort stage", result["diagnostics"][-1]["message"])

    def test_abort_condition_sensor_reads_link_back_to_definition(self):
        source = ("create_abort_stage('safe', 'tank_pt > 400*psi', {})\n"
                  "set_abort_stage('safe')\nwait_for(1*s)")
        result = self.check(source, True)
        self.assertEqual(result["simulation"]["sensor_read_lines"]["tank_pt"], [1])


if __name__ == "__main__":
    unittest.main()
