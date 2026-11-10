import assert from "node:assert/strict";
import test from "node:test";
import { normalizeEnvironment } from "../src/environment.js";

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
