import { normalizeSequenceName } from "./filename.js";

export const SAVED_SEQUENCES_KEY = "yjsp-saved-sequences-v1";
export const MAX_SAVED_SEQUENCES = 50;

export function listSavedSequences(storage) {
  const raw = storage.getItem(SAVED_SEQUENCES_KEY);
  if (raw === null) return [];
  let entries;
  try {
    entries = JSON.parse(raw);
  } catch {
    throw new Error("Saved sequence library is unreadable. Existing data was not changed.");
  }
  if (!Array.isArray(entries) || !entries.every(entry =>
    entry && typeof entry.name === "string" && typeof entry.source === "string" &&
    typeof entry.mapping === "string" && Number.isFinite(entry.updatedAt))) {
    throw new Error("Saved sequence library has invalid data. Existing data was not changed.");
  }
  return entries.sort((a, b) => b.updatedAt - a.updatedAt);
}

export function saveSequence(storage, { name, source, mapping }, now = Date.now()) {
  const normalizedName = normalizeSequenceName(name);
  if (typeof source !== "string" || source.length > 200000 ||
      typeof mapping !== "string" || mapping.length > 100000) {
    throw new Error("Sequence or test environment is too large to save.");
  }
  JSON.parse(mapping);
  const entries = listSavedSequences(storage);
  const existingIndex = entries.findIndex(entry => entry.name === normalizedName);
  if (existingIndex === -1 && entries.length >= MAX_SAVED_SEQUENCES) {
    throw new Error(`Library full (${MAX_SAVED_SEQUENCES} tests). Delete an older test before saving.`);
  }
  const entry = { name: normalizedName, source, mapping, updatedAt: now };
  if (existingIndex !== -1) entries.splice(existingIndex, 1);
  entries.unshift(entry);
  storage.setItem(SAVED_SEQUENCES_KEY, JSON.stringify(entries));
  return entry;
}

export function deleteSavedSequence(storage, name) {
  const entries = listSavedSequences(storage);
  const remaining = entries.filter(entry => entry.name !== name);
  if (remaining.length === entries.length) return false;
  storage.setItem(SAVED_SEQUENCES_KEY, JSON.stringify(remaining));
  return true;
}
