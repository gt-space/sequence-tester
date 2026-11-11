import { highlightPython } from "./highlight.js";
import { createEnvironmentEditor, parseEnvironmentFile, serializeEnvironmentFile } from "./environment.js";
import { createTimelineView } from "./timeline.js";
import { normalizeSequenceName, sequenceFileName, environmentFileName } from "./filename.js";
import { listSavedSequences, saveSequence, deleteSavedSequence } from "./saved-sequences.js";

const EXAMPLES = {
  vespula: "# tank pre press sequence\nimport time\nprint('Pre Press Sequence has begun')\n\n# define pressure variables\nftpt_target = 416*psi # psia, target fuel tank pressure\notpt_target = 357*psi # psia, target lox tank pressure\nupRan = 2*psi # psi, upper range bound for bang bang algorithm\nlowRan = 3*psi # psi, lower range bound for bang bang algorithm\n\n# time variables\npress_time = 20 # s, sequence duration\nwait_timing = 5 # ms\n\n# confirm switch closed\nFSWV.close()\nOSWV.close()\nwait_for(wait_timing*ms)\n\n# initialize valve state variables\nFBB.close()\nFBBopen = False # hardcoded for consistency\nOBB.close()\nOBBopen = False # hardcoded due to feedback issues on sam-21\n\nstart_time = time.time() # s, current time\n\n# press tanks with bang bang algorithm\nwhile time.time() < start_time + press_time:\n\t# check pressures\n\tcurrFTPT = FTPT.read()\n\tcurrOTPT = OTPT.read()\n\t# bang bang algorithm\n\tif FBBopen and currFTPT > ftpt_target + upRan:\n\t\tFBB.close()\n\t\tFBBopen = False\n\telif (not FBBopen) and currFTPT < ftpt_target - lowRan:\n\t\tFBB.open()\n\t\tFBBopen = True\n\tif OBBopen and currOTPT > otpt_target + upRan:\n\t\tOBB.close()\n\t\tOBBopen = False\n\telif (not OBBopen) and currOTPT < otpt_target - lowRan:\n\t\tOBB.open()\n\t\tOBBopen = True\n\twait_for(wait_timing*ms)\n\nOBB.close()\nFBB.close()\n\nprint('Pre Press Sequence has ended')",
  tank: `press_valve.open()\nwait_until(lambda: tank_pt.read() >= 300 * psi, 5 * s)\npress_valve.close()\nprint("Tank press sequence finished")`,
  pulse: `press_valve.open()\nwait_for(500 * ms)\npress_valve.close()\nwait_for(250 * ms)\nvent_valve.open()\nwait_for(250 * ms)\nvent_valve.close()`,
  abort: `# Abort triggers when the configured tank pressure exceeds 250 psi\ncreate_abort_stage(\n    "PRESSURIZATION",\n    "tank_pt > 250*psi",\n    {press_valve: (CLOSED, 500), vent_valve: (OPEN, 1000)}\n)\nset_abort_stage("PRESSURIZATION")\npress_valve.open()\nwait_for(5*s)\nprint("Only reached if the abort condition never triggers")`,
  abort_two: `# Adapted from YJSP Notion's GROUND and FILLING examples.\n# Demonstration thresholds only; not approved operational limits.\n# Safing timers are integer MILLISECONDS in current Luna.\ncreate_abort_stage(\n    "GROUND",\n    "PT.read() > 50*psi",\n    {press_valve: (CLOSED, 0), vent_valve: (OPEN, 0)}\n)\ncreate_abort_stage(\n    "FILLING",\n    "load_cell.read() > 40*lbf",\n    {press_valve: (CLOSED, 5000), vent_valve: (OPEN, 0)}\n)\nset_abort_stage("GROUND")\nwait_for(1*s)\nset_abort_stage("FILLING")\npress_valve.open()\nwait_for(5*s)\nprint("No abort triggered")`,
  vespula_abort: `# Historical Vespula abort sequence excerpt from YJSP Notion.\n# Demonstration only; this is NOT an approved live abort procedure.\nimport time\nfmv_time = 0.06\nomv_time = 0.125\nlox_close_lead = 0.1\nlox_close_wait = omv_time + lox_close_lead - fmv_time\nwait_timing = 5  # ms\n\nOBB.close()\nFBB.close()\nOSWV.close()\nFSWV.close()\nOMV.close()\n\nstart_time = time.time()\nwhile time.time() < start_time + lox_close_wait:\n    wait_for(wait_timing*ms)\n\nFMV.close()\nOVNT.open()\nFVNT.open()\nprint("Historical abort excerpt finished")`,
  feedback: `# Idealized pressure feedback demo (not a physical tank model)\nCISO.open()\nwait_until(lambda: CTPT.read() >= 340*psi, 5*s)\nCISO.close()\nCMV.open()\nwait_until(lambda: CTPT.read() <= 250*psi, 5*s)\nCMV.close()\nprint("Pressure-control sequence complete")`,
  import: `press_valve.open()\ntime.sleep(1)\npress_valve.close()`,
  api: `tank_pt.open()\npress_valve.open()\nwait_for(500 * ms)\npress_valve.close()`
};

