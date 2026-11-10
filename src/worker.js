import { loadPyodide } from "./pyodide/pyodide.mjs";

const PYODIDE_BASE = new URL("./pyodide/", self.location.href).href;

let ready;

async function initialize() {
  self.postMessage({ type: "progress", message: "Initializing Python runtime…" });
  const pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });
  self.postMessage({ type: "progress", message: "Loading Luna validation engine…" });
  const response = await fetch(new URL("./engine.py", self.location.href));
  if (!response.ok) throw new Error("Could not load the validation engine");
  pyodide.runPython(await response.text());
  self.postMessage({ type: "ready" });
  return pyodide;
}

ready = initialize().catch(error => {
  self.postMessage({ type: "startup-error", message: String(error) });
  throw error;
});

self.onmessage = async ({ data }) => {
  try {
    const pyodide = await ready;
    pyodide.globals.set("__sequence_source", data.source);
    pyodide.globals.set("__sequence_mapping", data.mapping);
    pyodide.globals.set("__sequence_execute", data.mode === "simulate");
    const result = pyodide.runPython("json.dumps(run_sequence(__sequence_source, __sequence_mapping, __sequence_execute))");
    self.postMessage({ type: "result", result: JSON.parse(result), id: data.id });
  } catch (error) {
    self.postMessage({ type: "failure", message: String(error), id: data.id });
  }
};
