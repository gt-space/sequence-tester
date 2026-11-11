import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSequenceName, sequenceFileName, environmentFileName } from "../src/filename.js";

test("named sequences download as distinct Python files", () => {
  assert.equal(sequenceFileName("CTS Cryo Purge v3"), "CTS_Cryo_Purge_v3.py");
  assert.equal(environmentFileName("CTS Cryo Purge v3"), "CTS_Cryo_Purge_v3-environment.json");
});

test("uploaded filenames keep their base names without doubled extensions", () => {
  assert.equal(normalizeSequenceName("cts_purge.py"), "cts_purge");
  assert.equal(sequenceFileName("cts_purge.PY"), "cts_purge.py");
});

test("filenames cannot contain directory separators or become empty", () => {
  assert.equal(sequenceFileName("../folder/test:rev?2.py"), "folder_test_rev_2.py");
  assert.equal(sequenceFileName(".."), "sequence.py");
  assert.equal(sequenceFileName(""), "sequence.py");
});
