import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import vm from "node:vm";

// Extract the actual examples and environments wired into the UI, so examples
// cannot drift away from the simulated Luna API unnoticed.
const app = readFileSync(new URL("../src/app.js", import.meta.url), "utf8");
const start = app.indexOf("const EXAMPLES = {");
const end = app.indexOf("const $ = id =>");
assert.ok(start !== -1 && end > start, "Could not locate the UI's example definitions");
const context = vm.createContext({});
vm.runInContext(`${app.slice(start, end)}\n` +
  "globalThis.configurations = { examples: EXAMPLES, maps: EXAMPLE_MAPPINGS, fallback: DEFAULT_MAPPING };", context);
const configurations = JSON.parse(JSON.stringify(context.configurations));

function simulate(name) {
  const input = JSON.stringify({
    source: configurations.examples[name],
    mapping: configurations.maps[name] ?? configurations.fallback
  });
  const code = [
    "import json, sys",
    "sys.path.insert(0, 'src')",
    "from engine import run_sequence",
    "data = json.load(sys.stdin)",
    "print(json.dumps(run_sequence(data['source'], data['mapping'], True)))"
  ].join("\n");
  const process = spawnSync("python3", ["-c", code], { input, encoding: "utf8" });
  assert.equal(process.status, 0, process.stderr);
  return JSON.parse(process.stdout);
}

test("the Notion-derived two-stage example triggers its second stage", () => {
  const result = simulate("abort_two");
  assert.equal(result.checks.api, "pass", JSON.stringify(result.diagnostics));
  assert.equal(result.checks.runtime, "pass", JSON.stringify(result.diagnostics));
  assert.equal(result.simulation.aborted, true);
  assert.deepEqual(result.simulation.abort_stages.map(stage => stage.name), ["GROUND", "FILLING"]);
  assert.equal(result.simulation.abort_stages[0].triggered, null);
  assert.ok(result.simulation.abort_stages[1].triggered > 2);
  assert.ok(result.events.some(event => event.kind === "abort_safe" && event.target === "vent_valve"));
  assert.ok(result.diagnostics.some(d => d.message.includes("ABORT CONDITION NEVER TRIGGERED: 'GROUND'")));
});

test("the historical Vespula abort excerpt runs as a manual-command trace", () => {
  const result = simulate("vespula_abort");
  assert.equal(result.checks.api, "pass", JSON.stringify(result.diagnostics));
  assert.equal(result.checks.runtime, "pass", JSON.stringify(result.diagnostics));
  assert.equal(result.simulation.aborted, false);
  const valveEvents = result.events.filter(event => event.kind === "valve");
  assert.deepEqual(valveEvents.map(event => event.target),
    ["OBB", "FBB", "OSWV", "FSWV", "OMV", "FMV", "OVNT", "FVNT"]);
  assert.ok(valveEvents.find(event => event.target === "FMV").time > 0.16);
});
