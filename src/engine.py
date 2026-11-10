import ast
import builtins
import contextlib
import io
import json
import math
import sys
import symtable
import time as host_time
import traceback
import types

from luna_contract import API, FUNCTIONS, METHODS, UNIT_CONSTANTS, UNIT_CLASSES, VALVE_STATES
from luna_validation import analyze_luna_api, validate_abort_expression

IMPORTS = {"common", "time", "math"}
UNITS = {"unknown", "psi", "V", "A", "lbf", "K"}


def diagnostic(stage, severity, message, line=0, column=0):
    return dict(stage=stage, severity=severity, message=message, line=line, column=column)


def check_mapping(raw):
    problems = []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object")
        valves = data.get("valves", [])
        sensors = data.get("sensors", [])
        if not isinstance(valves, list) or not isinstance(sensors, list):
            raise ValueError("valves and sensors must be arrays")
        valve_names = {}
        sensor_data = {}
        for valve in valves:
            if isinstance(valve, str):
                name, initial = valve, "CLOSED"
            elif isinstance(valve, dict):
                name, initial = valve.get("name"), valve.get("initial", "CLOSED")
            else:
                raise ValueError(f"Invalid valve definition: {valve!r}")
            if not isinstance(name, str) or not name.isidentifier():
                raise ValueError(f"Invalid valve name: {name!r}")
            if name in valve_names or name in API:
                raise ValueError(f"Duplicate or reserved valve name: {name}")
            if initial not in {"OPEN", "CLOSED"}:
                raise ValueError(f"Invalid initial state for {name}: {initial!r}")
            valve_names[name] = initial
        for sensor in sensors:
            if not isinstance(sensor, dict):
                raise ValueError("Each sensor must be an object")
            name = sensor.get("name")
            unit = sensor.get("unit", "unknown")
            if not isinstance(name, str) or not name.isidentifier():
                raise ValueError(f"Invalid sensor name: {name!r}")
            if name in sensor_data or name in valve_names or name in API:
                raise ValueError(f"Duplicate or reserved sensor name: {name}")
            if unit not in UNITS:
                raise ValueError(f"Unsupported unit for {name}: {unit}")
            if sensor.get("mode", "time") == "valve":
                influences = sensor.get("valves", [])
                if (not isinstance(influences, list) or not 1 <= len(influences) <= 4
                        or any(not isinstance(v, str) or v not in valve_names for v in influences)
                        or len(set(influences)) != len(influences)):
                    raise ValueError(f"{name} must select 1–4 distinct configured valves")
                initial = sensor.get("initial")
                if isinstance(initial, bool) or not isinstance(initial, (int, float)) or not math.isfinite(initial):
                    raise ValueError(f"{name} requires a finite initial value")
                rates = sensor.get("rates")
                combinations = [format(i, f"0{len(influences)}b") for i in range(2 ** len(influences))]
                if not isinstance(rates, dict) or set(rates) != set(combinations):
                    raise ValueError(f"{name} requires every valve-state row ({len(combinations)} total) to be configured")
                for combination, rate in rates.items():
                    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate):
                        raise ValueError(f"{name} row {combination.replace('0', 'C').replace('1', 'O')} needs a finite rate in {unit}/s")
                minimum, maximum = sensor.get("min"), sensor.get("max")
                for bound, value in (("minimum", minimum), ("maximum", maximum)):
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                        raise ValueError(f"{name} {bound} must be a finite number or blank")
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError(f"{name} minimum cannot exceed maximum")
                if minimum is not None and initial < minimum or maximum is not None and initial > maximum:
                    raise ValueError(f"{name} initial value is outside the configured limits")
                sensor_data[name] = dict(mode="valve", unit=unit, valves=influences, rates=rates,
                                         initial=initial, min=minimum, max=maximum)
                continue
            if sensor.get("mode", "time") != "time":
                raise ValueError(f"Unsupported sensor mode for {name}")
            interpolation = sensor.get("interpolation", "step")
            if interpolation not in {"step", "linear"}:
                raise ValueError(f"Unsupported profile for {name}: {interpolation}")
            samples = sensor.get("samples", [{"at": 0, "value": sensor.get("value", 0)}])
            if not isinstance(samples, list) or not samples:
                raise ValueError(f"{name} requires at least one sample")
            previous = -1
            for sample in samples:
                if not isinstance(sample, dict):
                    raise ValueError(f"Invalid sample for {name}")
                at, value = sample.get("at"), sample.get("value")
                if not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0 or at <= previous:
                    raise ValueError(f"{name} sample times must increase from 0")
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{name} sample values must be finite numbers")
                previous = at
            sensor_data[name] = dict(unit=unit, samples=samples, interpolation=interpolation)
        return valve_names, sensor_data, problems
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        problems.append(diagnostic("api", "error", str(error)))
        return set(), {}, problems


