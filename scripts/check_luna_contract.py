"""Fail on drift between Luna main's PyO3 Python API and the checked contract.

Usage: python scripts/check_luna_contract.py /path/to/luna-main
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from luna_contract import (  # noqa: E402
    CONSTRUCTORS, FUNCTIONS, METHODS, OTHER_CLASSES, OTHER_EXPORTS,
    PRELUDE, UNIT_CLASSES, UNIT_CONSTANTS, VALVE_STATES,
)


def signature_args(source, function):
    match = re.search(r"\b(?:pub\s+)?fn\s+" + re.escape(function) + r"\s*\(", source)
    if not match:
        raise AssertionError(f"No Rust function {function} found")
    start = match.end()
    depth = 1
    end = start
    while depth:
        if end >= len(source):
            raise AssertionError(f"Unterminated function signature: {function}")
        if source[end] == "(":
            depth += 1
        elif source[end] == ")":
            depth -= 1
        end += 1
    args = []
    for param in source[start:end - 1].split(","):
        param = param.strip()
        if not param or param in ("&self", "&mut self"):
            continue
        if ":" not in param:
            raise AssertionError(f"Unexpected signature parameter in {function}: {param!r}")
        name, kind = param.split(":", 1)
        args.append((name.strip(), "".join(kind.split())))
    return tuple(args)


def public_pyo3_methods(source, cls):
    block = re.search(r"#\[pymethods\]\s*impl\s+" + cls + r"\s*\{(.*?)^\}",
                      source, re.MULTILINE | re.DOTALL)
    if not block:
        raise AssertionError(f"Missing #[pymethods] block for {cls}")
    return set(re.findall(r"\bpub\s+fn\s+(\w+)\s*\(", block.group(1)))


def check(repo):
    root = repo / "common" / "src" / "sequence"
    mod = (root / "mod.rs").read_text()
    func = (root / "func.rs").read_text()
    device = (root / "device.rs").read_text()
    unit = (root / "unit.rs").read_text()
    gui = (repo / "common" / "src" / "comm" / "gui.rs").read_text()
    flight = (repo / "flight2" / "src" / "sequence.rs").read_text()

    exported_functions = set(re.findall(r"wrap_pyfunction!\((\w+),\s*module\)", mod))
    assert exported_functions == set(FUNCTIONS), (
        f"Luna functions changed: new={exported_functions - set(FUNCTIONS)}, "
        f"missing={set(FUNCTIONS) - exported_functions}"
    )
    declared_functions = set(re.findall(r"#\[pyfunction\]\s*pub\s+fn\s+(\w+)\s*\(", func))
    assert declared_functions == exported_functions, "PyO3 functions/export list diverged"
    for name, expected in FUNCTIONS.items():
        actual = signature_args(func, name)
        assert actual == expected, f"Luna {name} signature drifted: {actual} != {expected}"

    for cls, methods in METHODS.items():
        actual = public_pyo3_methods(device, cls)
        expected = set(methods) | {"new"}
        assert actual == expected, f"Luna {cls} methods drifted: {actual} != {expected}"
        for name, signature in {"new": CONSTRUCTORS[cls], **methods}.items():
            block = re.search(r"#\[pymethods\]\s*impl\s+" + cls + r"\s*\{(.*?)^\}",
                              device, re.MULTILINE | re.DOTALL).group(1)
            assert signature_args(block, name) == signature, f"Luna {cls}.{name} signature drifted"

    exports = set(re.findall(r"module\.add_class::<(\w+)>\(\)\?", mod))
    assert exports == set(CONSTRUCTORS) | OTHER_CLASSES, f"Luna classes drifted: {exports}"
    value_exports = set(re.findall(r'module\.add\("([^\"]+)"', mod))
    assert value_exports == set(UNIT_CONSTANTS) | OTHER_EXPORTS, f"Luna values drifted: {value_exports}"
    units = dict(re.findall(r'create_unit!\((\w+),\s*"([^"]+)"\)', unit))
    assert units == UNIT_CLASSES, f"Luna unit classes drifted: {units}"
    for name in PRELUDE:
        assert f'{name} = ValveState.{"Open" if name == "OPEN" else "Closed"};' in flight, (
            f"Missing injected {name} in flight's Python prelude"
        )
    states = re.search(r"pub enum ValveState\s*\{(.*?)^\}", gui, re.MULTILINE | re.DOTALL)
    assert states, "Cannot locate Luna ValveState enum"
    found_states = set(re.findall(r"^\s{4}(\w+),\s*$", states.group(1), re.MULTILINE))
    assert found_states == VALVE_STATES, f"Luna valve states drifted: {found_states}"
    print("Luna Python API contract matches upstream bindings and flight prelude.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check_luna_contract.py /path/to/luna-main")
    check(Path(sys.argv[1]))
