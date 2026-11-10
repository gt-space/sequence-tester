const UNITS = ["psi", "V", "A", "lbf", "K", "unknown"];
const SVG_NS = "http://www.w3.org/2000/svg";

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
      interpolation: sensor?.interpolation ?? "step",
      samples: Array.isArray(sensor?.samples) ? sensor.samples.map(sample => ({ at: sample?.at ?? "", value: sample?.value ?? "" })) : [{ at: 0, value: sensor?.value ?? 0 }]
    }))
  };
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
        field("Valve name", valve.name, value => { valve.name = value; save(); }),
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
      title.append(node("small", "", `${sensor.samples.length} points · ${sensor.unit}`));
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
        title.querySelector("small").textContent = `${sensor.samples.length} points · ${value}`;
        save();
      });
      const interpolation = dropdown("Profile", sensor.interpolation, [["step", "Step / hold"], ["linear", "Linear"]], value => {
        sensor.interpolation = value;
        refreshChart();
        save();
      });
      fields.append(name, unit, interpolation);

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
        details.append(fields, graph, samples, addPoint);
        card.append(details);
      } else {
        const preview = node("div", "env-sensor-preview");
        preview.append(graph);
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
      const sensor = { name: "", unit: "psi", interpolation: "step", samples: [{ at: 0, value: 0 }] };
      data.sensors.push(sensor);
      expandedSensors.add(sensor);
      renderSensors();
      save();
      sensorList.lastElementChild.querySelector("input")?.focus();
    }
  };
}