const DEFAULT_MAPPING = {
  valves: ["press_valve", "vent_valve"],
  sensors: [{ name: "tank_pt", unit: "psi", samples: [{ at: 0, value: 0 }, { at: 1, value: 120 }, { at: 2, value: 220 }, { at: 3, value: 315 }] }]
};

const VESPULA_MAPPING = {
  valves: ["FSWV", "OSWV", "FBB", "OBB"],
  sensors: [
    { name: "FTPT", unit: "psi", mode: "valve", initial: 400, valves: ["FBB"], rates: { "0": -2, "1": 30 }, min: 0, max: 500 },
    { name: "OTPT", unit: "psi", mode: "valve", initial: 330, valves: ["OBB"], rates: { "0": -2, "1": 30 }, min: 0, max: 500 }
  ]
};

const ABORT_TWO_MAPPING = {
  valves: ["press_valve", "vent_valve"],
  sensors: [
    { name: "PT", unit: "psi", interpolation: "linear",
      samples: [{ at: 0, value: 30 }, { at: 1, value: 40 }, { at: 3, value: 45 }] },
    { name: "load_cell", unit: "lbf", interpolation: "linear",
      samples: [{ at: 0, value: 0 }, { at: 1, value: 15 }, { at: 3, value: 50 }] }
  ]
};

const VESPULA_ABORT_MAPPING = {
  valves: [
    { name: "OBB", initial: "OPEN" }, { name: "FBB", initial: "OPEN" },
    { name: "OSWV", initial: "OPEN" }, { name: "FSWV", initial: "OPEN" },
    { name: "OMV", initial: "OPEN" }, { name: "FMV", initial: "OPEN" },
    { name: "OVNT", initial: "CLOSED" }, { name: "FVNT", initial: "CLOSED" }
  ],
  sensors: []
};

const EXAMPLE_MAPPINGS = {
  vespula: VESPULA_MAPPING,
  abort_two: ABORT_TWO_MAPPING,
  vespula_abort: VESPULA_ABORT_MAPPING
};

const FEEDBACK_MAPPING = {
  valves: ["CISO", "CMV"],
  sensors: [{ name: "CTPT", unit: "psi", mode: "valve", initial: 200,
    valves: ["CISO", "CMV"], rates: { "00": 0, "01": -25, "10": 40, "11": 0 }, min: 0, max: 500 }]
};

EXAMPLE_MAPPINGS.feedback = FEEDBACK_MAPPING;

