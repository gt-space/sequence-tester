"""Generate the tester's Python API contract directly from Luna (read-only).

This intentionally extracts the supported PyO3 surface, not flight/SAM behavior.
Run: python scripts/generate_luna_contract.py /path/to/luna --write
The bot opens a reviewable PR; it never auto-merges behavioral changes.
"""
import argparse
import pprint
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_luna_contract import signature_args, public_pyo3_methods  # noqa: E402


def impl_block(source, cls):
    match = re.search(r"#\[pymethods\]\s*impl\s+" + re.escape(cls) +
                      r"\s*\{(.*?)^\}", source, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"Missing PyO3 impl for {cls}")
    return match.group(1)


def comparison_order(device_source):
    block = impl_block(device_source, "Sensor")
    if "other.rich_compare(self.read()?, op)?" in block:
        return "reversed"
    if "self.read()?.rich_compare(other, op)?" in block:
        return "normal"
    raise ValueError("Unrecognized Luna Sensor.__richcmp__; review behavioral compatibility")


def extract(repo):
    seq = repo / "common" / "src" / "sequence"
    mod = (seq / "mod.rs").read_text()
    func = (seq / "func.rs").read_text()
    device = (seq / "device.rs").read_text()
    unit = (seq / "unit.rs").read_text()
    gui = (repo / "common" / "src" / "comm" / "gui.rs").read_text()
    flight = (repo / "flight2" / "src" / "sequence.rs").read_text()

    exported = set(re.findall(r"wrap_pyfunction!\((\w+),\s*module\)", mod))
    declared = set(re.findall(r"#\[pyfunction\]\s*pub\s+fn\s+(\w+)\s*\(", func))
    if not exported or exported != declared:
        raise ValueError(f"Unrecognized PyO3 function exports: module={exported}, func={declared}")
    functions = {name: signature_args(func, name) for name in sorted(exported)}

    methods = {}
    constructors = {}
    for cls in ("Valve", "Sensor"):
        block = impl_block(device, cls)
        exposed = public_pyo3_methods(device, cls)
        if "new" not in exposed:
            raise ValueError(f"No PyO3 constructor for {cls}")
        constructors[cls] = signature_args(block, "new")
        methods[cls] = {name: signature_args(block, name) for name in sorted(exposed - {"new"})}

    units = dict(re.findall(r'create_unit!\((\w+),\s*"([^"]+)"\)', unit))
    if not units:
        raise ValueError("No unit definitions found")
    unit_new = signature_args(unit, "new")
    constructors.update({name: unit_new for name in units})

    classes = set(re.findall(r"module\.add_class::<(\w+)>\(\)\?", mod))
    if not set(constructors) <= classes:
        raise ValueError("Luna no longer exports required unit or mapping classes")
    unit_values = re.findall(
        r'module\.add\("([^"]+)",\s*Py::new\(py,\s*(\w+)::new\(', mod
    )
    constants = {}
    for name, cls in unit_values:
        if cls not in units:
            raise ValueError(f"Unknown unit constant {name} with class {cls}")
        constants[name] = units[cls]
    values = set(re.findall(r'module\.add\("([^"]+)"', mod))
    if not constants or not values:
        raise ValueError("Unable to extract Luna's exported values")
    states_match = re.search(r"pub enum ValveState\s*\{(.*?)^\}", gui,
                             re.MULTILINE | re.DOTALL)
    if not states_match:
        raise ValueError("Cannot locate Luna ValveState enum")
    states = set(re.findall(r"^\s{4}(\w+),\s*$", states_match.group(1), re.MULTILINE))
    if not states:
        raise ValueError("No valve states found")
    prelude = {}
    for name, state in (("OPEN", "Open"), ("CLOSED", "Closed")):
        if f"{name} = ValveState.{state};" in flight:
            prelude[name] = state
        else:
            raise ValueError(f"Unrecognized Flight2 mapping prelude for {name}")
    return {
        "FUNCTIONS": functions,
        "METHODS": methods,
        "CONSTRUCTORS": constructors,
        "UNIT_CLASSES": units,
        "UNIT_CONSTANTS": constants,
        "OTHER_CLASSES": classes - set(constructors),
        "OTHER_EXPORTS": values - set(constants),
        "PRELUDE": set(prelude),
        "VALVE_STATES": states,
        "SENSOR_COMPARISON_ORDER": comparison_order(device),
    }


def render(contract):
    parts = ['"""Generated Luna Python API surface. DO NOT EDIT BY HAND.\n\n'
             'Run scripts/generate_luna_contract.py against a Luna checkout.\n'
             'Changes require simulator/test review before merge.\n"""\n']
    for key in ("FUNCTIONS", "METHODS", "CONSTRUCTORS", "UNIT_CLASSES",
                "UNIT_CONSTANTS", "OTHER_CLASSES", "OTHER_EXPORTS",
                "PRELUDE", "VALVE_STATES", "SENSOR_COMPARISON_ORDER"):
        value = contract[key]
        if isinstance(value, set):
            rendered = "set()" if not value else "{" + ", ".join(repr(x) for x in sorted(value)) + "}"
        else:
            rendered = pprint.pformat(value, sort_dicts=True, width=105)
        parts.append(f"{key} = {rendered}\n")
    parts.append(
        "\nCOMMON_EXPORTS = (set(FUNCTIONS) | set(CONSTRUCTORS) | set(UNIT_CONSTANTS) |\n"
        "                  OTHER_CLASSES | OTHER_EXPORTS)\n"
        "API = COMMON_EXPORTS | PRELUDE\n"
    )
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("luna", type=Path)
    parser.add_argument("--write", action="store_true", help="Regenerate src/luna_contract.py")
    args = parser.parse_args()
    contract = extract(args.luna)
    target = ROOT / "src" / "luna_contract.py"
    if args.write:
        target.write_text(render(contract))
        print(f"Updated {target}")
    else:
        sys.path.insert(0, str(ROOT / "src"))
        import luna_contract as current
        changed = [key for key, val in contract.items() if getattr(current, key, None) != val]
        if changed:
            raise SystemExit(f"Luna API changed in: {', '.join(changed)}. Generate a reviewed tester update.")
        print("Generated Luna API contract matches committed tester contract.")


if __name__ == "__main__":
    main()
