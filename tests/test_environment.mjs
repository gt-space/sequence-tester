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