const $ = id => document.getElementById(id);
const source = $("source");
const sequenceName = $("sequence-name");
function setSequenceName(value) {
  const name = normalizeSequenceName(value);
  sequenceName.value = name;
  $("sequence-tab-name").textContent = sequenceFileName(name);
  localStorage.setItem("yjsp-sequence-name", name);
  return name;
}
sequenceName.addEventListener("change", () => setSequenceName(sequenceName.value));
sequenceName.addEventListener("keydown", event => {
  if (event.key === "Enter") { event.preventDefault(); sequenceName.blur(); }
});
setSequenceName(localStorage.getItem("yjsp-sequence-name") ?? "sequence");
const mapping = $("mapping");
const status = $("engine-status");
let worker;
let ready = false;
let currentId = 0;
let pending = null;
let executionTimeout;
let elapsedTicker;
let startupTimeout;
let running = false;
let startupPhase = "Loading Python runtime…";
let activeSourceLine = 0;
let flightRun = null;

const clockSpeed = $("clock-speed");
const timeLimit = $("time-limit");
clockSpeed.value = ["1", "5"].includes(localStorage.getItem("yjsp-clock-speed"))
  ? localStorage.getItem("yjsp-clock-speed") : "5";
timeLimit.value = localStorage.getItem("yjsp-time-limit") ?? "600";

function updateFlight(simulated, wall, phase = "running") {
  if (!flightRun) return;
  const { limit, speed } = flightRun;
  const seconds = Math.max(0, simulated);
  const progress = $("flight-progress");
  progress.dataset.phase = phase;
  $("flight-phase").textContent = phase === "running" ? "SIMULATION IN PROGRESS" :
    phase === "complete" ? "SEQUENCE FINISHED" : "SIMULATION STOPPED";
  $("flight-elapsed").textContent = `T+ ${seconds.toFixed(1)}s`;
  $("flight-wall").textContent = `${Math.max(0, wall).toFixed(1)}s wall time · ${speed}× speed`;
  $("flight-limit").textContent = `${limit}s simulation limit`;
}

function startFlight(request) {
  flightRun = { speed: request.options.speed, limit: request.options.max_duration, started: performance.now() };
  $("flight-progress").hidden = false;
  updateFlight(0, 0);
}

function finishFlight(result) {
  if (!flightRun) return;
  const elapsed = (performance.now() - flightRun.started) / 1000;
  const simulated = typeof result?.virtual_time === "number" ? result.virtual_time : elapsed * flightRun.speed;
  updateFlight(simulated, result?.timing?.wall_seconds ?? elapsed,
    result?.checks?.runtime === "pass" ? "complete" : "stopped");
  flightRun = null;
}

function clearExecutionTimers() {
  clearTimeout(executionTimeout);
  clearInterval(elapsedTicker);
  elapsedTicker = null;
}

function updateLineFocus() {
  const indicator = $("line-focus");
  if (!activeSourceLine) { indicator.hidden = true; return; }
  const lineHeight = parseFloat(getComputedStyle(source).lineHeight) || 24.7;
  const padding = parseFloat(getComputedStyle(source).paddingTop) || 25;
  indicator.hidden = false;
  indicator.style.top = `${padding + (activeSourceLine - 1) * lineHeight - source.scrollTop}px`;
  indicator.style.height = `${lineHeight}px`;
}

function jumpToSourceLine(line, eventIndex = -1) {
  if (!line || line < 1) return;
  if (!splitView) selectTab("sequence");
  const lines = source.value.split("\n");
  if (line > lines.length) return;
  const offset = lines.slice(0, line - 1).reduce((sum, text) => sum + text.length + 1, 0);
  const lineHeight = parseFloat(getComputedStyle(source).lineHeight) || 24.7;
  const padding = parseFloat(getComputedStyle(source).paddingTop) || 25;
  source.focus({ preventScroll: true });
  source.setSelectionRange(offset, offset + lines[line - 1].length);
  source.scrollTop = 0;
  source.scrollLeft = 0;
  $("gutter").scrollTop = 0;
  $("highlight").scrollTop = 0;
  $("highlight").scrollLeft = 0;
  const lineTop = source.getBoundingClientRect().top + window.scrollY + padding + (line - 1) * lineHeight;
  window.scrollTo({ top: Math.max(0, lineTop - Math.min(180, window.innerHeight * 0.25)), behavior: "smooth" });
  activeSourceLine = line;
  updateLineFocus();
  document.querySelectorAll(".event-row").forEach(row => row.classList.toggle("is-selected", Number(row.dataset.line) === line));
  if (eventIndex >= 0) timeline.selectEvent(eventIndex);
  else timeline.highlightLine(line);
}

