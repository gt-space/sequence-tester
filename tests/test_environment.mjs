import assert from "node:assert/strict";
import test from "node:test";
import { normalizeEnvironment, parseEnvironmentFile, serializeEnvironmentFile } from "../src/environment.js";

const fallback = { valves: ["FBB"], sensors: [] };

test("migrates legacy valve names to initially closed valves", () => {
  const result = normalizeEnvironment(JSON.stringify(fallback), fallback);
  assert.deepEqual(result.valves, [{ name: "FBB", initial: "CLOSED" }]);
});

test("preserves configured valve initial states and sensor profiles", () => {
  const input = {
    valves: [{ name: "OBB", initial: "OPEN" }],
    sensors: [{ name: "FTPT", unit: "psi", interpolation: "linear", samples: [{ at: 0, value: 10 }, { at: 2, value: 100 }] }]
  };
  const result = normalizeEnvironment(input, fallback);
  assert.equal(result.valves[0].initial, "OPEN");
  assert.equal(result.sensors[0].interpolation, "linear");
  assert.equal(result.sensors[0].samples[1].value, 100);
});

test("falls back when saved JSON is invalid", () => {
  const result = normalizeEnvironment("{invalid", fallback);
  assert.equal(result.valves[0].name, "FBB");
});

test("preserves valve-driven truth table including intentionally blank cells", () => {
  const input = { valves: ["CISO", "CMV"], sensors: [{
    name: "CTPT", unit: "psi", mode: "valve", initial: 200,
    valves: ["CISO", "CMV"], rates: { "00": 0, "01": -25, "10": 40, "11": "" },
    min: 0, max: 500
  }] };
  const result = normalizeEnvironment(input, fallback).sensors[0];
  assert.equal(result.mode, "valve");
  assert.deepEqual(result.valves, ["CISO", "CMV"]);
  assert.deepEqual(result.rates, input.sensors[0].rates);
  assert.equal(result.initial, 200);
  assert.equal(result.min, 0);
});

test("export and import round-trip every valve state and a complete 16-row truth table", () => {
  const rates = Object.fromEntries(Array.from({ length: 16 }, (_, index) => [index.toString(2).padStart(4, "0"), index - 7]));
  const environment = normalizeEnvironment({
    valves: ["CISO", { name: "CMV", initial: "OPEN" }, "FBB", "OBB"],
    sensors: [{ name: "CTPT", unit: "psi", mode: "valve", initial: 250,
      valves: ["CISO", "CMV", "FBB", "OBB"], rates, min: 0, max: 500 }]
  }, fallback);
  const file = serializeEnvironmentFile(environment);
  assert.match(file, /\n  "valves": \[/);
  assert.deepEqual(parseEnvironmentFile(file), environment);
  assert.deepEqual(parseEnvironmentFile(file).sensors[0].rates, rates);
});

test("import retains incomplete truth tables so a user can save a draft", () => {
  const draft = { valves: ["CISO", "CMV"], sensors: [{ name: "CTPT", unit: "psi", mode: "valve",
    valves: ["CISO", "CMV"], rates: { "00": 0, "01": "", "10": 15 } }] };
  const result = parseEnvironmentFile(`\uFEFF${JSON.stringify(draft)}`);
  assert.equal(result.sensors[0].rates["01"], "");
  assert.equal(result.sensors[0].rates["11"], undefined);
  assert.deepEqual(result.valves, [{ name: "CISO", initial: "CLOSED" }, { name: "CMV", initial: "CLOSED" }]);
});

test("invalid imports are rejected rather than silently replacing the environment with defaults", () => {
  assert.throws(() => parseEnvironmentFile("{bad json"), /Invalid JSON/);
  assert.throws(() => parseEnvironmentFile(JSON.stringify({ valves: ["CISO"] })), /"valves" and "sensors"/);
  assert.throws(() => parseEnvironmentFile(JSON.stringify({ valves: [null], sensors: [] })), /Valve 1/);
  assert.throws(() => parseEnvironmentFile(JSON.stringify({ valves: [], sensors: [{ name: "CTPT", valves: Array(5).fill("V") }] })), /at most four/);
  assert.throws(() => parseEnvironmentFile(JSON.stringify({ valves: [], sensors: [{ name: "CTPT", samples: [null] }] })), /invalid time profile/);
});
