import ast
import builtins
import contextlib
import io
import json
import math
import sys
import symtable
import traceback
import types


API = {
    "Current", "Duration", "ElectricPotential", "Force", "Pressure", "Temperature",
    "A", "mA", "s", "ms", "us", "V", "mV", "lbf", "psi", "K",
    "Sensor", "Valve", "ValveState", "ValveSafeState", "IntervalIterator",
    "wait_for", "wait_until", "abort", "clear_abort_status", "interval",
    "create_abort_stage", "set_abort_stage", "curr_abort_stage",
    "curr_abort_condition", "aborted_in_this_stage", "send_reco_launch",
    "reco_init_ekf", "read_umbilical_voltage", "reco_recvd_launch",
    "launch_lug_arm", "launch_lug_detonate", "set_servo_disconnect_abort",
    "sam_camera_toggle", "OPEN", "CLOSED",
}
IMPORTS = {"common", "time", "math"}
VALVE_METHODS = {"open", "close", "actuate", "is_open", "is_closed", "get_name"}
SENSOR_METHODS = {"read"}
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

    kinds = {name: "valve" for name in valves}
    kinds.update({name: "sensor" for name in sensors})
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"Valve", "Sensor"}:
                kind = value.func.id.lower()
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        kinds[target.id] = kind
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name.split(".")[0] not in IMPORTS:
                    errors.append(diagnostic("runtime", "warning", f"Import '{item.name}' is not supported by browser simulation", node.lineno, node.col_offset + 1))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] not in IMPORTS:
            errors.append(diagnostic("runtime", "warning", f"Import '{node.module}' is not supported by browser simulation", node.lineno, node.col_offset + 1))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            name, method = node.func.value.id, node.func.attr
            kind = kinds.get(name)
            if kind and method not in (VALVE_METHODS if kind == "valve" else SENSOR_METHODS):
                errors.append(diagnostic("api", "error", f"{kind.title()} '{name}' does not support .{method}()", node.lineno, node.col_offset + 1))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"Valve", "Sensor"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                name = node.args[0].value
                pool = valves if node.func.id == "Valve" else sensors
                if name not in pool:
                    errors.append(diagnostic("api", "error", f"{node.func.id} '{name}' is not in the selected mapping", node.lineno, node.col_offset + 1))
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


