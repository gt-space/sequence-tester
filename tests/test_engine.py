import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engine import Simulator, run_sequence, simulation_integrity_errors


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
        result = self.check("x = Sensor('missing')\nx.read()", True)
        self.assertEqual(result["checks"]["api"], "partial")
        self.assertEqual(result["checks"]["runtime"], "fail")

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

    def test_static_luna_signature_validation(self):
        cases = [
            ("press_valve.actuate('CLOSED')", "expects bool"),
            ("press_valve.get_name()", "does not expose"),
            ("tank_pt.read(1)", "at most 0"),
            ("press_valve.open(True)", "at most 0"),
            ("wait_for()", "missing required"),
            ("interval(2.5, 10 * ms)", "expects i64"),
            ("launch_lug_arm('sam-21', 'True')", "expects bool"),
            ("sam_camera_toggle(1)", "expects bool"),
            ("wait_until(True, timeout=5*s)", "expects &PyAny"),
            ("press_valve.actuate(enabled=1)", "no parameter 'enabled'"),
            ("print(1*psi + 2*V)", "cannot combine"),
            ("import common\ncommon.missing_command()", "does not export"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                result = self.check(source, True)
                self.assertEqual(result["checks"]["api"], "fail", result["diagnostics"])
                self.assertTrue(any(message.lower() in item["message"].lower() for item in result["diagnostics"]),
                                result["diagnostics"])

    def test_valid_luna_api_calls_and_runtime_bool_guard(self):
        source = ("from common import Valve as ValveAlias\n"
                  "v = ValveAlias('press_valve')\n"
                  "v.actuate(True)\n"
                  "launch_lug_arm('sam-21', False)\n"
                  "wait_until(lambda: v.is_open(), timeout=5*s)\n"
                  "sam_camera_toggle(True)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        result = self.check("opening = 'CLOSED'\npress_valve.actuate(opening)", True)
        # Static inference catches simple aliasing; opaque dynamic values are rejected at runtime.
        self.assertEqual(result["checks"]["api"], "fail")
        result = self.check("def opening(): return 'CLOSED'\npress_valve.actuate(opening())", True)
        self.assertEqual(result["checks"]["runtime"], "fail")

    def test_integrity_checks_valve_event_accounting(self):
        sim = Simulator({"press_valve": "CLOSED"}, {})
        sim.total_valve_commands = 2
        sim.repeated_valve_commands = 1
        result = {"events": [], "valves": {"press_valve": "CLOSED"},
                  "simulation": {"sensors": {}}}
        self.assertTrue(any("accounting" in problem for problem in simulation_integrity_errors(sim, result)))

    def test_integrity_checks_final_state_and_event_order(self):
        sim = Simulator({"press_valve": "CLOSED"}, {})
        sim.total_valve_commands = 1
        result = {"events": [{"kind": "valve", "target": "press_valve", "detail": "OPEN", "time": 0}],
                  "valves": {"press_valve": "CLOSED"}, "simulation": {"sensors": {}}}
        self.assertTrue(any("Final valve states" in problem for problem in simulation_integrity_errors(sim, result)))
        result["valves"]["press_valve"] = "OPEN"
        result["events"].append({"kind": "command", "target": "x", "detail": "", "time": -1})
        self.assertTrue(any("timestamps" in problem for problem in simulation_integrity_errors(sim, result)))

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
                  "wait_until(condition=lambda: tank_pt.read() >= 300*psi, timeout=5*s, poll_interval=20*ms)\n"
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
        source = ("create_abort_stage('press', 'tank_pt.read() > 450*psi', {press_valve: (CLOSED, 500)})\n"
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
        source = ("create_abort_stage('press', 'tank_pt.read() > 450*psi', {press_valve: (CLOSED, 500)})\n"
                  "set_abort_stage('press')\nwait_for(5*s)")
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass")
        self.assertTrue(any("ABORT CONDITION NEVER TRIGGERED" in d["message"]
                            for d in result["diagnostics"]))
        self.assertIsNone(result["simulation"]["abort_stages"][0]["triggered"])

    def test_stage_switch_and_multiple_safing_delays(self):
        source = ("create_abort_stage('early', 'tank_pt.read() > 500*psi', {})\n"
                  "create_abort_stage('late', 'tank_pt.read() > 300*psi', "
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

    def test_valve_driven_sensor_triggers_abort_with_continuous_clock(self):
        source = ("create_abort_stage('rising', 'CTPT.read() > 210*psi', "
                  "{CISO: (CLOSED, 200)})\n"
                  "set_abort_stage('rising')\n"
                  "CISO.open()\n"
                  "wait_for(1*s)\n"
                  "print('should not run')")
        result = self.check(source, True, mapping=DRIVEN,
                            options={"clock_mode": "realtime", "speed": 5, "max_duration": 3})
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        abort = next(event for event in result["events"] if event["kind"] == "abort")
        safe = next(event for event in result["events"] if event["kind"] == "abort_safe")
        self.assertGreater(abort["time"], 0.25)
        self.assertLess(abort["time"], 0.45)
        self.assertAlmostEqual(safe["time"] - abort["time"], 0.2, places=2)
        self.assertEqual(result["valves"]["CISO"], "CLOSED")
        self.assertEqual(result["stdout"], "")
        self.assertEqual(result["timing"]["mode"], "realtime")

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
        source = ("create_abort_stage('safe', 'tank_pt.read() > 400*psi', {})\n"
                  "set_abort_stage('safe')\nwait_for(1*s)")
        result = self.check(source, True)
        self.assertEqual(result["simulation"]["sensor_read_lines"]["tank_pt"], [1])
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


    def test_direct_sensor_comparisons_match_luna_richcmp(self):
        # Luna currently evaluates threshold.compare(reading, op) in Sensor.__richcmp__.
        source = (
            "assert tank_pt > 300*psi\n"
            "assert tank_pt >= 300*psi\n"
            "assert not (tank_pt < 300*psi)\n"
            "assert not (tank_pt <= 300*psi)\n"
            "assert tank_pt == 0*psi\n"
            "assert not (tank_pt != 0*psi)\n"
            "assert tank_pt.read() < 300*psi\n"
        )
        result = self.check(source, True)
        self.assertEqual(result["checks"]["runtime"], "pass", result["diagnostics"])
        self.assertTrue(any("reverses direct Sensor" in d["message"] for d in result["diagnostics"]))

    def test_bound_method_alias_enforces_luna_signature(self):
        result = self.check("action = press_valve.open\naction(1)")
        self.assertEqual(result["checks"]["api"], "fail", result["diagnostics"])
        self.assertTrue(any("takes at most 0" in d["message"] for d in result["diagnostics"]))
        valid = self.check("action = press_valve.open\naction()", True)
        self.assertEqual(valid["checks"]["api"], "pass", valid["diagnostics"])
        self.assertEqual(valid["checks"]["runtime"], "pass", valid["diagnostics"])

    def test_luna_function_alias_enforces_arguments(self):
        bad = self.check("pause = wait_for\npause(1)")
        self.assertEqual(bad["checks"]["api"], "fail", bad["diagnostics"])
        good = self.check("pause = wait_for\npause(10*ms)", True)
        self.assertEqual(good["checks"]["runtime"], "pass", good["diagnostics"])

    def test_getattr_literal_is_checked_and_dynamic_is_partial(self):
        invalid = self.check("action = getattr(press_valve, 'get_name')\naction()")
        self.assertEqual(invalid["checks"]["api"], "fail", invalid["diagnostics"])
        literal = self.check("action = getattr(press_valve, 'open')\naction(1)")
        self.assertEqual(literal["checks"]["api"], "fail", literal["diagnostics"])
        dynamic = self.check("name = 'open'\naction = getattr(press_valve, name)\naction()", True)
        self.assertEqual(dynamic["checks"]["api"], "partial", dynamic["diagnostics"])
        self.assertEqual(dynamic["checks"]["runtime"], "pass", dynamic["diagnostics"])


if __name__ == "__main__":
    unittest.main()
