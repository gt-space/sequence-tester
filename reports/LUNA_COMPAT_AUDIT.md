# Independent Luna compatibility audit

Status: IN PROGRESS; no certification or physical-system safety claim.

## Authority and constraints

- Initial tester HEAD and fetched feature ref: `35eb351263c187689dae60a7f2b0f9fa4704291a`.
- Fetched Luna `origin/main`: `cf33309b2cf02e78fff18668dfca2f74ec77bd5f` (local main is behind; not used).
- Both working trees initially clean. Only remote refs fetched in Luna; source unchanged.
- Disposable upstream archive: `/tmp/luna-audit-upstream`, made with `git archive origin/main`.
- No production requests, FC IPC, live processes, hardware, other repositories, merge or main edits authorized or attempted.
- PR: https://github.com/gt-space/sequence-tester/pull/4 . `gh` absent locally.

## Evidence log

- `git fetch origin` in both repositories; `git status --short --branch`; `git rev-parse` authority refs.
- `git diff origin/main...HEAD --stat` reviewed tester change scope.
- Read upstream Sensor read/richcmp and entire quantity macro and Measurement conversion.
- Existing contract checker only identifies operand order text; compiled Python reflected behavior requires independent evidence.
- Both supplied Notion pages accessible through connected Notion fetch; archived temporarily for extraction. Vespula page last edited 2026-09-30. Historical launch V1 contains syntax error and lower-case boolean names; do not repair before testing.
- `python` and `gh` commands unavailable; use `python3` and connected GitHub/read-only HTTP as needed.

## Outstanding work

Compiled isolated binding harness, full parity matrix, production path review, scripts/CI mutations, source portability, regressions, browser checks, fixes and push remain in progress.

## Recovery checkpoint: independently established results

- Built extracted Rust/PyO3 0.21.2 harness in `/tmp/luna-binding-audit`. Exact upstream `unit.rs` (including Measurement IntoPy), Sensor `__richcmp__`, wait_for/wait_until, and interval are compiled; sensor read supplies synthetic values. NOT a build of the complete production common module; FC synchronization/deserialization/error propagation and IPC are not exercised.
- Matrix before/after saved in binding-comparisons-{before,after}.json. 360 comparisons across 0/299/300/301/400, psi/unknown/V, six operators, sensor/threshold on either side and explicit read on either side. 22 real mismatches before, zero after in these 360 cases. Additional 120 synthetic missing-sensor rows do NOT test production errors and are excluded from parity claims.
- `FTPT.read() > 300*psi` matches normal quantity ordering for all five values. Direct Sensor comparisons reverse ordering; Python reflected comparisons also reach Sensor when quantity returns NotImplemented.
- Compiled timing code: wait_for(Duration(0)) works; wait_for(500), wait_for() raise TypeError. wait_until(lambda: True, Duration(0)) works. Omitted timeout panics on this host (`Instant + Duration::MAX` overflow); tester now warns and marks partial. Original source unchanged.
- Added regression cases before fixes: initial seven cases yielded 10 failing subcases and 4 errors. Fixes cover reflected comparisons, runtime keyword names, dynamic unpacking partial status, unknown float readings, incompatible-unit equality, numeric string conversion, source portability warnings, constructors without access, quantity mutation, unreachable invalid branches, and optional-timeout limitation.
- Initial Python: 71/71; initial JS: 28/28. Current checkpoint: Python 85/85; JS 29/29; all src JS syntax checks pass. Browser existing regression passed (1/1) before latest changes; must rerun after final changes.
- Browser dependencies installed only in `/tmp/sequence-browser`; missing libnspr4/libnss3 downloaded/extracted under `/tmp/luna-browser-libs`, no system package install. Use LD_LIBRARY_PATH for browser.
- Source fingerprint added to generated manifest because signature-only checks miss scale/body changes. Fingerprints conservatively require review even for nonsemantic changes.
