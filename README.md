# YJSP Sequence Tester

A public, no-login sequence checker for [Luna](https://github.com/gt-space/luna) Python scripts. All user code is analyzed and simulated in the visitor's browser; the server only hosts static files.

## Features

1. Python syntax and indentation checks through Python's parser.
2. Undefined-name checks, including missing `import time` and typos in script variables.
3. Luna API validation for actual exported functions, argument counts/types, keyword arguments, units, mapped device methods, and abort safe-state tuples.
4. Abort-stage validation and simulated execution: the active condition is evaluated against test sensor profiles on a 10-ms virtual cadence; an abort ends the sequence and schedules configured safe-state commands using their millisecond delays.
5. Explicit simulation-coverage warnings for abort conditions never triggered and stages never activated.
6. Browser-only simulated execution, virtual time, mock sensors, valve commands, exceptions, and an event trace.
7. Synchronized valve-state, sensor-profile, and abort-stage plots, with up to four pinned time cursors and per-trace readouts.
8. Click an abort marker, safe-state transition, sensor source-link, or trace event to highlight the relevant Python line.

**Not implemented:** valve fault injection, hardware feedback simulation, real asynchronous FC/SAM communication, hardware-confirmed abort stages, or physical SAM testing. Passing these checks does not demonstrate that a sequence is safe to run on hardware.

## Run locally

```sh
python3 -m http.server 8000
```

Open `http://localhost:8000`. The deployed site serves [Pyodide](https://pyodide.org/) locally, while local development needs a copy of Pyodide under `src/pyodide/` (`npm install --no-save --prefix /tmp/sequence-pyodide pyodide@314.0.7` then copy the package). Python executes in a Web Worker. A stuck worker is terminated after five seconds of execution (initial loading is allowed more time).

## Test

```sh
python3 -m unittest discover -s tests -v
node --check src/app.js
node --check src/environment.js
node --check src/timeline.js
node --check src/worker.js
node --test tests/test_environment.mjs tests/test_timeline.mjs tests/test_timeline_ui.mjs tests/test_examples.mjs
python3 scripts/check_luna_contract.py /path/to/luna-main
```

GitHub Actions runs these checks on every push and PR, and daily. CI checks out **Luna's current `main`** and fails if the Rust/PyO3 exports, public function/method signatures, quantity definitions, valve-state enum, or FC Python prelude diverge from `src/luna_contract.py`. This intentionally blocks an unnoticed API change; semantic changes may still require manual review and simulator updates. A push to `main` deploys the static site through GitHub Pages once Pages is enabled for the repository.

## Test Environment

Operators configure valves and sensor profiles in the Test Environment tab. Luna injects names from flight mappings, so these names must be declared independently of the sequence to catch undefined devices and invalid method calls. The site ships with illustrative names only.

- Add valves in a compact table and choose their **initial simulation state** (`OPEN` or `CLOSED`). This is not the physical normally-open/normally-closed polarity in Luna's SAM mappings.
- Add sensors by name and unit. Sensor cards show a compact waveform preview and expand to edit timestamped readings. Choose **Step / hold** (default) or **Linear** interpolation.
- Switch between sequence and environment tabs or show both in split view. The generated JSON is internal and not edited directly.

The stored configuration has this format (legacy valve-name strings remain supported):

```json
{
  "valves": [
    { "name": "press_valve", "initial": "CLOSED" },
    { "name": "vent_valve", "initial": "OPEN" }
  ],
  "sensors": [
    {
      "name": "tank_pt",
      "unit": "psi",
      "interpolation": "step",
      "samples": [
        { "at": 0, "value": 0 },
        { "at": 2, "value": 220 },
        { "at": 3, "value": 310 }
      ]
    }
  ]
}
```

Step profiles hold the most recent sample at or before virtual time `t`; linear profiles interpolate between adjacent samples. No physical tank or valve model is assumed. Supported sensor units: `unknown`, `psi`, `V`, `A`, `lbf`, `K`.

## Example sequences and provenance

- **Two abort stages** adapts the `GROUND` sensor threshold in [Abort Behaviors](https://app.notion.com/p/34327990d78e803d91a1ef9273efd024) and `FILLING` abort-stage configuration in [Abort Stages Usage](https://app.notion.com/p/29827990d78e801e9d40ce4b89f3f6e8). It deliberately changes stage mid-sequence and supplies profiles that trigger the second condition; the thresholds and mappings are **demonstration inputs, not operational limits**.
- **Vespula abort (archived)** is an excerpt adapted from the historical abort script in [Launch Sequences (Vespula)](https://app.notion.com/p/2ab27990d78e8066bacdc26077843981). It demonstrates source-linked valve commands and timing; it is **not a complete or approved live abort procedure**.
- The `create_abort_stage()` examples use integer **milliseconds** for safe-state timers, per Luna's current Rust API. The older [Notion usage guide](https://app.notion.com/p/29827990d78e801e9d40ce4b89f3f6e8) describes those timers in seconds, so its example `5` would mean 5 ms, **not** 5 seconds, in current Luna. The `5000` in the adapted example means 5 seconds.
- The older [Abort Behaviors](https://app.notion.com/p/34327990d78e803d91a1ef9273efd024) documentation calls `set_servo_disconnect_monitoring(False)`; that function is **not** exported by Luna's current `common` module. The exposed name is `set_servo_disconnect_abort(False)`. Historical scripts must be validated against the current API before use.
- An ordinary Python script that issues manual valve commands is distinct from a configured abort stage monitored automatically by the FC. The tester models their command traces, but does not prove that either is safe on real hardware.

## Simulation output

After **Run simulation**, the result contains synchronized valve-command and sensor-profile plots, plus an abort-stage timeline when the script defines stages. Hovering a plot synchronizes the time cursor and shows every mapped trace's value, active abort stage, and abort status. Clicking an empty part of a plot pins a cursor; up to four can be compared side by side and removed individually. Clicking a valve transition, abort marker, stage card, or event-log line link jumps to the source line that issued/defined it. Sensor track links jump to their recorded `.read()` or abort-condition lines; clicking a line in the editor highlights associated events. The detailed event log is collapsible.

Abort stages behave as a **virtualized FC model**, not a hardware-verified safety mechanism. `create_abort_stage(name, condition, {valve: (CLOSED, integer_ms)})` registers a stage. `set_abort_stage(name)` activates the condition; when it becomes true, the simulator records an ABORT event, terminates the operator sequence, and schedules the requested safe-state commands by delay. The evaluator has only the separately injected Luna mapping/API symbols, like the real FC abort subprocess, not the main Python script's local variables. Stages that were active but did not trigger show **ABORT CONDITION NEVER TRIGGERED**, a coverage warning rather than a failure. Stages that were never selected get a different warning.

The sensor profiles are **inputs**, not calculated responses to valve actuation. A graph that looks plausible is not physical verification or validation of control performance.

## Compatibility and limitations

The supported sequence API is modeled after `common/src/sequence/{mod,func,device,unit}.rs` and the Python prelude in `flight2/src/sequence.rs` from Luna. All common exports, `OPEN`/`CLOSED`, and mapped names are available without explicit imports.

- `wait_for`, `wait_until`, `interval`, and `time.sleep()` advance virtual time. `wait_until()` returns normally on timeout, matching Luna; a timeout trace event is shown.
- Actuation and abort functions record *requested commands* only. `set_abort_stage()` does not test real revision/acknowledgment logic or physical valve movement. Safe-state actions use the operator's desired OPEN/CLOSED state, without board-level electrical polarity modeling.
- Modules other than the selected set (`common`, `time`, and `math`) are not supported in simulation, even if valid in Luna. Syntax/name validation can still run on them.
- No assertion is made about physical response, real sensor reliability, board synchronization, or failure-handling correctness.
- Browser Python runs in a Web Worker with a time limit and restricted imports. This is intended for a public, credential-free static origin; it is not a general-purpose secure Python sandbox.
- Source and mapping JSON stay in the visitor's `localStorage` and are not uploaded. Downloaded files are generated locally.

When Luna's binding surface changes, the daily contract check fails until `src/luna_contract.py`, the validator, simulator, and regression tests have been reviewed and updated together. This is API-surface synchronization, not certification of the flight software's internal semantics.