function sourceCursorMoved() {
  const before = source.value.slice(0, source.selectionStart);
  const line = before.split("\n").length;
  activeSourceLine = line;
  updateLineFocus();
  timeline.highlightLine(line);
  document.querySelectorAll(".event-row").forEach(row => row.classList.toggle("is-selected", Number(row.dataset.line) === line));
}

const timeline = createTimelineView({ container: $("visual-output"), onJumpToSource: jumpToSourceLine });

function setStatus(message, level = "normal") {
  status.textContent = message;
  status.dataset.level = level;
}

function makeWorker() {
  if (worker) worker.terminate();
  clearTimeout(startupTimeout);
  clearExecutionTimers();
  const workerUrl = new URL("./worker.js", import.meta.url);
  workerUrl.search = new URL(import.meta.url).search;
  worker = new Worker(workerUrl, { type: "module" });
  ready = false;
  startupPhase = "Loading Python runtime…";
  setStatus(startupPhase);
  startupTimeout = setTimeout(() => {
    setStatus(`Python startup timed out: ${startupPhase}. Try again.`, "error");
    worker.terminate();
    worker = null;
    pending = null;
  }, 45000);
  worker.onmessage = ({ data }) => {
    if (data.type === "progress") {
      startupPhase = data.message;
      setStatus(startupPhase);
    } else if (data.type === "ready") {
      clearTimeout(startupTimeout);
      ready = true;
      setStatus("Python runtime ready", "success");
      if (pending) dispatch(pending);
    } else if (data.type === "startup-error") {
      clearTimeout(startupTimeout);
      setStatus(`Runtime unavailable: ${data.message}`, "error");
      worker.terminate();
      worker = null;
    } else if (data.type === "result") {
      if (data.id !== currentId) return;
      clearExecutionTimers();
      running = false;
      pending = null;
      finishFlight(data.result);
      render(data.result);
      const issues = data.result.diagnostics || [];
      const errors = issues.filter(item => item.severity === "error").length;
      const warnings = issues.filter(item => item.severity === "warning").length;
      setStatus(errors ? `${errors} error(s) · ${warnings} warning(s)` :
        warnings ? `Check complete · ${warnings} warning(s)` : "Check complete",
      errors ? "error" : warnings ? "warning" : "success");
    } else if (data.type === "failure") {
      if (data.id !== currentId) return;
      clearExecutionTimers();
      running = false;
      pending = null;
      finishFlight(null);
      setStatus(`Execution failed: ${data.message}`, "error");
    }
  };
  worker.onerror = event => {
    clearTimeout(startupTimeout);
    clearExecutionTimers();
    finishFlight(null);
    running = false;
    setStatus(`Runtime error: ${event.message}`, "error");
    worker.terminate();
    worker = null;
  };
}

function dispatch(request) {
  pending = null;
  running = true;
  if (request.mode !== "simulate") {
    flightRun = null;
    $("flight-progress").hidden = true;
  }
  setStatus(request.mode === "simulate" ? "Simulating…" : "Validating…");
  worker.postMessage(request);
  const realtime = request.mode === "simulate" && request.options.clock_mode === "realtime";
  const wallLimit = realtime ? (request.options.max_duration / request.options.speed) * 1000 + 15000 : 15000;
  const startWall = performance.now();
  if (request.mode === "simulate") {
    startFlight(request);
    elapsedTicker = setInterval(() => {
      const elapsed = (performance.now() - startWall) / 1000;
      const time = realtime ? elapsed * request.options.speed : 0;
      updateFlight(time, elapsed);
      setStatus(realtime
        ? `Simulating ${request.options.speed}× · ~${time.toFixed(1)}s simulated / ${elapsed.toFixed(1)}s elapsed`
        : `Deterministic simulation · ${elapsed.toFixed(1)}s elapsed`);
    }, 200);
  }
  executionTimeout = setTimeout(() => {
    const seconds = wallLimit / 1000;
    render({ checks: { syntax: "pass", names: "not_run", api: "not_run", runtime: "fail" }, diagnostics: [{ stage: "runtime", severity: "error", message: `Execution exceeded the ${seconds.toFixed(1)}s wall-clock watchdog limit; check for an infinite loop or stalled condition`, line: 0 }], events: [], virtual_time: null, stdout: "" });
    finishFlight(null);
    running = false;
    makeWorker();
    setStatus(`Execution stopped after ${seconds.toFixed(1)}s. Restarting Python runtime…`, "error");
  }, wallLimit);
}