def check_source(source, valves, sensors):
    errors = []
    try:
        tree = ast.parse(source, filename="sequence.py")
        compile(tree, "sequence.py", "exec")
    except SyntaxError as error:
        return None, [diagnostic("syntax", "error", error.msg, error.lineno or 0, error.offset or 0)]

    table = symtable.symtable(source, "sequence.py", "exec")
    defined = set(dir(builtins)) | API | set(valves) | set(sensors)
    for symbol in table.get_symbols():
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace():
            defined.add(symbol.get_name())

    unresolved = set()

    def collect(scope):
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in defined:
                unresolved.add(symbol.get_name())
        for child in scope.get_children():
            collect(child)

    collect(table)
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in unresolved:
            if node.id not in seen:
                errors.append(diagnostic("names", "error", f"Undefined name '{node.id}'", node.lineno, node.col_offset + 1))
                seen.add(node.id)

    errors.extend(analyze_luna_api(tree, valves, sensors))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name.split(".")[0] not in IMPORTS:
                    errors.append(diagnostic("runtime", "warning", f"Import '{item.name}' is not supported by browser simulation", node.lineno, node.col_offset + 1))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] not in IMPORTS:
            errors.append(diagnostic("runtime", "warning", f"Import '{node.module}' is not supported by browser simulation", node.lineno, node.col_offset + 1))
    return tree, errors


class Quantity:
    def __init__(self, raw, kind):
        self.raw = float(raw)
        self.kind = kind

    def check(self, other):
        if not isinstance(other, Quantity) or other.kind != self.kind:
            raise TypeError(f"Cannot combine {self.kind} with {type(other).__name__}")
        return other.raw

    def __add__(self, other):
        return Quantity(self.raw + self.check(other), self.kind)

    def __sub__(self, other):
        return Quantity(self.raw - self.check(other), self.kind)

    def __mul__(self, value):
        return Quantity(self.raw * float(value), self.kind)

    __rmul__ = __mul__

    def __truediv__(self, value):
        return Quantity(self.raw / float(value), self.kind)

    def __lt__(self, other):
        return self.raw < self.check(other)

    def __le__(self, other):
        return self.raw <= self.check(other)

    def __gt__(self, other):
        return self.raw > self.check(other)

    def __ge__(self, other):
        return self.raw >= self.check(other)

    def __eq__(self, other):
        return isinstance(other, Quantity) and self.kind == other.kind and self.raw == other.raw

    def __repr__(self):
        return f"{self.raw:g} {self.kind}"


class SimulationLimit(Exception):
    pass


class SequenceAborted(BaseException):
    """The FC would terminate the operator sequence after an abort."""


