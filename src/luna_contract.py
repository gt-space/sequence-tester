"""Python surface exported by Luna's Rust/PyO3 `common` sequence module.

This contract is checked against gt-space/luna main in CI by
scripts/check_luna_contract.py. It does not describe physical SAM behavior.
"""

FUNCTIONS = {
    "wait_for": (("duration", "Duration"),),
    "wait_until": (("condition", "&PyAny"), ("timeout", "Option<Duration>"),
                   ("poll_interval", "Option<Duration>")),
    "interval": (("count", "i64"), ("period", "Duration")),
    "create_abort_stage": (("stage_name", "String"), ("abort_condition", "String"),
                           ("safe_valve_states", "&PyDict")),
    "set_abort_stage": (("stage_name", "String"),),
    "curr_abort_stage": (),
    "curr_abort_condition": (),
    "aborted_in_this_stage": (),
    "abort": (),
    "clear_abort_status": (),
    "send_reco_launch": (),
    "reco_init_ekf": (),
    "read_umbilical_voltage": (),
    "reco_recvd_launch": (),
    "launch_lug_arm": (("sam_hostname", "String"), ("should_enable", "bool")),
    "launch_lug_detonate": (("sam_hostname", "String"), ("should_enable", "bool")),
    "sam_camera_toggle": (("should_enable", "bool"),),
    "set_servo_disconnect_abort": (("enabled", "bool"),),
}

# Only functions inside #[pymethods] are callable from Python. In particular,
# Valve.get_name() is a Rust helper, NOT a Python method.
METHODS = {
    "Valve": {
        "open": (), "close": (), "actuate": (("open", "bool"),),
        "is_open": (), "is_closed": (),
    },
    "Sensor": {"read": ()},
}

CONSTRUCTORS = {
    "Valve": (("name", "String"),),
    "Sensor": (("name", "String"),),
    "Current": (("raw", "f64"),),
    "Duration": (("raw", "f64"),),
    "ElectricPotential": (("raw", "f64"),),
    "Force": (("raw", "f64"),),
    "Pressure": (("raw", "f64"),),
    "Temperature": (("raw", "f64"),),
}

UNIT_CLASSES = {
    "Current": "A", "Duration": "s", "ElectricPotential": "V",
    "Force": "lbf", "Pressure": "psi", "Temperature": "K",
}
UNIT_CONSTANTS = {
    "A": "A", "mA": "A", "s": "s", "ms": "s", "us": "s",
    "V": "V", "mV": "V", "lbf": "lbf", "psi": "psi", "K": "K",
}
OTHER_CLASSES = {"ValveState", "ValveSafeState", "IntervalIterator"}
OTHER_EXPORTS = {"__layout_fingerprint__"}
PRELUDE = {"OPEN", "CLOSED"}  # Injected by flight2/src/sequence.rs.
VALVE_STATES = {"Undetermined", "Disconnected", "Open", "Closed", "Fault"}

COMMON_EXPORTS = (set(FUNCTIONS) | set(CONSTRUCTORS) | set(UNIT_CONSTANTS) |
                  OTHER_CLASSES | OTHER_EXPORTS)
API = COMMON_EXPORTS | PRELUDE