class Simulator:
    def __init__(self, valves, sensors):
        self.time = 0.0
        self.events = []
        self.initial_valves = dict(valves)
        self.valves = dict(valves)
        self.sensors = sensors
        self.dynamic_values = {name: sensor["initial"] for name, sensor in sensors.items()
                               if sensor.get("mode") == "valve"}
        self.dynamic_samples = {name: [{"at": 0.0, "value": value}]
                                for name, value in self.dynamic_values.items()}
        self.sensor_read_lines = {}
        self.stage = ""
        self.condition = ""
        self.aborted = False

    @staticmethod
    def source_line():
        frame = sys._getframe(1)
        while frame:
            if frame.f_code.co_filename == "sequence.py":
                return frame.f_lineno
            frame = frame.f_back
        return 0

    def event(self, kind, target, detail):
        if len(self.events) < 300:
            self.events.append(dict(time=round(self.time, 4), kind=kind,
                                    target=target, detail=str(detail), line=self.source_line()))

    def advance(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Wait duration must be finite and nonnegative")
        if self.time + seconds > 3600:
            raise SimulationLimit("Simulation exceeded one hour of virtual time")
        for name, sensor in self.sensors.items():
            if sensor.get("mode") != "valve":
                continue
            key = "".join("1" if self.valves[valve] == "OPEN" else "0" for valve in sensor["valves"])
            rate = sensor["rates"][key]
            current = self.dynamic_values[name]
            target = current + seconds * rate
            bound = sensor["max"] if rate > 0 else sensor["min"]
            if bound is not None and ((rate > 0 and target > bound) or (rate < 0 and target < bound)):
                crossing = self.time + (bound - current) / rate
                self.record_sensor(name, crossing, bound)
                target = bound
            self.dynamic_values[name] = target
        self.time += seconds

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

    def read(self, name):
        if name not in self.sensors:
            raise KeyError(f"Unknown sensor '{name}'")
        line = self.source_line()
        if line:
            lines = self.sensor_read_lines.setdefault(name, set())
            lines.add(line)
        sensor = self.sensors[name]
        if sensor.get("mode") == "valve":
            value = self.dynamic_values[name]
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
        return value if sensor["unit"] == "unknown" else Quantity(value, sensor["unit"])

    def make_module(self):
        sim = self
        module = types.ModuleType("common")

        class ValveState:
            Open = "OPEN"
            Closed = "CLOSED"

        class Valve:
            def __init__(self, name):
                if name not in sim.valves:
                    raise KeyError(f"Unknown valve '{name}'")
                self.name = name

            def get_name(self):
                return self.name

            def actuate(self, opening):
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
                return sim.valves[self.name] == "OPEN"

            def is_closed(self):
                return sim.valves[self.name] == "CLOSED"

        class Sensor:
            def __init__(self, name):
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
            limit = timeout.raw if isinstance(timeout, Quantity) else 3600 - sim.time
            poll = poll_interval.raw if isinstance(poll_interval, Quantity) else 0.01
            if poll <= 0:
                raise ValueError("poll_interval must be positive")
            deadline = min(sim.time + limit, 3600)
            calls = 0
            while not condition():
                if sim.time >= deadline:
                    sim.event("timeout", "wait_until", "Condition not met; Luna returns without raising")
                    return
                if calls > 100000:
                    raise SimulationLimit("Too many wait_until polls")
                sim.advance(min(poll, deadline - sim.time))
                calls += 1

        def interval(count, period):
            if not isinstance(period, Quantity) or period.kind != "s":
                raise TypeError("interval expects a Duration")
            start = sim.time
            for i in range(count):
                sim.advance(max(0, start + i * period.raw - sim.time))
                yield i

        def send(name, *args):
            sim.event("command", name, ", ".join(map(str, args)))

        def create_abort_stage(name, condition, safe_states):
            if not isinstance(safe_states, dict):
                raise TypeError("safe_valve_states must be a dictionary")
            for valve, state in safe_states.items():
                if not isinstance(valve, Valve) or not isinstance(state, tuple) or len(state) != 2:
                    raise TypeError("Each safe state must map Valve to (ValveState, timer)")
                if state[0] not in (ValveState.Open, ValveState.Closed) or not isinstance(state[1], int) or state[1] < 0:
                    raise TypeError("Safe states require OPEN/CLOSED and a nonnegative integer timer")
            send("create_abort_stage", name, condition, f"{len(safe_states)} valve states")

        def set_abort_stage(name):
            sim.stage = name
            sim.event("abort_stage", name, "Transition simulated, not hardware-confirmed")

        def abort():
            sim.aborted = True
            send("abort", "Abort requested")

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
            "launch_lug_arm": lambda host, enabled: send("launch_lug_arm", host, enabled),
            "launch_lug_detonate": lambda host, enabled: send("launch_lug_detonate", host, enabled),
            "set_servo_disconnect_abort": lambda enabled: send("set_servo_disconnect_abort", enabled),
            "sam_camera_toggle": lambda enabled: send("sam_camera_toggle", enabled),
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


def run_sequence(source, mapping, execute=False):
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

    sim = Simulator(valves, sensors)
    common = sim.make_module()
    fake_time = types.ModuleType("time")
    fake_time.sleep = sim.advance
    fake_time.time = lambda: sim.time
    fake_time.monotonic = lambda: sim.time
    fake_time.perf_counter = lambda: sim.time
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
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(tree, "sequence.py", "exec"), scope, scope)
        result["checks"]["runtime"] = "pass"
    except BaseException as error:
        line = next((frame.lineno for frame in reversed(traceback.extract_tb(error.__traceback__)) if frame.filename == "sequence.py"), 0)
        result["checks"]["runtime"] = "fail"
        result["diagnostics"].append(diagnostic("runtime", "error", f"{type(error).__name__}: {error}", line))
    result["stdout"] = output.getvalue()[:10000]
    result["events"] = sim.events
    result["virtual_time"] = round(sim.time, 4)
    result["valves"] = sim.valves
    result["simulation"] = {
        "initial_valves": sim.initial_valves,
        "sensors": sim.sensor_traces(),
        "sensor_read_lines": {name: sorted(lines) for name, lines in sim.sensor_read_lines.items()},
    }
    return result
