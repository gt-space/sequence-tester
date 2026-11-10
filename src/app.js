const EXAMPLES = {
  tank: `# Tank press demonstration with simulated sensor data\npress_valve.open()\nwait_until(lambda: tank_pt.read() >= 300 * psi, 5 * s)\npress_valve.close()\nprint("Tank press sequence finished")`,
  pulse: `# Timed valve operation\npress_valve.open()\nwait_for(500 * ms)\npress_valve.close()\nwait_for(250 * ms)\nvent_valve.open()\nwait_for(250 * ms)\nvent_valve.close()`,
  import: `# Missing import is detected before execution\npress_valve.open()\ntime.sleep(1)\npress_valve.close()`,
  api: `# A sensor cannot be opened like a valve\ntank_pt.open()\npress_valve.open()\nwait_for(500 * ms)\npress_valve.close()`
};

const DEFAULT_MAPPING = {
  valves: ["press_valve", "vent_valve"],
  sensors: [{ name: "tank_pt", unit: "psi", samples: [{ at: 0, value: 0 }, { at: 1, value: 120 }, { at: 2, value: 220 }, { at: 3, value: 315 }] }]
};

const $ = id => document.getElementById(id);
const source = $("source");
const mapping = $("mapping");
const status = $("engine-status");
let worker;
let ready = false;
let currentId = 0;
let pending = null;
let executionTimeout;
let startupTimeout;
let running = false;
let startupPhase = "Loading Python runtime…";

function setStatus(message, level = "normal") {
  status.textContent = message;
  status.dataset.level = level;
}

function makeWorker() {
  if (worker) worker.terminate();
  clearTimeout(startupTimeout);
  clearTimeout(executionTimeout);
  const workerUrl = new URL("./worker.js", import.meta.url);
  workerUrl.search = new URL(import.meta.url).search;
  worker = new Worker(workerUrl);
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
      clearTimeout(executionTimeout);
      running = false;
      pending = null;
      render(data.result);
      setStatus("Check complete", "success");
    } else if (data.type === "failure") {
      if (data.id !== currentId) return;
      clearTimeout(executionTimeout);
      running = false;
      pending = null;
      setStatus(`Execution failed: ${data.message}`, "error");
    }
  };
  worker.onerror = event => {
    clearTimeout(startupTimeout);
    clearTimeout(executionTimeout);
    setStatus(`Runtime error: ${event.message}`, "error");
    worker.terminate();
    worker = null;
  };
}

function dispatch(request) {
  pending = null;
  running = true;
  setStatus(request.mode === "simulate" ? "Simulating…" : "Validating…");
  worker.postMessage(request);
  executionTimeout = setTimeout(() => {
    render({ checks: { syntax: "pass", names: "not_run", api: "not_run", runtime: "fail" }, diagnostics: [{ stage: "runtime", severity: "error", message: "Execution exceeded the 5-second wall-clock limit", line: 0 }], events: [], virtual_time: 0, stdout: "" });
    running = false;
    makeWorker();
    setStatus("Execution stopped after 5 seconds. Restarting Python runtime…", "error");
  }, 5000);
}

function run(mode) {
  if (source.value.length > 200000 || mapping.value.length > 100000) {
    setStatus("Sequence or configuration too large", "error");
    return;
  }
  const request = { id: ++currentId, mode, source: source.value, mapping: mapping.value };
  localStorage.setItem("yjsp-sequence-source", source.value);
  localStorage.setItem("yjsp-sequence-mapping", mapping.value);
  if (!worker) makeWorker();
  if (running) {
    makeWorker();
    pending = request;
    return;
  }
  if (ready) dispatch(request);
  else { pending = request; setStatus("Waiting for Python runtime…"); }
}

function render(result) {
  const stages = result.checks || {};
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
    empty.textContent = "No diagnostics reported for these checks.";
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
      if (!item.line) return;
      const lines = source.value.split("\n");
      const offset = lines.slice(0, item.line - 1).reduce((sum, line) => sum + line.length + 1, 0);
      source.focus();
      source.setSelectionRange(offset, offset + (lines[item.line - 1] || "").length);
    };
    list.append(row);
  }
  $("virtual-time").textContent = typeof result.virtual_time === "number" ? `${result.virtual_time.toFixed(3)} s` : "—";
  const trace = $("trace");
  trace.replaceChildren();
  const events = result.events || [];
  if (!events.length) {
    trace.className = "trace-empty";
    trace.textContent = stages.runtime === "pass" ? "Sequence finished without issuing hardware commands." : "Run a successful simulation to see the event trace.";
  } else {
    trace.className = "event-list";
    for (const event of events) {
      const row = document.createElement("div");
      row.className = "event-row";
      const time = document.createElement("span");
      time.className = "event-time";
      time.textContent = `${Number(event.time).toFixed(3)} s`;
      const kind = document.createElement("span");
      kind.className = `event-kind ${event.kind}`;
      kind.textContent = event.kind;
      const detail = document.createElement("span");
      detail.textContent = `${event.target} · ${event.detail}`;
      row.append(time, kind, detail);
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
  localStorage.setItem("yjsp-sequence-source", source.value);
}

source.value = localStorage.getItem("yjsp-sequence-source") ?? EXAMPLES.tank;
mapping.value = localStorage.getItem("yjsp-sequence-mapping") ?? JSON.stringify(DEFAULT_MAPPING, null, 2);
updateEditor();
source.addEventListener("input", updateEditor);
source.addEventListener("scroll", () => { $("gutter").scrollTop = source.scrollTop; });
source.addEventListener("keydown", event => {
  if (event.key === "Tab") {
    event.preventDefault();
    const a = source.selectionStart;
    source.setRangeText("    ", a, source.selectionEnd, "end");
    updateEditor();
  }
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    run("simulate");
  }
});
mapping.addEventListener("input", () => localStorage.setItem("yjsp-sequence-mapping", mapping.value));
$("validate").onclick = () => run("validate");
$("simulate").onclick = () => run("simulate");
document.querySelectorAll("[data-example]").forEach(button => button.onclick = () => {
  source.value = EXAMPLES[button.dataset.example];
  updateEditor();
  source.focus();
});
$("upload").onclick = () => $("file-input").click();
$("file-input").onchange = async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 200000) { setStatus("File too large (200 KB maximum)", "error"); return; }
  source.value = await file.text();
  updateEditor();
};
$("download").onclick = () => {
  const url = URL.createObjectURL(new Blob([source.value], { type: "text/x-python" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "sequence.py";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
makeWorker();
