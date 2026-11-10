const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 1000;
const LEFT = 150;
const RIGHT = 969;
const PINS = ["#e0a500", "#75cbe3", "#c89cde", "#8fd1a5"];
const SENSOR_COLORS = ["#75cbe3", "#8fd1a5", "#c89cde", "#e0a500", "#ee9d85"];

function el(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function svg(tag, attributes = {}, text) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}

function nice(number) {
  return Number(number).toLocaleString("en-US", { maximumFractionDigits: 3 });
}

export function sensorValueAt(sensor, time) {
  const samples = sensor.samples || [];
  if (!samples.length) return null;
  let previous = samples[0];
  for (const sample of samples.slice(1)) {
    if (sample.at > time) {
      if (sensor.interpolation === "linear" && time > previous.at) {
        const ratio = (time - previous.at) / (sample.at - previous.at);
        return previous.value + ratio * (sample.value - previous.value);
      }
      break;
    }
    previous = sample;
  }
  return previous.value;
}

export function valveStateAt(initial, events, name, time) {
  let state = initial[name] || "CLOSED";
  for (const event of events) {
    if (event.time > time) break;
    if (event.kind === "valve" && event.target === name) state = event.detail;
  }
  return state;
}

export function sensorRateAt(sensor, initial, events, time) {
  if (sensor.mode !== "valve") return null;
  const key = sensor.valves.map(name => valveStateAt(initial, events, name, time) === "OPEN" ? "1" : "0").join("");
  return { key, rate: sensor.rates[key] };
}

