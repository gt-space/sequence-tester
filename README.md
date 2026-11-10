# YJSP Sequence Tester

A public, no-login sequence checker for [Luna](https://github.com/gt-space/luna) Python scripts. All user code is analyzed and simulated in the visitor's browser; the server only hosts static files.

## Features

1. Python syntax and indentation checks through Python's parser.
2. Undefined-name checks, including missing `import time` and typos in script variables.
3. Luna API validation for actual exported functions, argument counts/types, keyword arguments, units, mapped device methods, and abort safe-state tuples.
4. Abort-stage validation and simulated execution: the active condition is evaluated against test sensor profiles on a 10-ms virtual cadence; an abort ends the sequence and schedules configured safe-state commands using their millisecond delays.
5. Explicit simulation-coverage warnings for abort conditions never triggered and stages never activated.
6. Browser-only simulated execution with a **continuous clock (5× default)**, mock sensors, valve commands, exceptions, and an event trace. The deterministic clock remains available internally for automated tests.
7. Valve-driven sensors with complete valve-state truth tables, linear rates, and optional bounds for feedback control loops.
8. Synchronized valve-state, sensor, and abort-stage plots, with up to four pinned time cursors and per-trace readouts.
9. Click a valve transition, abort marker, safe-state transition, sensor source-link, or trace event to highlight the originating Python line.

**Not implemented:** valve fault injection, hardware feedback simulation, real asynchronous FC/SAM communication, hardware-confirmed abort stages, or physical SAM testing. Passing these checks does not demonstrate that a sequence is safe to run on hardware.

## Run locally

```sh
python3 -m http.server 8000
```

Open `http://localhost:8000`. The deployed site serves [Pyodide](https://pyodide.org/) locally, while local development needs a copy of Pyodide under `src/pyodide/` (`npm install --no-save --prefix /tmp/sequence-pyodide pyodide@314.0.7` then copy the package). Python executes in a Web Worker. The wall-clock watchdog accounts for the selected simulated-time limit and acceleration (with a 15-second cushion); deterministic mode has a 15-second watchdog for stuck loops. Initial loading is allowed more time.

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
- Add sensors by name and unit. **Time profile** sensors accept timestamped readings with **Step / hold** (default) or **Linear** interpolation.
- Change the sensor behavior to **Valve-driven** for feedback simulation. Select 1–4 influencing logical valve names and enter an explicit rate (in sensor units per second) for *every* OPEN/CLOSED combination; zero is a valid rate but a blank row is not. Enter the initial reading and optional lower/upper limits. A missing or invalid row prevents simulation.
- Use **Export env ↓** in the Test Environment tab to download a reusable `test-environment.json` file, including valve initial states, sensor profiles, and all truth-table entries. **Import env ↑** restores it later or on another computer. Export works for incomplete configurations, so partially filled tables can be saved as drafts. Import replaces the current environment, but leaves `sequence.py` untouched. Invalid files are rejected without replacing the current environment.
- Switch between sequence and environment tabs or show both in split view. Both editors expand vertically with their content, using the browser page for vertical scrolling rather than separate editor scrollbars. Long unwrapped Python lines and wide truth tables can still scroll horizontally. The generated JSON is internal and not edited directly.

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

## Abort-stage simulation

After **Run simulation**, the result contains synchronized valve-command and sensor-profile plots, plus an abort-stage timeline when the script defines stages. Hovering a plot synchronizes the time cursor and shows every mapped trace's value, active abort stage, and abort status. Clicking an empty part of a plot pins a cursor; up to four can be compared side by side and removed individually. Clicking a valve transition, abort marker, stage card, or event-log line link jumps to the source line that issued/defined it. Sensor track links jump to their recorded `.read()` or abort-condition lines; clicking a line in the editor highlights associated events. The detailed event log is collapsible.

Abort stages behave as a **virtualized FC model**, not a hardware-verified safety mechanism. `create_abort_stage(name, condition, {valve: (CLOSED, integer_ms)})` registers a stage. `set_abort_stage(name)` activates the condition; when it becomes true, the simulator records an ABORT event, terminates the operator sequence, and schedules the requested safe-state commands by delay. The evaluator has only the separately injected Luna mapping/API symbols, like the real FC abort subprocess, not the main Python script's local variables. Stages that were active but did not trigger show **ABORT CONDITION NEVER TRIGGERED**, a coverage warning rather than a failure. Stages that were never selected get a different warning.

## Valve-driven sensors
For example, a pressure sensor affected by `CISO` and `CMV` can use a complete four-row truth table:

```json
{
  "name": "CTPT", "unit": "psi", "mode": "valve", "initial": 200,
  "valves": ["CISO", "CMV"],
  "rates": { "00": 0, "01": -25, "10": 40, "11": 0 },
  "min": 0, "max": 500
}
```

Each bit is the corresponding valve in the listed order: `0` means CLOSED, `1` means OPEN. The value is a signed rate in `psi/s`. The current valve-state combination selects the rate; the reading evolves continuously from its last value. Changing a valve switches rates without resetting the sensor. The generated sensor trace includes state-change breakpoints and limit crossings so the plotted line and pinned-cursor readouts follow simulated values. The **Valve-driven CTPT** and **Vespula prePress** examples demonstrate feedback behavior with illustrative rates, not measured tank performance.

## Simulation clock

Simulation runs with a continuous clock. The speed and duration limit are set in the tester's run controls; **nothing is added to `sequence.py`**. The exact same Python code can be pasted into Luna or tested here.

- **Continuous clock** advances simulated time with the actual elapsed wall clock. Only **1× and 5×** are supported to limit scheduling jitter from aggressive acceleration; 5× is the default. At 5×, a 10-second Luna wait takes approximately 2 seconds to simulate. Sensor reads, valve transitions, `time.time()`, `time.monotonic()`, `time.perf_counter()`, `time.sleep()`, `wait_for()`, `wait_until()`, and `interval()` share this clock. A busy-polling loop such as `while CTPT.read() < 300 * psi: pass` sees pressure rise based on configured valve rates without an artificial wait inserted into the user's source.
- **Limit** caps simulated duration (default 600 seconds, configurable from 1 to 3600). When a sensor condition cannot complete before the limit, the runtime reports an error, including the last sensor reading and its active valve-state truth-table rate when available. An additional main-thread watchdog terminates a worker that never returns, even if it calls no simulated API.

The output shows simulated seconds, wall-clock seconds, target speed, measured effective speed, and wait overshoot. These are simulator timing diagnostics, not a measurement of Luna's real hardware scheduler or control-loop response time. Browser scheduling and Pyodide execution can introduce jitter, especially at high acceleration.

During simulation, a rocket-themed circular activity indicator spins until the run finishes or stops, then becomes a static green or red ring. The live T+ clock and elapsed wall time remain visible throughout the run. No completion percentage is estimated for sequences with sensor-driven loops of unknown duration.

The Python engine retains a deterministic clock for automated regression tests. It is intentionally not selectable in the website because a Luna sequence with a tight sensor-polling loop can stall when time only advances on explicit waits.

## Simulation output

After **Run simulation**, the result contains two aligned plots: requested valve states and sensor readings (including valve-driven responses). Hovering either plot synchronizes the time cursor and shows every mapped trace's value; valve-driven readouts also show the active truth-table combination and its rate. Clicking an empty part of a plot pins a cursor; up to four can be compared side by side and removed individually. Clicking a valve transition or the event-log line link jumps to the source line that issued it. Sensor track links jump to their recorded `.read()` lines; clicking a line in the editor highlights associated valve transitions on the plot. The detailed event log is collapsible.

When the sequence defines abort stages, a synchronized abort-stage plot also shows activation, triggering, and safing delays. Clicking an abort marker or stage card jumps to the associated source line; abort-condition sensor reads are linked to their definition lines.

Time profiles are **inputs** independent of commands. Valve-driven readings respond to *commanded* valve states using user-entered rates, not a physical fluid model or feedback from real actuators. A graph that looks plausible is not physical verification or validation of control performance. A feedback loop without a readable sensor or time call may still stall until the wall-clock watchdog, even in continuous mode.

## Compatibility and limitations

The supported sequence API is modeled after `common/src/sequence/{mod,func,device,unit}.rs` and the Python prelude in `flight2/src/sequence.rs` from Luna. All common exports, `OPEN`/`CLOSED`, and mapped names are available without explicit imports.

- `wait_for`, `wait_until`, `interval`, and `time.sleep()` advance time while the continuous clock also progresses between calls. `wait_until()` returns normally on its own timeout, matching Luna, but the tester flags a warning and shows a timeout trace event so the operator sees that the condition never became true. The separate global simulated-time limit is a test error.
- Actuation and abort functions record *requested commands* only. `set_abort_stage()` does not test real revision/acknowledgment logic or physical valve movement. Safe-state actions use the operator's desired OPEN/CLOSED state, without board-level electrical polarity modeling.
- Modules other than the selected set (`common`, `time`, and `math`) are not supported in simulation, even if valid in Luna. Syntax/name validation can still run on them.
- No assertion is made about physical response, real sensor reliability, board synchronization, or failure-handling correctness.
- Browser Python runs in a Web Worker with a time limit and restricted imports. This is intended for a public, credential-free static origin; it is not a general-purpose secure Python sandbox.
- Source and mapping JSON stay in the visitor's `localStorage` and are not uploaded. Downloaded files are generated locally.

When Luna's binding surface changes, the daily contract check fails until `src/luna_contract.py`, the validator, simulator, and regression tests have been reviewed and updated together. This is API-surface synchronization, not certification of the flight software's internal semantics.