function run(mode) {
  if (source.value.length > 200000 || mapping.value.length > 100000) {
    setStatus("Sequence or configuration too large", "error");
    return;
  }
  const maxDuration = Number(timeLimit.value);
  const speed = Number(clockSpeed.value);
  if (mode === "simulate" && ![1, 5].includes(speed)) {
    setStatus("Simulation speed must be 1× or 5×", "error");
    return;
  }
  if (mode === "simulate" && (!Number.isFinite(maxDuration) || maxDuration < 1 || maxDuration > 3600)) {
    setStatus("Simulated-time limit must be between 1 and 3600 seconds", "error");
    return;
  }
  const options = { clock_mode: "realtime", speed,
    max_duration: mode === "simulate" ? maxDuration : 600 };
  const request = { id: ++currentId, mode, source: source.value, mapping: mapping.value, options };
  localStorage.setItem("yjsp-sequence-source", source.value);
  localStorage.setItem("yjsp-sequence-mapping", mapping.value);
  if (mode === "simulate") saveCurrentSequence(true);
  if (!worker) makeWorker();
  if (running) {
    makeWorker();
    pending = request;
    return;
  }
  if (ready) dispatch(request);
  else { pending = request; setStatus("Waiting for Python runtime…"); }
}

function invalidateResults() {
  currentId++;
  pending = null;
  flightRun = null;
  $("flight-progress").hidden = true;
  if (running) {
    running = false;
    makeWorker();
  }
  for (const el of document.querySelectorAll("[data-check]")) {
    el.dataset.state = "stale";
    el.querySelector(".check-icon").textContent = "↻";
    el.querySelector(".check-status").textContent = "Not checked";
  }
  $("validation-state").textContent = "MODIFIED";
  $("validation-state").dataset.state = "stale";
  $("issue-count").textContent = "—";
  $("diagnostics").className = "empty-state";
  $("diagnostics").textContent = "Not checked";
  $("virtual-time").textContent = "—";
  $("timing-details").hidden = true;
  $("timing-details").textContent = "";
  timeline.clear();
  $("trace-placeholder").hidden = false;
  $("event-details").hidden = true;
  $("event-count").textContent = "0";
  $("trace").className = "trace-empty";
  $("trace").textContent = "No simulation output";
  activeSourceLine = 0;
  updateLineFocus();
  $("stdout-box").hidden = true;
  $("stdout").textContent = "";
  if (ready) setStatus("Edited · revalidate");
}