export function sampleScale(sensor) {
  const values = (sensor.samples || []).map(sample => Number(sample.value));
  if (!values.length) return { min: 0, max: 1 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const margin = Math.max((max - min) * .12, Math.abs(max) * .015, 1);
  return { min: min - margin, max: max + margin };
}

export function createTimelineView({ container, onJumpToSource }) {
  let payload = null;
  let duration = 1;
  let pins = [];
  let hovered = null;
  let selectedEvent = -1;
  let selectedLine = 0;
  let overlays = [];
  let chips;
  let readout;
  let counter;
  let hint;
  let nextPinId = 0;

  const xAt = time => LEFT + time / duration * (RIGHT - LEFT);
  const clamp = value => Math.min(duration, Math.max(0, value));
  const displayTime = time => `${nice(time)}s`;

  function uniquePinId() {
    for (let i = 0; i < 4; i++) {
      const candidate = (nextPinId + i) % 4;
      if (!pins.some(pin => pin.id === candidate)) {
        nextPinId = (candidate + 1) % 4;
        return candidate;
      }
    }
    return -1;
  }

  function drawGrid(chart, height) {
    for (let i = 0; i <= 5; i++) {
      const time = duration * i / 5;
      const x = xAt(time);
      chart.append(svg("line", { x1: x, x2: x, y1: 22, y2: height - 26, class: "timeline-grid" }));
      chart.append(svg("text", { x, y: height - 7, class: "timeline-axis", "text-anchor": "middle" }, displayTime(time)));
    }
  }

  function attachPointer(chart) {
    chart.classList.add("timeline-interactive");
    const timeFromPointer = event => {
      const bounds = chart.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width * WIDTH;
      return clamp((x - LEFT) / (RIGHT - LEFT) * duration);
    };
    chart.addEventListener("pointermove", event => {
      hovered = timeFromPointer(event);
      updateCursors();
    });
    chart.addEventListener("pointerleave", () => { hovered = null; updateCursors(); });
    chart.addEventListener("click", event => {
      if (pins.length === 4) return;
      hovered = timeFromPointer(event);
      pins.push({ id: uniquePinId(), time: Number(hovered.toFixed(3)) });
      updateCursors();
    });
  }

  function makeChart(label, height) {
    const chart = svg("svg", { viewBox: `0 0 ${WIDTH} ${height}`, role: "img", "aria-label": label });
    drawGrid(chart, height);
    attachPointer(chart);
    const overlay = svg("g", { class: "timeline-overlay" });
    chart.append(overlay);
    overlays.push({ chart, overlay, height });
    return chart;
  }

  function marker(event, index, cy) {
    const hit = svg("circle", {
      cx: xAt(event.time), cy, r: 8, class: `timeline-event-dot ${event.detail === "OPEN" ? "valve-open" : "valve-closed"}${selectedEvent === index || (selectedLine && event.line === selectedLine) ? " selected" : ""}`,
      tabindex: event.line ? 0 : -1, role: event.line ? "button" : "img",
      "aria-label": `${event.target} ${event.detail} at ${displayTime(event.time)}${event.line ? `, source line ${event.line}` : ""}`,
      "data-event-index": index
    });
    hit.append(svg("title", {}, `${event.target}: ${event.detail} · ${displayTime(event.time)}${event.line ? ` · line ${event.line}` : ""}`));
    const jump = e => {
      e.stopPropagation();
      hovered = event.time;
      if (event.line) {
        selectedEvent = index;
        onJumpToSource(event.line, index);
      } else updateCursors();
    };
    hit.addEventListener("click", jump);
    hit.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); jump(e); } });
    return hit;
  }

  function valveChart() {
    const names = Object.keys(payload.initial_valves);
    const row = 39;
    const height = Math.max(100, 55 + names.length * row);
    const chart = makeChart("Valve command states over virtual time; click to pin a cursor", height);
    if (!names.length) {
      chart.append(svg("text", { x: LEFT, y: 60, class: "timeline-empty-label" }, "No valves configured"));
      return chart;
    }
    names.forEach((name, index) => {
      const top = 27 + index * row;
      const hi = top + 4;
      const lo = top + 21;
      const center = top + 12;
      chart.append(svg("text", { x: 18, y: center + 4, class: "timeline-track-name" }, name));
      chart.append(svg("line", { x1: LEFT, x2: RIGHT, y1: lo, y2: lo, class: "timeline-rail" }));
      const changes = payload.events.map((event, eventIndex) => ({ ...event, eventIndex }))
        .filter(event => event.kind === "valve" && event.target === name);
      let state = payload.initial_valves[name] || "CLOSED";
      let previousTime = 0;
      const yForState = value => value === "OPEN" ? hi : lo;
      const drawSegment = (from, to, value) => {
        if (to <= from) return;
        chart.append(svg("path", {
          d: `M${xAt(from)} ${yForState(value)} H${xAt(to)}`,
          class: `timeline-valve-line ${value === "OPEN" ? "valve-open" : "valve-closed"}`
        }));
      };
      for (const event of changes) {
        const x = xAt(event.time);
        drawSegment(previousTime, event.time, state);
        if (event.detail !== state) {
          chart.append(svg("path", {
            d: `M${x} ${yForState(state)} V${yForState(event.detail)}`,
            class: `timeline-valve-line ${event.detail === "OPEN" ? "valve-open" : "valve-closed"}`
          }));
        }
        state = event.detail;
        previousTime = event.time;
      }
      drawSegment(previousTime, duration, state);
      for (const event of changes) chart.append(marker(event, event.eventIndex, event.detail === "OPEN" ? hi : lo));
    });
    chart.append(overlays.at(-1).overlay);
    return chart;
  }

  function sensorChart() {
    const entries = Object.entries(payload.sensors);
    const row = 80;
    const height = Math.max(100, 55 + entries.length * row);
    const chart = makeChart("Sensor readings over virtual time, including valve-driven responses; click to pin a cursor", height);
    if (!entries.length) {
      chart.append(svg("text", { x: LEFT, y: 60, class: "timeline-empty-label" }, "No sensors configured"));
      return chart;
    }
    entries.forEach(([name, sensor], index) => {
      const top = 30 + index * row;
      const bottom = top + 49;
      const samples = [{ at: 0, value: sensorValueAt(sensor, 0) },
        ...(sensor.samples || []).filter(sample => sample.at > 0 && sample.at <= duration)];
      if (samples[0].value === null) return;
      if (samples.at(-1).at < duration) samples.push({ at: duration, value: sensorValueAt(sensor, duration) });
      const scale = sampleScale({ samples });
      const y = value => bottom - (value - scale.min) / (scale.max - scale.min) * (bottom - top);
      const color = SENSOR_COLORS[index % SENSOR_COLORS.length];
      const label = svg("text", { x: 18, y: top + 16, class: "timeline-track-name" }, name);
      chart.append(label);
      chart.append(svg("text", { x: 18, y: top + 32, class: "timeline-track-unit" }, sensor.unit));
      chart.append(svg("line", { x1: LEFT, x2: RIGHT, y1: bottom, y2: bottom, class: "timeline-rail" }));
      chart.append(svg("text", { x: LEFT - 11, y: top + 4, class: "timeline-range", "text-anchor": "end" }, nice(scale.max)));
      chart.append(svg("text", { x: LEFT - 11, y: bottom, class: "timeline-range", "text-anchor": "end" }, nice(scale.min)));
      let path = `M${LEFT} ${y(samples[0].value)}`;
      for (let i = 1; i < samples.length; i++) {
        const point = samples[i];
        const x = xAt(point.at);
        path += sensor.interpolation === "linear" ? ` L${x} ${y(point.value)}` : ` H${x} V${y(point.value)}`;
      }
      path += ` H${RIGHT}`;
      chart.append(svg("path", { d: path, class: "timeline-sensor-line", stroke: color }));
      const sourceLine = payload.sensor_read_lines[name]?.[0];
      if (sourceLine) {
        const button = document.createElementNS(SVG_NS, "text");
        button.setAttribute("x", 93);
        button.setAttribute("y", top + 32);
        button.setAttribute("class", "timeline-source-link");
        button.setAttribute("role", "button");
        button.setAttribute("tabindex", "0");
        button.textContent = `L${sourceLine} ↗`;
        button.setAttribute("aria-label", `Show ${name} read at Python line ${sourceLine}`);
        button.addEventListener("click", event => { event.stopPropagation(); onJumpToSource(sourceLine, -1); });
        button.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onJumpToSource(sourceLine, -1); }
        });
        chart.append(button);
      }
    });
    chart.append(overlays.at(-1).overlay);
    return chart;
  }

  function updateCursors() {
    if (!payload) return;
    const all = pins.map(pin => ({ ...pin, color: PINS[pin.id], label: `C${pin.id + 1}` }));
    if (hovered !== null) all.push({ id: "hover", time: hovered, color: "#faf8e8", label: "LIVE" });
    for (const { overlay, height } of overlays) {
      overlay.replaceChildren();
      for (const cursor of all) {
        const x = xAt(cursor.time);
        overlay.append(svg("line", { x1: x, x2: x, y1: 21, y2: height - 25,
          stroke: cursor.color, "stroke-width": cursor.id === "hover" ? 1.3 : 2,
          "stroke-dasharray": cursor.id === "hover" ? "5 4" : "none", opacity: cursor.id === "hover" ? .75 : .95 }));
        overlay.append(svg("text", { x: Math.max(LEFT + 13, Math.min(RIGHT - 13, x)), y: 16,
          "text-anchor": "middle", class: "timeline-cursor-label", fill: cursor.color }, cursor.label));
      }
    }
    counter.textContent = `${pins.length}/4 pinned`;
    hint.textContent = pins.length >= 4 ? "Remove a cursor to pin another time." : "Hover to inspect · Click the plot to pin · Click a valve transition to view code";
    chips.replaceChildren();
    for (const pin of pins) {
      const button = el("button", "cursor-chip");
      button.type = "button";
      button.style.setProperty("--cursor-color", PINS[pin.id]);
      button.textContent = `C${pin.id + 1}  ${displayTime(pin.time)}  ×`;
      button.setAttribute("aria-label", `Remove cursor ${pin.id + 1} at ${displayTime(pin.time)}`);
      button.onclick = () => { pins = pins.filter(entry => entry !== pin); updateCursors(); };
      chips.append(button);
    }
    if (pins.length) {
      const clear = el("button", "cursor-clear", "Clear all");
      clear.type = "button";
      clear.onclick = () => { pins = []; updateCursors(); };
      chips.append(clear);
    }
    readout.replaceChildren();
    if (!all.length) {
      readout.append(el("div", "timeline-readout-empty", "Move over either plot to inspect values at that time."));
      return;
    }
    const table = el("table", "timeline-table");
    const thead = el("thead");
    const header = el("tr");
    header.append(el("th", "", "SIGNAL"));
    for (const cursor of all) {
      const cell = el("th", "", `${cursor.label} · ${displayTime(cursor.time)}`);
      cell.style.setProperty("--cursor-color", cursor.color);
      header.append(cell);
    }
    thead.append(header);
    table.append(thead);
    const body = el("tbody");
    const valveNames = Object.keys(payload.initial_valves);
    for (const name of valveNames) {
      const row = el("tr");
      row.append(el("th", "", name));
      for (const cursor of all) {
        const state = valveStateAt(payload.initial_valves, payload.events, name, cursor.time);
        const cell = el("td", state === "OPEN" ? "state-open" : "state-closed", state);
        row.append(cell);
      }
      body.append(row);
    }
    for (const [name, sensor] of Object.entries(payload.sensors)) {
      const row = el("tr");
      row.append(el("th", "", name));
      for (const cursor of all) {
        const value = sensorValueAt(sensor, cursor.time);
        row.append(el("td", "", `${value === null ? "—" : nice(value)} ${sensor.unit === "unknown" ? "" : sensor.unit}`.trim()));
      }
      body.append(row);
      if (sensor.mode === "valve") {
        const ruleRow = el("tr");
        ruleRow.append(el("th", "", `${name} rate`));
        for (const cursor of all) {
          const { key, rate } = sensorRateAt(sensor, payload.initial_valves, payload.events, cursor.time);
          const states = sensor.valves.map((valve, i) => `${valve} ${key[i] === "1" ? "OPEN" : "CLOSED"}`).join(" · ");
          const cell = el("td", "timeline-rate", `${rate > 0 ? "+" : ""}${nice(rate)} ${sensor.unit}/s`);
          cell.title = states;
          cell.append(el("small", "", states));
          ruleRow.append(cell);
        }
        body.append(ruleRow);
      }
    }
    table.append(body);
    readout.append(table);
  }

  function render() {
    container.replaceChildren();
    overlays = [];
    if (!payload) return;
    const toolbar = el("div", "timeline-toolbar");
    const title = el("div", "timeline-toolbar-title", "VALVE STATES & SENSOR INPUTS");
    counter = el("span", "timeline-count");
    toolbar.append(title, counter);
    container.append(toolbar);
    const valveSection = el("section", "timeline-section");
    const vtitle = el("div", "timeline-section-heading");
    vtitle.append(el("h3", "", "Valve commands"), el("span", "", "OPEN / CLOSED"));
    valveSection.append(vtitle, valveChart());
    container.append(valveSection);
    const sensorSection = el("section", "timeline-section sensor-timeline");
    const stitle = el("div", "timeline-section-heading");
    stitle.append(el("h3", "", "Sensor readings"), el("span", "", "TIME PROFILES / VALVE-DRIVEN"));
    sensorSection.append(stitle, sensorChart());
    container.append(sensorSection);
    const controls = el("div", "timeline-cursor-controls");
    hint = el("span", "timeline-hint");
    chips = el("div", "timeline-cursor-chips");
    controls.append(hint, chips);
    container.append(controls);
    readout = el("div", "timeline-readout");
    container.append(readout);
    updateCursors();
  }

  return {
    load(result) {
      const simulation = result.simulation;
      if (!simulation) { this.clear(); return; }
      payload = {
        initial_valves: simulation.initial_valves || {},
        sensors: simulation.sensors || {},
        sensor_read_lines: simulation.sensor_read_lines || {},
        events: [...(result.events || [])].sort((a, b) => a.time - b.time)
      };
      duration = Math.max(.001, Number(result.virtual_time) || 0);
      pins = [];
      hovered = null;
      selectedEvent = -1;
      selectedLine = 0;
      nextPinId = 0;
      render();
      container.hidden = false;
    },
    clear() {
      payload = null;
      pins = [];
      hovered = null;
      container.replaceChildren();
      container.hidden = true;
    },
    selectEvent(index) {
      selectedEvent = index;
      selectedLine = payload?.events[index]?.line || 0;
      if (payload) render();
    },
    highlightLine(line) {
      selectedEvent = -1;
      selectedLine = line;
      if (payload) render();
    }
  };
}
