# YJSP Sequence Tester

A public, no-login sequence checker for [Luna](https://github.com/gt-space/luna) Python scripts. All user code is analyzed and simulated in the visitor's browser; the server only hosts static files.

## Features (MVP layers 1–4)

1. Python syntax and indentation checks through Python's parser.
2. Undefined-name checks, including missing `import time` and typos in script variables.
3. Luna API and mapping checks for exported names, valve/sensor constructors, and their methods.
4. Browser-only simulated execution, virtual time, mock sensors, valve commands, exceptions, and an event trace.

**Not implemented:** behavioral assertions (layer 5), fault injection (layer 6), accurate hardware behavior, hardware-confirmed abort stages, or physical SAM testing. Passing these checks does not demonstrate that a sequence is safe to run on hardware.

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
node --check src/worker.js
node --test tests/test_environment.mjs
```

GitHub Actions runs these checks on every push and PR. A push to `main` deploys the static site through GitHub Pages once Pages is enabled for the repository.

## Test Environment

Operators configure valves and sensor profiles in the Test Environment tab. Luna injects names from flight mappings, so these names must be declared independently of the sequence to catch undefined devices and invalid method calls. The site ships with illustrative names only.

- Add valves by name and choose their **initial simulation state** (`OPEN` or `CLOSED`). This is not the physical normally-open/normally-closed polarity in Luna's SAM mappings.
- Add sensors by name and unit, then edit timestamped readings. The graph previews the profile. Choose **Step / hold** (default) or **Linear** interpolation.
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

## Compatibility and limitations

The supported sequence API is modeled after `common/src/sequence/{mod,func,device,unit}.rs` and the Python prelude in `flight2/src/sequence.rs` from Luna. All common exports, `OPEN`/`CLOSED`, and mapped names are available without explicit imports.

- `wait_for`, `wait_until`, `interval`, and `time.sleep()` advance virtual time. `wait_until()` returns normally on timeout, matching Luna; a timeout trace event is shown.
- Actuation and abort functions record *requested commands* only. `set_abort_stage()` does not test real revision/acknowledgment logic.
- Modules other than the selected set (`common`, `time`, and `math`) are not supported in simulation, even if valid in Luna. Syntax/name validation can still run on them.
- No assertion is made about physical response, real sensor reliability, board synchronization, or failure-handling correctness.
- Browser Python runs in a Web Worker with a time limit and restricted imports. This is intended for a public, credential-free static origin; it is not a general-purpose secure Python sandbox.
- Source and mapping JSON stay in the visitor's `localStorage` and are not uploaded. Downloaded files are generated locally.

When Luna's binding surface changes, update the simulator and regression tests together. A generated compatibility manifest and runtime contract tests against Luna should be added before relying on this in a formal qualification workflow.