class Simulator:
    def __init__(self, valves, sensors, clock_mode="deterministic", speed=5, max_duration=600):
        self.time = 0.0
        self.clock_mode = clock_mode
        self.speed = speed
        self.max_duration = max_duration
        self.wall_start = host_time.perf_counter()
        self.epoch_start = host_time.time()
        self.wait_errors = []
        self.events = []
        self.initial_valves = dict(valves)
        self.valves = dict(valves)
        self.sensors = sensors
        self.dynamic_values = {name: sensor["initial"] for name, sensor in sensors.items()
                               if sensor.get("mode") == "valve"}
        self.dynamic_samples = {name: [{"at": 0.0, "value": value}]
                                for name, value in self.dynamic_values.items()}
        self.sensor_read_lines = {}
        self.last_sensor_read = None
        self.runtime_diagnostics = []
        self.stage = "DEFAULT"
        self.condition = "False"
        self._syncing_clock = False
        self.next_abort_check = 0.01
        self.aborted = False
        self.abort_scope = None
        self.abort_stages = {
            "DEFAULT": dict(name="DEFAULT", condition="False", safe={}, defined_line=0,
                            activated=[0.0], triggered=None, code=compile("False", "<abort>", "eval")),
        }
        self.pending_safe_states = []
        self.abort_eval_line = 0

    def start_clock(self):
        self.wall_start = host_time.perf_counter()
        self.epoch_start = host_time.time()

    @staticmethod
    def source_line():
        frame = sys._getframe(1)
        while frame:
            if frame.f_code.co_filename == "sequence.py":
                return frame.f_lineno
            frame = frame.f_back
        return 0

    def event(self, kind, target, detail, *, line=None, sync=True, **extra):
        if sync:
            self.sync_clock()
        if len(self.events) < 1000:
            self.events.append(dict(time=round(self.time, 4), kind=kind,
                                    target=target, detail=str(detail),
                                    line=self.source_line() if line is None else line, **extra))

    def define_abort_stage(self, name, condition, states, line):
        self.sync_clock()
        if not isinstance(name, str) or not isinstance(condition, str):
            raise TypeError("create_abort_stage expects stage_name and abort_condition strings")
        code, problems = validate_abort_expression(condition, self.valves, self.sensors,
                                                    ast.parse("False", mode="eval").body)
        if problems:
            raise ValueError("; ".join(item["message"] for item in problems))
        self.abort_stages[name] = dict(
            name=name, condition=condition, code=code, safe=dict(states),
            defined_line=line, activated=[], triggered=None,
        )
        self.event("abort_config", name, f"Condition: {condition} · {len(states)} safe-state commands", line=line)

    def activate_abort_stage(self, name, line):
        self.sync_clock()
        if not isinstance(name, str):
            raise TypeError("set_abort_stage expects a string")
        if name not in self.abort_stages:
            raise ValueError(f"Unknown abort stage '{name}' (not created)")
        self.stage = name
        self.condition = self.abort_stages[name]["condition"]
        self.next_abort_check = self.time + 0.01
        self.abort_stages[name]["activated"].append(round(self.time, 4))
        self.event("abort_stage", name, f"Active condition: {self.condition}", line=line)
        self.check_abort_condition()

    def trigger_abort(self, reason, line=None):
        self.sync_clock()
        if self.aborted:
            return
        self.aborted = True
        stage = self.abort_stages[self.stage]
        stage["triggered"] = round(self.time, 4)
        self.event("abort", self.stage, reason, line=line, condition=stage["condition"])
        for name, (state, delay_ms) in stage["safe"].items():
            self.pending_safe_states.append((self.time + delay_ms / 1000, name, state,
                                             stage["defined_line"], delay_ms))
        self.apply_safe_states(self.time)

    def apply_safe_states(self, until):
        self.pending_safe_states.sort(key=lambda item: item[0])
        while self.pending_safe_states and self.pending_safe_states[0][0] <= until + 1e-9:
            at, name, state, line, delay_ms = self.pending_safe_states.pop(0)
            self._integrate_to(max(self.time, at))
            for sensor_name, config in self.sensors.items():
                if config.get("mode") == "valve" and name in config["valves"]:
                    self.record_sensor(sensor_name)
            self.valves[name] = state
            self.event("valve", name, state, line=line, origin="abort", stage=self.stage, sync=False)
            self.event("abort_safe", name, f"{state} after {delay_ms} ms safing delay",
                       line=line, stage=self.stage, sync=False)

    def check_abort_condition(self):
        if self.aborted or self.stage == "DEFAULT" or self.abort_scope is None:
            return
        stage = self.abort_stages[self.stage]
        try:
            self.abort_eval_line = stage["defined_line"]
            result = bool(eval(stage["code"], {"__builtins__": {}}, self.abort_scope))
        except Exception as error:
            raise RuntimeError(f"Abort stage '{self.stage}' condition failed: {error}") from error
        finally:
            self.abort_eval_line = 0
        if result:
            self.trigger_abort(f"Condition became true: {stage['condition']}",
                               line=stage["defined_line"])
            raise SequenceAborted(f"Abort condition triggered in stage '{self.stage}'")

    def _advance_to(self, target):
        if target > self.max_duration:
            context = ""
            if self.last_sensor_read:
                name, value = self.last_sensor_read
                sensor = self.sensors[name]
                if sensor.get("mode") == "valve":
                    key = "".join("1" if self.valves[valve] == "OPEN" else "0" for valve in sensor["valves"])
                    states = ", ".join(f"{valve}={self.valves[valve]}" for valve in sensor["valves"])
                    context = (f"; last {name}={value:g} {sensor['unit']} "
                               f"({states}, rate {sensor['rates'][key]:g} {sensor['unit']}/s)")
                else:
                    context = f"; last {name}={value:g} {sensor['unit']}"
            raise SimulationLimit(f"Simulation reached the {self.max_duration:g}s simulated-time limit; "
                                  f"a loop or sensor condition may never complete{context}")
        # Luna's abort subprocess polls at 10 ms. Advance time-dependent
        # sensors to each checkpoint before evaluating the active condition.
        if self.aborted or self.stage == "DEFAULT" or self.abort_scope is None:
            self._integrate_to(target)
            return
        while self.time < target - 1e-10:
            checkpoint = min(target, self.next_abort_check)
            if checkpoint <= self.time:
                self.next_abort_check = round(self.time + 0.01, 6)
                checkpoint = min(target, self.next_abort_check)
            self._integrate_to(checkpoint)
            if self.time >= self.next_abort_check - 1e-9:
                self.next_abort_check = round(self.next_abort_check + 0.01, 6)
                self.check_abort_condition()

    def _integrate_to(self, target):
        seconds = max(0, target - self.time)
        for name, sensor in self.sensors.items():
            if sensor.get("mode") != "valve":
                continue
            key = "".join("1" if self.valves[valve] == "OPEN" else "0" for valve in sensor["valves"])
            rate = sensor["rates"][key]
            current = self.dynamic_values[name]
            next_value = current + seconds * rate
            bound = sensor["max"] if rate > 0 else sensor["min"]
            if bound is not None and ((rate > 0 and next_value > bound) or (rate < 0 and next_value < bound)):
                crossing = self.time + (bound - current) / rate
                self.record_sensor(name, crossing, bound)
                next_value = bound
            self.dynamic_values[name] = next_value
        self.time += seconds

    def sync_clock(self):
        if self.clock_mode == "realtime" and not self._syncing_clock:
            self._syncing_clock = True
            try:
                self._advance_to(max(self.time, (host_time.perf_counter() - self.wall_start) * self.speed))
            finally:
                self._syncing_clock = False

    def advance(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Wait duration must be finite and nonnegative")
        self.sync_clock()
        if self.clock_mode == "deterministic":
            self._advance_to(self.time + seconds)
            return
        starting = self.time
        target = starting + seconds
        if target > self.max_duration:
            self._advance_to(target)
        deadline = self.wall_start + target / self.speed
        while True:
            remaining = deadline - host_time.perf_counter()
            if remaining <= 0:
                break
            host_time.sleep(remaining if remaining < .002 else remaining - .0005)
        self.sync_clock()
        if seconds > 0:
            self.wait_errors.append(max(0, self.time - starting - seconds))

    def elapsed_time(self):
        self.sync_clock()
        return self.time

    def clock_time(self):
        self.sync_clock()
        return self.epoch_start + self.time if self.clock_mode == "realtime" else self.time

    def timing_summary(self):
        wall = max(0, host_time.perf_counter() - self.wall_start)
        return {"mode": self.clock_mode, "requested_speed": self.speed if self.clock_mode == "realtime" else None,
                "wall_seconds": round(wall, 4), "actual_speed": round(self.time / wall, 3) if wall and self.clock_mode == "realtime" else None,
                "wait_count": len(self.wait_errors),
                "max_wait_overshoot_ms": round(1000 * max(self.wait_errors, default=0), 3),
                "simulated_limit_seconds": self.max_duration}

    def record_sensor(self, name, at=None, value=None):
        at = self.time if at is None else at
        value = self.dynamic_values[name] if value is None else value
        samples = self.dynamic_samples[name]
        if at > samples[-1]["at"] + 1e-10:
            samples.append({"at": round(at, 6), "value": value})
        else:
            samples[-1]["value"] = value

    def sensor_traces(self):
        result = {}
        for name, sensor in self.sensors.items():
            if sensor.get("mode") != "valve":
                result[name] = sensor
                continue
            self.record_sensor(name)
            result[name] = dict(mode="valve", unit=sensor["unit"], interpolation="linear",
                                samples=self.dynamic_samples[name], valves=sensor["valves"], rates=sensor["rates"])
        return result

    def finish(self):
        # The SAM safe-state timers continue after the FC kills the sequence.
        if self.pending_safe_states:
            self.apply_safe_states(max(item[0] for item in self.pending_safe_states))

    def coverage(self):
        return [{
            "name": item["name"], "condition": item["condition"],
            "defined_line": item["defined_line"], "activated": item["activated"],
            "triggered": item["triggered"],
            "safe_states": [{"name": name, "state": state, "delay_ms": delay}
                            for name, (state, delay) in item["safe"].items()],
        } for item in self.abort_stages.values() if item["name"] != "DEFAULT"]

    def read(self, name):
        self.sync_clock()
        if name not in self.sensors:
            raise KeyError(f"Unknown sensor '{name}'")
        line = self.abort_eval_line or self.source_line()
        if line:
            lines = self.sensor_read_lines.setdefault(name, set())
            lines.add(line)
        sensor = self.sensors[name]
        if sensor.get("mode") == "valve":
            value = self.dynamic_values[name]
            self.last_sensor_read = (name, value)
            return value if sensor["unit"] == "unknown" else Quantity(value, sensor["unit"])
        value = sensor["samples"][0]["value"]
        previous = sensor["samples"][0]
        for sample in sensor["samples"][1:]:
            if sample["at"] > self.time:
                if sensor["interpolation"] == "linear" and self.time > previous["at"]:
                    ratio = (self.time - previous["at"]) / (sample["at"] - previous["at"])
                    value = previous["value"] + ratio * (sample["value"] - previous["value"])
                break
            value = sample["value"]
            previous = sample
        self.last_sensor_read = (name, value)
        return value if sensor["unit"] == "unknown" else Quantity(value, sensor["unit"])

    def make_module(self):
        sim = self
        module = types.ModuleType("common")

        class ValveState:
            Undetermined = "UNDETERMINED"
            Disconnected = "DISCONNECTED"
            Open = "OPEN"
            Closed = "CLOSED"
            Fault = "FAULT"

        class Valve:
            def __init__(self, name):
                if not isinstance(name, str):
                    raise TypeError("Valve name must be a string")
                if name not in sim.valves:
                    raise KeyError(f"Unknown valve '{name}'")
                self.name = name

            def __hash__(self):
                return hash(self.name)

            def __eq__(self, other):
                return isinstance(other, Valve) and self.name == other.name

            def actuate(self, opening):
                sim.sync_clock()
                if type(opening) is not bool:
                    raise TypeError("Valve.actuate(open) requires a bool")
                state = "OPEN" if opening else "CLOSED"
                if sim.valves[self.name] != state:
                    for sensor_name, config in sim.sensors.items():
                        if config.get("mode") == "valve" and self.name in config["valves"]:
                            sim.record_sensor(sensor_name)
                sim.valves[self.name] = state
                sim.event("valve", self.name, state)

            def open(self):
                self.actuate(True)

            def close(self):
                self.actuate(False)

            def is_open(self):
                sim.sync_clock()
                return sim.valves[self.name] == "OPEN"

            def is_closed(self):
                sim.sync_clock()
                return sim.valves[self.name] == "CLOSED"

        class Sensor:
            def __init__(self, name):
                if not isinstance(name, str):
                    raise TypeError("Sensor name must be a string")
                if name not in sim.sensors:
                    raise KeyError(f"Unknown sensor '{name}'")
                self.name = name

            def read(self):
                return sim.read(self.name)

            def __gt__(self, other):
                return self.read() > other

            def __ge__(self, other):
                return self.read() >= other

            def __lt__(self, other):
                return self.read() < other

            def __le__(self, other):
                return self.read() <= other

        def wait_for(duration):
            if not isinstance(duration, Quantity) or duration.kind != "s":
                raise TypeError("wait_for expects a Duration such as 500 * ms")
            sim.advance(duration.raw)

        def wait_until(condition, timeout=None, poll_interval=None):
            if timeout is not None and (not isinstance(timeout, Quantity) or timeout.kind != "s"):
                raise TypeError("wait_until timeout must be a Duration")
            if poll_interval is not None and (not isinstance(poll_interval, Quantity) or poll_interval.kind != "s"):
                raise TypeError("wait_until poll_interval must be a Duration")
            sim.sync_clock()
            limit = timeout.raw if isinstance(timeout, Quantity) else sim.max_duration - sim.time
            poll = poll_interval.raw if isinstance(poll_interval, Quantity) else 0.01
            if poll <= 0:
                raise ValueError("poll_interval must be positive")
            deadline = min(sim.time + limit, sim.max_duration)
            calls = 0
            while not condition():
                sim.sync_clock()
                if sim.time >= deadline:
                    if sim.time >= sim.max_duration:
                        sim._advance_to(sim.time + 0.001)
                    sim.event("timeout", "wait_until", "Condition not met; Luna returns without raising")
                    sim.runtime_diagnostics.append(diagnostic(
                        "runtime", "warning", "wait_until() timed out before its condition became true; "
                        "Luna continues executing the sequence", sim.source_line()))
                    return
                if calls > 100000:
                    raise SimulationLimit("Too many wait_until polls")
                sim.advance(min(poll, deadline - sim.time))
                calls += 1

        def interval(count, period):
            if type(count) is not int:
                raise TypeError("interval count must be an integer")
            if not isinstance(period, Quantity) or period.kind != "s":
                raise TypeError("interval expects a Duration")
            sim.sync_clock()
            start = sim.time
            for i in range(count):
                sim.sync_clock()
                sim.advance(max(0, start + i * period.raw - sim.time))
                yield i

        def send(name, *args):
            sim.event("command", name, ", ".join(map(str, args)))

        def strict_bool(value):
            if type(value) is not bool:
                raise TypeError("Luna expects a boolean argument")
            return value

        def strict_string(value):
            if not isinstance(value, str):
                raise TypeError("Luna expects a string argument")
            return value

        def create_abort_stage(name, condition, safe_states):
            if not isinstance(safe_states, dict):
                raise TypeError("safe_valve_states must be a dictionary")
            checked = {}
            for valve, state in safe_states.items():
                if not isinstance(valve, Valve) or not isinstance(state, tuple) or len(state) != 2:
                    raise TypeError("Each safe state must map Valve to (ValveState, timer)")
                if state[0] not in (ValveState.Open, ValveState.Closed) or type(state[1]) is not int or not 0 <= state[1] <= 0xFFFFFFFF:
                    raise TypeError("Safe states require OPEN/CLOSED and a u32 millisecond timer")
                checked[valve.name] = state
            sim.define_abort_stage(name, condition, checked, sim.source_line())

        def set_abort_stage(name):
            sim.activate_abort_stage(name, sim.source_line())

        def abort():
            sim.trigger_abort("Manual abort requested", line=sim.source_line())
            raise SequenceAborted("Operator sequence terminated after abort")

        def clear_abort_status():
            sim.aborted = False
            send("clear_abort_status")

        names = {
            "Valve": Valve, "Sensor": Sensor, "ValveState": ValveState,
            "ValveSafeState": dict, "IntervalIterator": type(interval(0, Quantity(1, "s"))),
            "OPEN": ValveState.Open, "CLOSED": ValveState.Closed,
            "wait_for": wait_for, "wait_until": wait_until, "interval": interval,
            "create_abort_stage": create_abort_stage, "set_abort_stage": set_abort_stage,
            "curr_abort_stage": lambda: sim.stage,
            "curr_abort_condition": lambda: sim.condition,
            "aborted_in_this_stage": lambda: sim.aborted,
            "abort": abort, "clear_abort_status": clear_abort_status,
            "send_reco_launch": lambda: send("send_reco_launch"),
            "reco_init_ekf": lambda: send("reco_init_ekf"),
            "read_umbilical_voltage": lambda: Quantity(0, "V"),
            "reco_recvd_launch": lambda: False,
            "launch_lug_arm": lambda host, enabled: send("launch_lug_arm", strict_string(host), strict_bool(enabled)),
            "launch_lug_detonate": lambda host, enabled: send("launch_lug_detonate", strict_string(host), strict_bool(enabled)),
            "set_servo_disconnect_abort": lambda enabled: send("set_servo_disconnect_abort", strict_bool(enabled)),
            "sam_camera_toggle": lambda enabled: send("sam_camera_toggle", strict_bool(enabled)),
            "__layout_fingerprint__": "mock-layout-not-real-fc",
        }
        for name, kind in (("Current", "A"), ("Duration", "s"), ("ElectricPotential", "V"),
                           ("Force", "lbf"), ("Pressure", "psi"), ("Temperature", "K")):
            names[name] = lambda value, k=kind: Quantity(value, k)
        for name, kind, factor in (("A", "A", 1), ("mA", "A", 0.001),
                                   ("s", "s", 1), ("ms", "s", 0.001), ("us", "s", 0.000001),
                                   ("V", "V", 1), ("mV", "V", 0.001), ("lbf", "lbf", 1),
                                   ("psi", "psi", 1), ("K", "K", 1)):
            names[name] = Quantity(factor, kind)
        for key, value in names.items():
            setattr(module, key, value)
        module.__all__ = list(names)
        return module


def run_sequence(source, mapping, execute=False, options=None):
    valves, sensors, diagnostics = check_mapping(mapping)
    result = {"checks": {"syntax": "not_run", "names": "not_run", "api": "not_run", "runtime": "not_run"},
              "diagnostics": diagnostics, "events": [], "stdout": "", "virtual_time": 0, "valves": {},
              "simulation": None}
    tree, source_diagnostics = check_source(source, valves, sensors)
    result["diagnostics"].extend(source_diagnostics)
    if tree is None:
        result["checks"]["syntax"] = "fail"
        return result
    result["checks"]["syntax"] = "pass"
    for stage in ("names", "api"):
        result["checks"][stage] = "fail" if any(d["stage"] == stage and d["severity"] == "error" for d in result["diagnostics"]) else "pass"
    if not execute or any(d["severity"] == "error" for d in result["diagnostics"]):
        return result

    options = options or {}
    try:
        clock_mode = options.get("clock_mode", "deterministic")
        speed = options.get("speed", 5)
        max_duration = options.get("max_duration", 600)
        if clock_mode not in ("deterministic", "realtime"):
            raise ValueError("Clock mode must be realtime or deterministic")
        if isinstance(speed, bool) or speed not in (1, 5):
            raise ValueError("Simulation speed must be either 1× or 5×")
        if (isinstance(max_duration, bool) or not isinstance(max_duration, (int, float))
                or not math.isfinite(max_duration) or not 1 <= max_duration <= 3600):
            raise ValueError("Simulated-time limit must be between 1 and 3600 seconds")
    except (AttributeError, ValueError, TypeError) as error:
        result["checks"]["runtime"] = "fail"
        result["diagnostics"].append(diagnostic("runtime", "error", f"Invalid simulation settings: {error}"))
        return result

    sim = Simulator(valves, sensors, clock_mode=clock_mode, speed=speed, max_duration=max_duration)
    common = sim.make_module()
    fake_time = types.ModuleType("time")
    fake_time.sleep = sim.advance
    fake_time.time = sim.clock_time
    fake_time.monotonic = sim.elapsed_time
    fake_time.perf_counter = sim.elapsed_time
    allowed = {"common": common, "time": fake_time, "math": math}

    def import_module(name, *args, **kwargs):
        if name in allowed:
            return allowed[name]
        raise ImportError(f"Import '{name}' is unavailable in this browser simulator")

    safe = vars(builtins).copy()
    for name in ("open", "input", "exec", "eval", "compile", "breakpoint"):
        safe.pop(name, None)
    safe["__import__"] = import_module
    scope = {"__builtins__": safe, "__name__": "__main__"}
    scope.update({name: getattr(common, name) for name in common.__all__})
    for name in valves:
        scope[name] = common.Valve(name)
    for name in sensors:
        scope[name] = common.Sensor(name)
    # Luna runs abort conditions in a distinct Python process with the same
    # mapping prelude, NOT the parent sequence's local variables.
    sim.abort_scope = {name: scope[name] for name in API if name in scope}
    sim.abort_scope.update({name: scope[name] for name in (*valves, *sensors)})
    sim.abort_scope.update({name: safe[name] for name in
                            ("abs", "min", "max", "round", "int", "float", "bool")})
    output = io.StringIO()
    try:
        code = compile(tree, "sequence.py", "exec")
        sim.start_clock()
        with contextlib.redirect_stdout(output):
            exec(code, scope, scope)
        sim.sync_clock()
        result["checks"]["runtime"] = "pass"
    except SequenceAborted:
        result["checks"]["runtime"] = "pass"
    except BaseException as error:
        line = next((frame.lineno for frame in reversed(traceback.extract_tb(error.__traceback__)) if frame.filename == "sequence.py"), 0)
        result["checks"]["runtime"] = "fail"
        result["diagnostics"].append(diagnostic("runtime", "error", f"{type(error).__name__}: {error}", line))
    sim.finish()
    for stage in sim.coverage():
        if not stage["activated"]:
            result["diagnostics"].append(diagnostic(
                "abort", "warning", f"ABORT STAGE NOT ACTIVATED: '{stage['name']}' was defined but never selected",
                stage["defined_line"]))
        elif stage["triggered"] is None:
            result["diagnostics"].append(diagnostic(
                "abort", "warning", f"ABORT CONDITION NEVER TRIGGERED: '{stage['name']}' ({stage['condition']}) did not fire with these sensor profiles",
                stage["defined_line"]))
    result["stdout"] = output.getvalue()[:10000]
    result["diagnostics"].extend(sim.runtime_diagnostics)
    result["events"] = sim.events
    result["virtual_time"] = round(sim.time, 4)
    result["timing"] = sim.timing_summary()
    result["valves"] = sim.valves
    result["simulation"] = {
        "initial_valves": sim.initial_valves,
        "sensors": sim.sensor_traces(),
        "sensor_read_lines": {name: sorted(lines) for name, lines in sim.sensor_read_lines.items()},
        "abort_stages": sim.coverage(),
        "aborted": sim.aborted,
    }
    return result
