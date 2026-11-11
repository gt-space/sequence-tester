import test from "node:test";
import assert from "node:assert/strict";
import {
  SAVED_SEQUENCES_KEY, MAX_SAVED_SEQUENCES,
  listSavedSequences, saveSequence, deleteSavedSequence
} from "../src/saved-sequences.js";

function memoryStorage() {
  const data = new Map();
  return {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value)
  };
}

const testCase = (name, source = "print('test')", mapping = '{"valves":[],"sensors":[]}') =>
  ({ name, source, mapping });

test("a test saves its Python source and environment and survives a reload", () => {
  const storage = memoryStorage();
  assert.deepEqual(listSavedSequences(storage), []);
  saveSequence(storage, testCase("CTS Fill", "CFILL.open()", '{"valves":["CFILL"],"sensors":[]}'), 1000);
  assert.deepEqual(listSavedSequences(storage), [{
    name: "CTS_Fill", source: "CFILL.open()", mapping: '{"valves":["CFILL"],"sensors":[]}', updatedAt: 1000
  }]);
});

test("re-running the same named test updates the existing saved version", () => {
  const storage = memoryStorage();
  saveSequence(storage, testCase("first", "old"), 100);
  saveSequence(storage, testCase("second"), 200);
  saveSequence(storage, testCase("first", "new"), 300);
  assert.deepEqual(listSavedSequences(storage).map(item => item.name), ["first", "second"]);
  assert.equal(listSavedSequences(storage)[0].source, "new");
  assert.equal(listSavedSequences(storage)[0].updatedAt, 300);
});

test("deleting a saved test leaves other test snapshots intact", () => {
  const storage = memoryStorage();
  saveSequence(storage, testCase("fill"), 100);
  saveSequence(storage, testCase("purge"), 200);
  assert.equal(deleteSavedSequence(storage, "fill"), true);
  assert.equal(deleteSavedSequence(storage, "fill"), false);
  assert.deepEqual(listSavedSequences(storage).map(item => item.name), ["purge"]);
});

test("full library never silently discards older sequences", () => {
  const storage = memoryStorage();
  for (let i = 0; i < MAX_SAVED_SEQUENCES; i++) {
    saveSequence(storage, testCase(`test_${i}`), i);
  }
  assert.throws(() => saveSequence(storage, testCase("test_extra")), /Library full/);
  assert.equal(listSavedSequences(storage).length, MAX_SAVED_SEQUENCES);
  saveSequence(storage, testCase("test_2", "updated"));
  assert.equal(listSavedSequences(storage).length, MAX_SAVED_SEQUENCES);
});

test("corrupted saved data is reported without overwriting it", () => {
  const storage = memoryStorage();
  storage.setItem(SAVED_SEQUENCES_KEY, "bad-json");
  assert.throws(() => listSavedSequences(storage), /unreadable/);
  assert.throws(() => saveSequence(storage, testCase("test")), /unreadable/);
  assert.equal(storage.getItem(SAVED_SEQUENCES_KEY), "bad-json");
});

test("invalid data and storage errors cannot masquerade as successful saves", () => {
  const storage = memoryStorage();
  assert.throws(() => saveSequence(storage, testCase("bad", "ok", "invalid")), SyntaxError);
  assert.deepEqual(listSavedSequences(storage), []);
  const denied = { getItem: () => null, setItem: () => { throw new Error("QuotaExceededError"); } };
  assert.throws(() => saveSequence(denied, testCase("test")), /QuotaExceededError/);
});