function render(result) {
  const stages = result.checks || {};
  const failed = Object.values(stages).includes("fail");
  const hasWarnings = (result.diagnostics || []).some(item => item.severity === "warning");
  $("validation-state").textContent = failed ? "ISSUES FOUND" : hasWarnings ? "WARNINGS" : "CHECKED";
  $("validation-state").dataset.state = failed ? "fail" : hasWarnings ? "warning" : "pass";
  for (const [name, state] of Object.entries(stages)) {
    const el = document.querySelector(`[data-check="${name}"]`);
    if (!el) continue;
    el.dataset.state = state;
    el.querySelector(".check-icon").textContent = state === "pass" ? "✓" : state === "fail" ? "!" : "—";
    el.querySelector(".check-status").textContent = state === "pass" ? "Passed" : state === "fail" ? "Failed" : "Not run";
  }
  const diagnostics = result.diagnostics || [];
  $("issue-count").textContent = diagnostics.length;
  const list = $("diagnostics");
  list.replaceChildren();
  if (!diagnostics.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state good";
    empty.textContent = "No issues";
    list.append(empty);
  }
  for (const item of diagnostics) {
    const row = document.createElement("button");
    row.className = `issue ${item.severity}`;
    row.type = "button";
    const where = item.line ? `Line ${item.line} · ${item.stage}` : item.stage;
    row.innerHTML = `<span class="issue-kicker"></span><span class="issue-message"></span>`;
    row.querySelector(".issue-kicker").textContent = `${item.severity.toUpperCase()} · ${where}`;
    row.querySelector(".issue-message").textContent = item.message;
    row.onclick = () => {
      jumpToSourceLine(item.line);
    };
    list.append(row);
  }
  $("virtual-time").textContent = typeof result.virtual_time === "number" ? `${result.virtual_time.toFixed(3)} s` : "—";
  const timing = result.timing;
  const timingDetails = $("timing-details");
  timingDetails.hidden = !timing;
  timingDetails.replaceChildren();
  if (timing) {
    const pieces = [timing.mode === "realtime" ? `Continuous · ${timing.requested_speed}× target` : "Deterministic · instant advance",
      `${timing.wall_seconds.toFixed(3)}s wall time`,
      `${timing.simulated_limit_seconds}s simulation limit`];
    if (timing.mode === "realtime") {
      pieces.splice(2, 0, `${timing.actual_speed?.toFixed(2) ?? "—"}× effective`,
        `${timing.wait_count} waits · max ${(timing.max_wait_overshoot_ms / timing.requested_speed).toFixed(2)}ms wall overshoot`);
    }
    timingDetails.textContent = pieces.join("   ·   ");
  }
  if (result.simulation) timeline.load(result);
  else timeline.clear();
  $("trace-placeholder").hidden = Boolean(result.simulation);
  const trace = $("trace");
  trace.replaceChildren();
  const events = result.events || [];
  $("event-details").hidden = !events.length;
  $("event-count").textContent = String(events.length);
  if (!events.length) {
    trace.className = "trace-empty";
    trace.textContent = stages.runtime === "pass" ? "No hardware events" : "No simulation output";
  } else {
    trace.className = "event-list";
    for (const [index, event] of events.entries()) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "event-row";
      row.dataset.eventIndex = index;
      row.dataset.line = event.line || "0";
      if (event.line) {
        row.title = `View ${sequenceFileName(sequenceName.value)}:${event.line}`;
        row.onclick = () => jumpToSourceLine(event.line, index);
      } else row.disabled = true;
      const time = document.createElement("span");
      time.className = "event-time";
      time.textContent = `${Number(event.time).toFixed(3)} s`;
      const kind = document.createElement("span");
      kind.className = `event-kind ${event.kind}`;
      kind.textContent = event.kind;
      const detail = document.createElement("span");
      detail.textContent = `${event.target} · ${event.detail}`;
      row.append(time, kind, detail);
      if (event.line) row.append(Object.assign(document.createElement("span"), { className: "event-source", textContent: `L${event.line} ↗` }));
      trace.append(row);
    }
  }
  $("stdout-box").hidden = !result.stdout;
  $("stdout").textContent = result.stdout || "";
}

function updateEditor() {
  const count = source.value.split("\n").length;
  $("gutter").textContent = Array.from({ length: count }, (_, i) => String(i + 1)).join("\n");
  $("editor-info").textContent = `${count} lines · ${source.value.length} characters`;
  highlightPython(source.value, $("highlight"));
  $("highlight").scrollTop = source.scrollTop;
  $("highlight").scrollLeft = source.scrollLeft;
  localStorage.setItem("yjsp-sequence-source", source.value);
  updateLineFocus();
}

