const UNITS = ["psi", "V", "A", "lbf", "K", "unknown"];
const SVG_NS = "http://www.w3.org/2000/svg";
const tableKeys = count => Array.from({ length: 2 ** count }, (_, i) => i.toString(2).padStart(count, "0"));

function node(tag, className, label) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (label !== undefined) element.textContent = label;
  return element;
}

function action(label, onClick, className = "env-action") {
  const button = node("button", className, label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function field(label, value, onInput, type = "text") {
  const wrapper = node("label", "env-field");
  wrapper.append(node("span", "env-field-label", label));
  const input = node("input", "env-input");
  input.type = type;
  input.value = value ?? "";
  input.setAttribute("aria-label", label);
  if (type === "number") {
    input.step = "any";
    input.inputMode = "decimal";
  }
  input.addEventListener("input", () => onInput(input.value));
  wrapper.append(input);
  return wrapper;
}

function dropdown(label, value, options, onChange) {
  const wrapper = node("label", "env-field");
  wrapper.append(node("span", "env-field-label", label));
  const select = node("select", "env-select");
  for (const [key, text] of options) {
    const option = node("option", "", text);
    option.value = key;
    option.selected = key === value;
    select.append(option);
  }
  select.addEventListener("change", () => onChange(select.value));
  wrapper.append(select);
  return wrapper;
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function profileChart(sensor) {
  const chart = svgElement("svg", { viewBox: "0 0 320 128", role: "img", "aria-label": `${sensor.name || "Sensor"} profile` });
  const samples = sensor.samples
    .filter(point => point.at !== "" && point.value !== "" && Number.isFinite(Number(point.at)) && Number.isFinite(Number(point.value)) && Number(point.at) >= 0)
    .map(point => ({ at: Number(point.at), value: Number(point.value) }))
    .sort((a, b) => a.at - b.at);
  if (!samples.length) return chart;

  const left = 36, right = 307, top = 16, bottom = 100;
  const duration = Math.max(1, ...samples.map(point => point.at));
  const values = samples.map(point => point.value);
  const low = Math.min(...values), high = Math.max(...values);
  const spread = Math.max(1, high - low);
  const min = low - spread * .15, max = high + spread * .15;
  const x = time => left + time / duration * (right - left);
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);

  for (let i = 0; i <= 3; i++) {
    const level = top + (bottom - top) * i / 3;
    chart.append(svgElement("line", { x1: left, x2: right, y1: level, y2: level, class: "env-chart-grid" }));
  }
  const interpolation = sensor.interpolation === "linear" ? "linear" : "step";
  let path = `M${left} ${y(samples[0].value)}`;
  for (let i = 1; i < samples.length; i++) {
    const point = samples[i];
    path += interpolation === "linear" ? ` L${x(point.at)} ${y(point.value)}` : ` H${x(point.at)} V${y(point.value)}`;
  }
  path += ` H${right}`;
  chart.append(svgElement("path", { d: path, class: "env-chart-line" }));
  for (const point of samples) chart.append(svgElement("circle", { cx: x(point.at), cy: y(point.value), r: 3.5, class: "env-chart-point" }));
  const start = svgElement("text", { x: left, y: 119, class: "env-chart-label", "text-anchor": "start" });
  start.textContent = "0s";
  const end = svgElement("text", { x: right, y: 119, class: "env-chart-label", "text-anchor": "end" });
  end.textContent = `${Number(duration.toFixed(2))}s`;
  chart.append(start, end);
  return chart;
}

export function normalizeEnvironment(raw, fallback) {
  let data;
  try {
    data = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    data = fallback;
  }
  if (!data || !Array.isArray(data.valves) || !Array.isArray(data.sensors)) data = fallback;
  return {
    valves: data.valves.map(valve => typeof valve === "string"
      ? { name: valve, initial: "CLOSED" }
      : { name: valve?.name ?? "", initial: valve?.initial ?? "CLOSED" }),
    sensors: data.sensors.map(sensor => ({
      name: sensor?.name ?? "",
      unit: sensor?.unit ?? "unknown",
      mode: sensor?.mode === "valve" ? "valve" : "time",
      initial: sensor?.initial ?? 0,
      min: sensor?.min ?? null,
      max: sensor?.max ?? null,
      valves: Array.isArray(sensor?.valves) ? [...sensor.valves] : [],
      rates: sensor?.rates && typeof sensor.rates === "object" && !Array.isArray(sensor.rates) ? { ...sensor.rates } : {},
      interpolation: sensor?.interpolation ?? "step",
      samples: Array.isArray(sensor?.samples) ? sensor.samples.map(sample => ({ at: sample?.at ?? "", value: sample?.value ?? "" })) : [{ at: 0, value: sensor?.value ?? 0 }]
    }))
  };
}

// Reject malformed imports instead of silently replacing the current editor with defaults.
export function parseEnvironmentFile(raw) {
  let data;
  try {
    data = JSON.parse(raw.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error("Invalid JSON. Choose a test environment .json file.");
  }
  if (!data || typeof data !== "object" || Array.isArray(data) ||
      !Array.isArray(data.valves) || !Array.isArray(data.sensors)) {
    throw new Error('Environment JSON must contain "valves" and "sensors" arrays.');
  }
  if (data.valves.length > 100 || data.sensors.length > 100) {
    throw new Error("Environment has too many valves or sensors (100 maximum each).");
  }
  for (const [index, valve] of data.valves.entries()) {
    if (typeof valve === "string") continue; // Legacy exported configurations.
    if (!valve || typeof valve !== "object" || Array.isArray(valve) ||
        typeof valve.name !== "string" ||
        (valve.initial !== undefined && !["OPEN", "CLOSED"].includes(valve.initial))) {
      throw new Error(`Valve ${index + 1} must have a name and an OPEN/CLOSED initial state.`);
    }
  }
  for (const [index, sensor] of data.sensors.entries()) {
    if (!sensor || typeof sensor !== "object" || Array.isArray(sensor) || typeof sensor.name !== "string") {
      throw new Error(`Sensor ${index + 1} must be an object with a name.`);
    }
    if (sensor.valves !== undefined &&
        (!Array.isArray(sensor.valves) || sensor.valves.length > 4 ||
          sensor.valves.some(name => typeof name !== "string"))) {
      throw new Error(`Sensor ${index + 1} must reference at most four valve names.`);
    }
    if (sensor.samples !== undefined &&
        (!Array.isArray(sensor.samples) || sensor.samples.length > 1000 ||
          sensor.samples.some(sample => !sample || typeof sample !== "object" || Array.isArray(sample)))) {
      throw new Error(`Sensor ${index + 1} has an invalid time profile.`);
    }
    if (sensor.rates !== undefined &&
        (!sensor.rates || typeof sensor.rates !== "object" || Array.isArray(sensor.rates))) {
      throw new Error(`Sensor ${index + 1} has an invalid valve truth table.`);
    }
  }
  const normalized = normalizeEnvironment(data, data);
  if (JSON.stringify(normalized).length > 100000) {
    throw new Error("Environment is too large (100 KB maximum configuration).");
  }
  return normalized;
}

export function serializeEnvironmentFile(environment) {
  return `${JSON.stringify(environment, null, 2)}\n`;
}

export function createEnvironmentEditor({ mapping, valveList, sensorList, initial, fallback, onChange }) {
  let data = normalizeEnvironment(initial, fallback);
  let expandedSensors = new WeakSet();

  function save(notify = true) {
    mapping.value = JSON.stringify(data);
    if (notify) onChange();
  }

  function renderValves() {
    valveList.replaceChildren();
    if (data.valves.length) {
      const headings = node("div", "env-valve-table-head");
      headings.append(node("span", "", "VALVE NAME"), node("span", "", "STARTING STATE"));
      valveList.append(headings);
    }
    data.valves.forEach((valve, index) => {
      const row = node("div", "env-valve-row");
      const remove = action("×", () => { data.valves.splice(index, 1); renderValves(); save(); }, "env-remove");
      remove.setAttribute("aria-label", `Remove valve ${valve.name || index + 1}`);
      row.append(
        field("Valve name", valve.name, value => {
          const previous = valve.name;
          valve.name = value;
          for (const sensor of data.sensors) {
            if (sensor.mode === "valve") sensor.valves = sensor.valves.map(name => name === previous ? value : name);
          }
          renderSensors();
          save();
        }),
        dropdown("Starting state", valve.initial, [["CLOSED", "Closed"], ["OPEN", "Open"]], value => { valve.initial = value; save(); }),
        remove
      );
      valveList.append(row);
    });
    if (!data.valves.length) valveList.append(node("div", "env-empty", "No valves configured"));
    document.getElementById("valve-count").textContent = String(data.valves.length);
  }

  function renderSensors() {
    sensorList.replaceChildren();
    data.sensors.forEach((sensor, index) => {
      const card = node("section", "env-sensor-card");
      const expanded = expandedSensors.has(sensor);
      card.classList.toggle("expanded", expanded);
      const heading = node("div", "env-sensor-header");
      const toggle = action("", () => {
        if (expanded) expandedSensors.delete(sensor);
        else expandedSensors.add(sensor);
        renderSensors();
      }, "env-sensor-toggle");
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", `${expanded ? "Collapse" : "Edit"} sensor ${sensor.name || index + 1}`);
      toggle.append(node("span", "env-sensor-icon", "∿"));
      const title = node("span", "env-sensor-title");
      title.append(node("strong", "", sensor.name || "New sensor"));
      const subtitle = node("small");
      title.append(subtitle);
      const dynamic = sensor.mode === "valve";
      const keys = tableKeys(sensor.valves.length);
      const completed = keys.filter(key => sensor.rates[key] !== "" && sensor.rates[key] !== undefined && Number.isFinite(Number(sensor.rates[key]))).length;
      const updateSubtitle = () => {
        subtitle.textContent = dynamic ? `${completedCount()}/${keys.length} states · ${sensor.unit}/s` : `${sensor.samples.length} points · ${sensor.unit}`;
        subtitle.classList.toggle("env-incomplete", dynamic && completedCount() !== keys.length);
      };
      const completedCount = () => keys.filter(key => sensor.rates[key] !== "" && sensor.rates[key] !== undefined && Number.isFinite(Number(sensor.rates[key]))).length;
      updateSubtitle();
      toggle.append(title, node("span", "env-chevron", expanded ? "⌃" : "⌄"));
      heading.append(toggle);
      const removeSensor = action("×", () => { data.sensors.splice(index, 1); renderSensors(); save(); }, "env-remove");
      removeSensor.setAttribute("aria-label", `Remove sensor ${sensor.name || index + 1}`);
      heading.append(removeSensor);

      const fields = node("div", "env-sensor-fields");
      const name = field("Name", sensor.name, value => {
        sensor.name = value;
        title.querySelector("strong").textContent = value || "New sensor";
        refreshChart();
        save();
      });
      const unit = dropdown("Unit", sensor.unit, UNITS.map(value => [value, value]), value => {
        sensor.unit = value;
        renderSensors();
        save();
      });
      const interpolation = dropdown("Profile", sensor.interpolation, [["step", "Step / hold"], ["linear", "Linear"]], value => {
        sensor.interpolation = value;
        refreshChart();
        save();
      });
      const mode = dropdown("Sensor behavior", sensor.mode, [["time", "Time profile"], ["valve", "Valve-driven"]], value => {
        sensor.mode = value;
        renderSensors();
        save();
      });
      fields.append(name, unit, mode);
      if (!dynamic) fields.append(interpolation);

      const graph = node("div", "env-chart");
      function refreshChart() { graph.replaceChildren(profileChart(sensor)); }
      refreshChart();

      const samples = node("div", "env-samples");
      const labels = node("div", "env-sample-labels");
      labels.append(node("span", "", "TIME (s)"), node("span", "", "VALUE"));
      samples.append(labels);
      sensor.samples.forEach((point, pointIndex) => {
        const row = node("div", "env-sample-row");
        const removePoint = action("×", () => {
          sensor.samples.splice(pointIndex, 1);
          renderSensors();
          save();
        }, "env-remove");
        removePoint.setAttribute("aria-label", `Remove sample ${pointIndex + 1} from ${sensor.name || "sensor"}`);
        removePoint.disabled = sensor.samples.length <= 1;
        row.append(
          field("Time (s)", point.at, value => { point.at = value === "" ? "" : Number(value); refreshChart(); save(); }, "number"),
          field("Value", point.value, value => { point.value = value === "" ? "" : Number(value); refreshChart(); save(); }, "number"),
          removePoint
        );
        samples.append(row);
      });
      const addPoint = action("+ Add point", () => {
        const last = sensor.samples.at(-1);
        const lastTime = Number(last?.at);
        sensor.samples.push({ at: Number.isFinite(lastTime) ? lastTime + 1 : 0, value: Number(last?.value) || 0 });
        renderSensors();
        save();
        sensorList.children[index].querySelector(".env-sample-row:last-child input")?.focus();
      });
      card.append(heading);
      if (expanded) {
        const details = node("div", "env-sensor-details");
        details.append(fields);
        if (dynamic) {
          const setup = node("div", "env-dynamic-setup");
          setup.append(node("p", "env-sensor-hint", "Select the valves affecting this sensor. Every OPEN/CLOSED combination needs an explicit rate (enter 0 for no change)."));
          const settings = node("div", "env-dynamic-settings");
          settings.append(field(`Initial value (${sensor.unit})`, sensor.initial, value => {
            sensor.initial = value === "" ? "" : Number(value);
            save();
          }, "number"));
          for (const bound of ["min", "max"]) {
            settings.append(field(`${bound === "min" ? "Minimum" : "Maximum"} (optional)`, sensor[bound] ?? "", value => {
              sensor[bound] = value === "" ? null : Number(value);
              save();
            }, "number"));
          }
          setup.append(settings);
          const selection = node("div", "env-influences");
          selection.append(node("span", "env-field-label", "Influencing valves (up to 4)"));
          const configured = data.valves.map(v => v.name).filter(v => v);
          sensor.valves.forEach((valve, valveIndex) => {
            const line = node("div", "env-influence-row");
            const options = [["", "Select valve…"], ...configured.filter(v => v === valve || !sensor.valves.includes(v)).map(v => [v, v])];
            line.append(dropdown(`Valve ${valveIndex + 1}`, valve, options, value => {
              sensor.valves[valveIndex] = value;
              sensor.rates = {};
              renderSensors();
              save();
            }), action("×", () => {
              sensor.valves.splice(valveIndex, 1);
              sensor.rates = {};
              renderSensors();
              save();
            }, "env-remove"));
            selection.append(line);
          });
          const available = configured.filter(v => !sensor.valves.includes(v));
          const addInfluence = action("+ Add valve", () => {
            sensor.valves.push(available[0]);
            sensor.rates = {};
            renderSensors();
            save();
          });
          addInfluence.disabled = sensor.valves.length >= 4 || !available.length;
          selection.append(addInfluence);
          setup.append(selection);
          if (sensor.valves.length) {
            const table = node("div", "env-truth-table");
            const head = node("div", "env-truth-head");
            const columns = `repeat(${sensor.valves.length}, minmax(65px, 1fr)) minmax(108px, 1.4fr)`;
            head.style.gridTemplateColumns = columns;
            for (const valve of sensor.valves) head.append(node("span", "", valve || "?"));
            head.append(node("span", "", `RATE (${sensor.unit}/s)`));
            table.append(head);
            keys.forEach(key => {
              const line = node("div", "env-truth-row");
              line.style.gridTemplateColumns = columns;
              for (const bit of key) line.append(node("span", `env-state ${bit === "1" ? "open" : "closed"}`, bit === "1" ? "OPEN" : "CLOSED"));
              const current = sensor.rates[key];
              line.append(field(`Rate for ${key}`, current ?? "", value => {
                sensor.rates[key] = value === "" ? "" : Number(value);
                const remaining = keys.filter(item => sensor.rates[item] !== "" && sensor.rates[item] !== undefined && Number.isFinite(Number(sensor.rates[item]))).length;
                status.textContent = `${remaining}/${keys.length} combinations defined`;
                status.classList.toggle("env-incomplete", remaining !== keys.length);
                updateSubtitle();
                save();
              }, "number"));
              table.append(line);
            });
            const status = node("p", "env-table-status", `${completed}/${keys.length} combinations defined`);
            status.classList.toggle("env-incomplete", completed !== keys.length);
            setup.append(table, status);
          } else setup.append(node("p", "env-incomplete", "Select at least one valve to generate its truth table."));
          details.append(setup);
        } else details.append(graph, samples, addPoint);
        card.append(details);
      } else {
        const preview = node("div", "env-sensor-preview");
        if (dynamic) preview.append(node("div", "env-sensor-hint", `${sensor.valves.join(" + ") || "No valves selected"} · ${completed}/${keys.length} rates defined`));
        else preview.append(graph);
        card.append(preview);
      }
      sensorList.append(card);
    });
    if (!data.sensors.length) sensorList.append(node("div", "env-empty", "No sensors configured"));
    document.getElementById("sensor-count").textContent = String(data.sensors.length);
  }

  function render() {
    renderValves();
    renderSensors();
  }

  render();
  save(false);
  return {
    load(next) { data = normalizeEnvironment(next, fallback); expandedSensors = new WeakSet(); render(); save(); },
    focus() { (valveList.querySelector("input") || sensorList.querySelector("input") || valveList.parentElement.querySelector("button"))?.focus(); },
    addValve() {
      data.valves.push({ name: "", initial: "CLOSED" });
      renderValves();
      save();
      valveList.lastElementChild.querySelector("input")?.focus();
    },
    addSensor() {
      const sensor = { name: "", unit: "psi", mode: "time", initial: 0, min: null, max: null, valves: [], rates: {}, interpolation: "step", samples: [{ at: 0, value: 0 }] };
      data.sensors.push(sensor);
      expandedSensors.add(sensor);
      renderSensors();
      save();
      sensorList.lastElementChild.querySelector("input")?.focus();
    }
  };
}
