import json
import sys
import time
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

DRIVEN = {
    "valves": ["CISO", "CMV"],
    "sensors": [{
        "name": "CTPT", "unit": "psi", "mode": "valve", "initial": 200,
        "valves": ["CISO", "CMV"],
        "rates": {"00": 0, "01": -25, "10": 40, "11": 0},
        "min": 0, "max": 500,
    }],
}


class EngineTests(unittest.TestCase):
    def check(self, source, execute=False, mapping=MAPPING, options=None):
        return run_sequence(source, json.dumps(mapping), execute, options)

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
        self.assertEqual([event["line"] for event in result["events"]], [2, 4])

    def test_event_source_location_in_loop(self):
        result = self.check("for i in range(2):\n    press_valve.open()\n    wait_for(1*s)\n    press_valve.close()", True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertEqual([event["line"] for event in result["events"]], [2, 4, 2, 4])

    def test_repeated_valve_commands_do_not_truncate_later_transitions(self):
        source = ("press_valve.open()\n"
                  "for _ in range(500):\n"
                  "    press_valve.open()\n"
                  "    wait_for(500*ms)\n"
                  "press_valve.close()")
        result = self.check(source, True, options={"max_duration": 300})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual([(event["target"], event["detail"], event["time"])
                          for event in result["events"]],
                         [("press_valve", "OPEN", 0), ("press_valve", "CLOSED", 250)])
        self.assertTrue(any("Collapsed 500 repeated valve commands" in item["message"]
                            for item in result["diagnostics"]))

    def test_more_than_300_real_transitions_are_preserved(self):
        source = ("for i in range(350):\n"
                  "    press_valve.actuate(i % 2 == 0)\n"
                  "    wait_for(1*ms)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual(len(result["events"]), 350)
        self.assertAlmostEqual(result["events"][-1]["time"], 0.349)
        self.assertEqual(result["valves"]["press_valve"], "CLOSED")

    def test_excessive_distinct_events_fail_instead_of_silently_truncating(self):
        source = ("for i in range(10001):\n"
                  "    press_valve.actuate(i % 2 == 0)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "fail")
        self.assertEqual(len(result["events"]), 10000)
        self.assertTrue(any("More than 10,000 distinct simulation events" in item["message"]
                            for item in result["diagnostics"]))

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
        self.assertTrue(any(item["severity"] == "warning" and "wait_until() timed out" in item["message"]
                            for item in result["diagnostics"]))

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

    def test_valve_driven_sensor_follows_all_four_states(self):
        source = """assert CTPT.read() == 200*psi
CISO.open()
wait_for(2*s)
assert CTPT.read() == 280*psi
CMV.open()
wait_for(1*s)
assert CTPT.read() == 280*psi
CISO.close()
wait_for(2*s)
assert CTPT.read() == 230*psi
CMV.close()
wait_for(1*s)
assert CTPT.read() == 230*psi"""
        result = self.check(source, True, mapping=DRIVEN)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual(result["simulation"]["sensors"]["CTPT"]["samples"], [
            {"at": 0, "value": 200}, {"at": 2.0, "value": 280},
            {"at": 3.0, "value": 280}, {"at": 5.0, "value": 230},
            {"at": 6.0, "value": 230},
        ])

    def test_valve_driven_pressure_control_loop(self):
        source = """CISO.open()
while CTPT.read() < 340*psi:
    wait_for(100*ms)
CISO.close()
assert CTPT.read() >= 340*psi
assert CTPT.read() < 345*psi"""
        result = self.check(source, True, mapping=DRIVEN)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertLess(result["virtual_time"], 4)
        self.assertEqual(result["valves"]["CISO"], "CLOSED")

    def test_incomplete_truth_table_rejected_in_validation(self):
        for bad in ({"00": 0, "01": -25, "10": 40}, {"00": 0, "01": -25, "10": 40, "11": ""}):
            mapping = {**DRIVEN, "sensors": [{**DRIVEN["sensors"][0], "rates": bad}]}
            result = self.check("print(CTPT.read())", True, mapping=mapping)
            self.assertEqual(result["checks"]["api"], "fail")

    def test_valve_driven_rejects_unknown_or_duplicate_valves(self):
        for valves in (["CISO", "missing"], ["CISO", "CISO"]):
            mapping = {**DRIVEN, "sensors": [{**DRIVEN["sensors"][0], "valves": valves}]}
            result = self.check("print(CTPT.read())", mapping=mapping)
            self.assertEqual(result["checks"]["api"], "fail")

    def test_valve_driven_rejects_invalid_bounds_and_rate(self):
        originals = DRIVEN["sensors"][0]
        for changes in ({"min": 300}, {"min": 600, "max": 500}, {"rates": {**originals["rates"], "11": float("nan")}}):
            mapping = {**DRIVEN, "sensors": [{**originals, **changes}]}
            result = self.check("print(CTPT.read())", mapping=mapping)
            self.assertEqual(result["checks"]["api"], "fail")

    def test_valve_driven_clamps_at_bound_without_inaccurate_plot(self):
        mapping = {**DRIVEN, "sensors": [{**DRIVEN["sensors"][0], "max": 250}]}
        result = self.check("CISO.open()\nwait_for(5*s)\nassert CTPT.read() == 250*psi", True, mapping=mapping)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual(result["simulation"]["sensors"]["CTPT"]["samples"], [
            {"at": 0, "value": 200}, {"at": 1.25, "value": 250}, {"at": 5.0, "value": 250},
        ])

    def test_continuous_clock_advances_without_explicit_wait(self):
        source = """CISO.open()
while CTPT.read() < 210*psi:
    pass
CISO.close()
print('done')"""
        start = time.perf_counter()
        result = self.check(source, True, mapping=DRIVEN,
                            options={"clock_mode": "realtime", "speed": 5, "max_duration": 5})
        elapsed = time.perf_counter() - start
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertGreaterEqual(result["virtual_time"], 0.25)
        self.assertLess(result["virtual_time"], 0.7)
        self.assertGreaterEqual(elapsed, 0.045)
        self.assertEqual(result["valves"]["CISO"], "CLOSED")
        self.assertEqual(result["stdout"], "done\n")
        self.assertEqual(result["timing"]["requested_speed"], 5)

    def test_continuous_wait_and_wall_elapsed_time(self):
        source = """import time
start = time.time()
monotonic_start = time.monotonic()
time.sleep(0.2)
assert 0.19 <= time.time() - start <= 0.5
assert 0.19 <= time.monotonic() - monotonic_start <= 0.5
assert time.perf_counter() >= monotonic_start"""
        result = self.check(source, True, options={"clock_mode": "realtime", "speed": 5, "max_duration": 5})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertGreaterEqual(result["timing"]["wait_count"], 1)
        self.assertGreaterEqual(result["virtual_time"], 0.2)

    def test_continuous_pressure_loop_switches_from_fill_to_vent(self):
        source = """CISO.open()
while CTPT.read() < 220*psi:
    pass
CISO.close()
CMV.open()
while CTPT.read() > 210*psi:
    pass
CMV.close()"""
        result = self.check(source, True, mapping=DRIVEN,
                            options={"clock_mode": "realtime", "speed": 5, "max_duration": 5})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual([event["detail"] for event in result["events"]],
                         ["OPEN", "CLOSED", "OPEN", "CLOSED"])
        self.assertAlmostEqual(result["virtual_time"], 0.9, delta=0.3)
        sensor_samples = result["simulation"]["sensors"]["CTPT"]["samples"]
        self.assertGreaterEqual(max(sample["value"] for sample in sensor_samples), 220)
        self.assertLessEqual(sensor_samples[-1]["value"], 210)

    def test_continuous_wait_until_timeout_preserves_luna_semantics(self):
        result = self.check("wait_until(lambda: tank_pt.read() > 500*psi, 200*ms)", True,
                            options={"clock_mode": "realtime", "speed": 5, "max_duration": 2})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertTrue(any(event["kind"] == "timeout" for event in result["events"]))
        self.assertGreaterEqual(result["virtual_time"], 0.2)

    def test_deterministic_mode_remains_instant_and_repeatable(self):
        result = self.check("import time\ntime.sleep(20)\nprint(time.monotonic())", True,
                            options={"clock_mode": "deterministic", "speed": 5, "max_duration": 40})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertEqual(result["virtual_time"], 20)
        self.assertEqual(result["stdout"], "20.0\n")
        self.assertEqual(result["timing"]["mode"], "deterministic")

    def test_continuous_stalled_condition_reports_sensor_state(self):
        source = """CISO.open()
while CTPT.read() < 300*psi:
    pass"""
        result = self.check(source, True, mapping=DRIVEN,
                            options={"clock_mode": "realtime", "speed": 5, "max_duration": 1})
        self.assertEqual(result["checks"]["runtime"], "fail")
        self.assertIn("SimulationLimit", result["diagnostics"][-1]["message"])
        self.assertIn("last CTPT=", result["diagnostics"][-1]["message"])
        self.assertIn("CISO=OPEN", result["diagnostics"][-1]["message"])

    def test_invalid_clock_options_are_diagnosed(self):
        for options in ({"clock_mode": "unknown"}, {"speed": 0}, {"speed": 10},
                        {"speed": 20}, {"speed": True}, {"max_duration": 0}):
            result = self.check("print('hello')", True, options=options)
            self.assertEqual(result["checks"]["runtime"], "fail")
            self.assertIn("Invalid simulation settings", result["diagnostics"][-1]["message"])

    def test_one_x_simulation_speed_is_supported(self):
        result = self.check("wait_for(20*ms)", True,
                            options={"clock_mode": "realtime", "speed": 1, "max_duration": 2})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertGreaterEqual(result["virtual_time"], 0.02)
        self.assertEqual(result["timing"]["requested_speed"], 1)


if __name__ == "__main__":
    unittest.main()