source.value = localStorage.getItem("yjsp-sequence-source") ?? EXAMPLES.tank;
const environment = createEnvironmentEditor({
  mapping,
  valveList: $("valve-list"),
  sensorList: $("sensor-list"),
  initial: localStorage.getItem("yjsp-sequence-mapping") ?? DEFAULT_MAPPING,
  fallback: DEFAULT_MAPPING,
  onChange: () => {
    localStorage.setItem("yjsp-sequence-mapping", mapping.value);
    invalidateResults();
  }
});

let activeSavedSnapshot = null;
function currentMatches(entry) {
  return entry.name === normalizeSequenceName(sequenceName.value) &&
    entry.source === source.value && entry.mapping === mapping.value;
}

function renderSavedSequences() {
  const container = $("saved-sequences");
  container.replaceChildren();
  let entries;
  try {
    entries = listSavedSequences(localStorage);
    $("saved-error").hidden = true;
  } catch (error) {
    $("saved-error").textContent = error.message;
    $("saved-error").hidden = false;
    $("saved-count").textContent = "!";
    return;
  }
  $("saved-count").textContent = String(entries.length);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Run a simulation or save a test to add it here.";
    container.append(empty);
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "saved-entry";
    const load = document.createElement("button");
    load.type = "button";
    load.className = "saved-load";
    load.title = `Load ${entry.name}.py and its environment`;
    const title = document.createElement("strong");
    title.textContent = `${entry.name}.py`;
    const date = document.createElement("small");
    date.textContent = `Saved ${new Date(entry.updatedAt).toLocaleString()}`;
    load.append(title, date);
    load.onclick = () => {
      if (!currentMatches(entry) && (!activeSavedSnapshot || !currentMatches(activeSavedSnapshot)) &&
          !window.confirm("Replace the current unsaved edits with this saved test?")) return;
      source.value = entry.source;
      setSequenceName(entry.name);
      environment.load(entry.mapping);
      updateEditor();
      invalidateResults();
      activeSavedSnapshot = entry;
      source.focus();
      source.setSelectionRange(0, 0);
      source.scrollTop = 0;
      source.scrollLeft = 0;
      setStatus(`Loaded ${entry.name}.py and its test environment`, "success");
    };
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "saved-remove";
    remove.textContent = "×";
    remove.title = `Delete ${entry.name} from this browser`;
    remove.setAttribute("aria-label", remove.title);
    remove.onclick = () => {
      if (!window.confirm(`Delete saved test ${entry.name}.py from this browser?`)) return;
      try {
        deleteSavedSequence(localStorage, entry.name);
        if (activeSavedSnapshot?.name === entry.name) activeSavedSnapshot = null;
        renderSavedSequences();
        setStatus(`Deleted saved test ${entry.name}.py`, "success");
      } catch (error) {
        $("saved-error").textContent = `Could not delete: ${error.message}`;
        $("saved-error").hidden = false;
      }
    };
    row.append(load, remove);
    container.append(row);
  }
}

