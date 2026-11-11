"""Conservative source checks against Luna's *actual* Python binding signatures.

Only statically provable mismatches fail. Expressions of unknown type are checked
again by the simulator when executed. This module has no abort-stage semantics.
"""

import ast

from luna_contract import (COMMON_EXPORTS, CONSTRUCTORS, FUNCTIONS, METHODS,
                           OTHER_CLASSES, UNIT_CLASSES, UNIT_CONSTANTS, VALVE_STATES)


def issue(message, node, severity="error"):
    return {"stage": "api", "severity": severity, "message": message,
            "line": getattr(node, "lineno", 0), "column": getattr(node, "col_offset", -1) + 1}


class LunaApiChecker(ast.NodeVisitor):
    def __init__(self, valves, sensors):
        self.valves = valves
        self.sensors = sensors
        self.errors = []
        self.types = {name: f"quantity:{kind}" for name, kind in UNIT_CONSTANTS.items()}
        self.types.update({name: "valve" for name in valves})
        self.types.update({name: f"sensor:{data['unit']}" for name, data in sensors.items()})
        self.types.update({"OPEN": "valvestate", "CLOSED": "valvestate"})
        self.common_modules = {"common"}
        self.aliases = {}

    def record(self, message, node, severity="error"):
        self.errors.append(issue(message, node, severity))

    def type_of(self, node):
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return "bool"
            if type(node.value) is str:
                return "str"
            if type(node.value) is int:
                return "int"
            if type(node.value) is float:
                return "float"
            if node.value is None:
                return "none"
        if isinstance(node, ast.Name):
            return self.types.get(node.id, "unknown")
        if isinstance(node, ast.Lambda):
            return "callable"
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, (ast.Compare, ast.BoolOp)):
            return "bool"
        if isinstance(node, ast.UnaryOp):
            return "bool" if isinstance(node.op, ast.Not) else self.type_of(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = self.type_of(node.left), self.type_of(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return left if left == right else "unknown"
            if isinstance(node.op, (ast.Mult, ast.Div)):
                if left.startswith("quantity:") and right in {"int", "float"}:
                    return left
                if isinstance(node.op, ast.Mult) and right.startswith("quantity:") and left in {"int", "float"}:
                    return right
            return "float" if left in {"int", "float"} and right in {"int", "float"} else "unknown"
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "ValveState":
                return "valvestate" if node.attr in VALVE_STATES else "unknown"
        if isinstance(node, ast.Call):
            name, owner = self.call_target(node.func)
            if owner in {"Valve", "Sensor"}:
                if name == "read" and owner == "Sensor" and isinstance(node.func.value, ast.Name):
                    kind = self.types.get(node.func.value.id, "unknown")
                    return "float" if kind == "sensor:unknown" else kind.replace("sensor:", "quantity:")
                return "bool" if name in {"is_open", "is_closed"} else "unknown"
            if owner is None and name in CONSTRUCTORS:
                if name in UNIT_CLASSES:
                    return f"quantity:{UNIT_CLASSES[name]}"
                if name == "Valve":
                    return "valve"
                if name == "Sensor":
                    first = node.args[0] if node.args else None
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        return f"sensor:{self.sensors.get(first.value, {}).get('unit', 'unknown')}"
                    return "sensor:unknown"
            if owner is None and name in {"reco_recvd_launch", "aborted_in_this_stage"}:
                return "bool"
            if owner is None and name in {"curr_abort_stage", "curr_abort_condition"}:
                return "str"
            if owner is None and name == "read_umbilical_voltage":
                return "quantity:V"
        return "unknown"

    def call_target(self, func):
        if isinstance(func, ast.Name):
            return self.aliases.get(func.id, func.id), None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.common_modules:
                return func.attr, None
        if isinstance(func, ast.Attribute):
            kind = self.type_of(func.value)
            if kind == "valve":
                return func.attr, "Valve"
            if kind.startswith("sensor:"):
                return func.attr, "Sensor"
        return None, None

    def visit_Import(self, node):
        for item in node.names:
            if item.name == "common":
                self.common_modules.add(item.asname or "common")

    def visit_ImportFrom(self, node):
        if node.module == "common":
            for item in node.names:
                if item.name != "*":
                    if item.name not in COMMON_EXPORTS:
                        self.record(f"Luna's common module does not export '{item.name}'", node)
                    self.aliases[item.asname or item.name] = item.name

    def visit_Assign(self, node):
        self.visit(node.value)
        inferred = self.type_of(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.types[target.id] = inferred

    def visit_AnnAssign(self, node):
        if node.value:
            self.visit(node.value)
            if isinstance(node.target, ast.Name):
                self.types[node.target.id] = self.type_of(node.value)

    def visit_Call(self, node):
        name, owner = self.call_target(node.func)
        if owner and name not in METHODS[owner]:
            self.record(f"{owner} does not expose .{name}() in Luna's Python API", node)
        signature = METHODS[owner].get(name) if owner and name in METHODS[owner] else None
        if owner is None:
            signature = FUNCTIONS.get(name, CONSTRUCTORS.get(name))
            if name in OTHER_CLASSES:
                self.record(f"Luna's {name} class has no public Python constructor", node)
        if signature is not None:
            self.check_signature(name, node, signature)
        if name in {"Valve", "Sensor"} and owner is None and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                pool = self.valves if name == "Valve" else self.sensors
                if first.value not in pool:
                    self.record(f"{name} '{first.value}' is not in the Test Environment", node)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id in self.common_modules:
            if node.attr not in COMMON_EXPORTS:
                self.record(f"Luna's common module does not export '{node.attr}'", node)
        if isinstance(node.value, ast.Name) and node.value.id == "ValveState" and node.attr not in VALVE_STATES:
            self.record(f"Unknown Luna ValveState.{node.attr}", node)
        if node.attr == "raw" and self.type_of(node.value).startswith("quantity:"):
            self.record("Luna's PyO3 quantity classes do not expose a Python .raw attribute", node)
        self.generic_visit(node)

    def visit_BinOp(self, node):
        left, right = self.type_of(node.left), self.type_of(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)) and left.startswith("quantity:") and right.startswith("quantity:") and left != right:
            self.record(f"Luna cannot combine {left[9:]} and {right[9:]} units with + or -", node)
        self.generic_visit(node)

    def visit_Compare(self, node):
        terms = [node.left, *node.comparators]
        for a, b in zip(terms, terms[1:]):
            left, right = self.type_of(a), self.type_of(b)
            if left.startswith("sensor:"):
                left = left.replace("sensor:", "quantity:")
            if right.startswith("sensor:"):
                right = right.replace("sensor:", "quantity:")
            if left.startswith("quantity:") and right != "unknown" and left != right:
                self.record(f"Luna comparison mixes {left[9:]} with {right}", node)
        self.generic_visit(node)

    def check_signature(self, name, node, signature):
        if any(isinstance(arg, ast.Starred) for arg in node.args) or any(keyword.arg is None for keyword in node.keywords):
            self.record(f"{name}() uses dynamic argument unpacking; full API check deferred to runtime", node, "warning")
            return
        expected = {param: kind for param, kind in signature}
        required = {param for param, kind in signature if not kind.startswith("Option<")}
        passed = {}
        if len(node.args) > len(signature):
            self.record(f"{name}() takes at most {len(signature)} argument(s), got {len(node.args)}", node)
        for (param, _), value in zip(signature, node.args):
            passed[param] = value
        for keyword in node.keywords:
            if keyword.arg not in expected:
                self.record(f"{name}() has no parameter '{keyword.arg}'", keyword)
            elif keyword.arg in passed:
                self.record(f"{name}() received '{keyword.arg}' more than once", keyword)
            else:
                passed[keyword.arg] = keyword.value
        missing = required - set(passed)
        if missing:
            self.record(f"{name}() missing required argument(s): {', '.join(sorted(missing))}", node)
        for param, value in passed.items():
            kind = expected[param]
            actual = self.type_of(value)
            if actual == "unknown":
                continue
            if kind.startswith("Option<"):
                if actual == "none":
                    continue
                kind = kind[7:-1]
            valid = {"Duration": {"quantity:s"}, "String": {"str"}, "bool": {"bool"},
                     "&PyAny": {"callable"}, "&PyDict": {"dict"}, "u32": {"int"},
                     "i64": {"int"}, "f64": {"int", "float"}}.get(kind)
            if valid and actual not in valid:
                self.record(f"{name}() parameter '{param}' expects {kind}, got {actual}", value)
            if kind == "u32" and isinstance(value, ast.Constant) and type(value.value) is int:
                if not 0 <= value.value <= 0xFFFFFFFF:
                    self.record(f"{name}() parameter '{param}' must fit an unsigned 32-bit integer", value)


def analyze_luna_api(tree, valves, sensors):
    checker = LunaApiChecker(valves, sensors)
    checker.visit(tree)
    return checker.errors