function saveCurrentSequence(silent = false) {
  try {
    const entry = saveSequence(localStorage, {
      name: setSequenceName(sequenceName.value), source: source.value, mapping: mapping.value
    });
    activeSavedSnapshot = entry;
    renderSavedSequences();
    if (!silent) setStatus(`Saved ${entry.name}.py with its test environment in this browser`, "success");
    return true;
  } catch (error) {
    $("saved-error").textContent = `Could not save test: ${error.message}`;
    $("saved-error").hidden = false;
    if (!silent) setStatus(`Could not save test: ${error.message}`, "error");
    return false;
  }
}
$("save-sequence").onclick = () => saveCurrentSequence();
renderSavedSequences();
try {
  activeSavedSnapshot = listSavedSequences(localStorage).find(currentMatches) ?? null;
} catch { /* The visible error is provided by renderSavedSequences(). */ }
$("add-valve").onclick = environment.addValve;
$("add-sensor").onclick = environment.addSensor;
let currentTab = "sequence";
let splitView = false;
function updateLayout() {
  $("editor-body").dataset.view = splitView ? "split" : currentTab;
  for (const name of ["sequence", "environment"]) {
    const tab = $(`${name}-tab`);
    tab.classList.toggle("active", currentTab === name);
    tab.setAttribute("aria-selected", String(currentTab === name));
  }
  $("split-toggle").setAttribute("aria-pressed", String(splitView));
  $("split-toggle").textContent = splitView ? "▣ Single view" : "▥ Split view";
  $("source-actions").hidden = !splitView && currentTab === "environment";
  $("environment-actions").hidden = !splitView && currentTab === "sequence";
  $("editor-info").hidden = !splitView && currentTab === "environment";
  $("environment-info").hidden = splitView || currentTab !== "environment";
}
function selectTab(name) {
  currentTab = name;
  updateLayout();
  if (name === "sequence") source.focus();
  else environment.focus();
}
$("sequence-tab").onclick = () => selectTab("sequence");
$("environment-tab").onclick = () => selectTab("environment");
$("split-toggle").onclick = () => { splitView = !splitView; updateLayout(); };
updateLayout();
updateEditor();
source.addEventListener("input", () => { updateEditor(); invalidateResults(); });
source.addEventListener("scroll", () => { $("gutter").scrollTop = source.scrollTop; $("highlight").scrollTop = source.scrollTop; $("highlight").scrollLeft = source.scrollLeft; updateLineFocus(); });
source.addEventListener("click", sourceCursorMoved);
source.addEventListener("keyup", sourceCursorMoved);
source.addEventListener("keydown", event => {
  if (event.key === "Tab") {
    event.preventDefault();
    const a = source.selectionStart;
    source.setRangeText("    ", a, source.selectionEnd, "end");
    updateEditor();
    invalidateResults();
  }
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    run("simulate");
  }
});
$("validate").onclick = () => run("validate");
$("simulate").onclick = () => run("simulate");
for (const control of [clockSpeed, timeLimit]) {
  control.addEventListener("change", () => {
    localStorage.setItem("yjsp-clock-speed", clockSpeed.value);
    localStorage.setItem("yjsp-time-limit", timeLimit.value);
    invalidateResults();
  });
}
document.querySelectorAll("[data-example]").forEach(button => button.onclick = () => {
  source.value = EXAMPLES[button.dataset.example];
  setSequenceName(button.dataset.example);
  environment.load(EXAMPLE_MAPPINGS[button.dataset.example] || DEFAULT_MAPPING);
  updateEditor();
  source.focus();
  source.setSelectionRange(0, 0);
  source.scrollTop = 0;
  source.scrollLeft = 0;
  $("highlight").scrollTop = 0;
  $("highlight").scrollLeft = 0;
  $("gutter").scrollTop = 0;
});
$("upload").onclick = () => $("file-input").click();
$("file-input").onchange = async event => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (file.size > 200000) { setStatus("File too large (200 KB maximum)", "error"); return; }
  source.value = await file.text();
  setSequenceName(file.name);
  updateEditor();
  invalidateResults();
};
function downloadFile(contents, filename, mimeType) {
  const url = URL.createObjectURL(new Blob([contents], { type: mimeType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("download").onclick = () => downloadFile(source.value, sequenceFileName(setSequenceName(sequenceName.value)), "text/x-python");
$("environment-download").onclick = () => {
  downloadFile(serializeEnvironmentFile(JSON.parse(mapping.value)), environmentFileName(setSequenceName(sequenceName.value)), "application/json");
  setStatus("Test environment exported as JSON", "success");
};
$("environment-upload").onclick = () => $("environment-file-input").click();
$("environment-file-input").onchange = async event => {
  const file = event.target.files?.[0];
  event.target.value = ""; // Selecting the same file again must still trigger import.
  if (!file) return;
  if (file.size > 200000) {
    setStatus("Environment file too large (200 KB maximum)", "error");
    return;
  }
  try {
    const imported = parseEnvironmentFile(await file.text());
    environment.load(imported);
    setStatus(`Loaded ${file.name} · revalidate to check the environment`, "success");
  } catch (error) {
    setStatus(`Environment not imported: ${error.message}`, "error");
  }
};
makeWorker();
