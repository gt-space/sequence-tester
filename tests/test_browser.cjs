/* Real-browser Pyodide regression for the original silent timeline truncation.
 * Run with: NODE_PATH=/tmp/sequence-browser/node_modules node tests/test_browser.cjs
 */
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { test } = require("node:test");
const { mkdirSync, writeFileSync } = require("node:fs");
const { chromium } = require("playwright");

const HOST = "http://127.0.0.1:8765";

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt++) {
    try {
      const result = await fetch(HOST);
      if (result.ok) return;
    } catch { /* server still starting */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Static server did not become available");
}

test("Pyodide browser regression: valve history, cursors, saved tests, API, and abort stages", { timeout: 180000 }, async () => {
  const server = spawn("python3", ["-m", "http.server", "8765", "--bind", "127.0.0.1"],
    { stdio: "ignore" });
  let browser;
  let page;
  const pageErrors = [];
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"],
      ...(process.env.SEQUENCE_BROWSER_BINARY ? { executablePath: process.env.SEQUENCE_BROWSER_BINARY } : {}) });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto(HOST);
    await page.waitForFunction(() => document.querySelector("#engine-status")?.textContent?.includes("Python runtime ready"),
      null, { timeout: 70000 });

    const source = [
      "CMV.open()",
      "for _ in range(500):",
      "    CMV.open()",
      "    wait_for(20*ms)",
      "CMV.close()",
      "CFILL.open()",
      "wait_for(2*s)",
      "CFILL.close()",
    ].join("\n");
    const environment = {
      valves: ["CMV", "CFILL"],
      sensors: [{ name: "CTPT", unit: "psi", mode: "valve", initial: 200,
        valves: ["CMV", "CFILL"],
        rates: { "00": 0, "01": 1, "10": 2, "11": -2 }, min: 0, max: 1000 }],
    };
    await page.locator("#file-input").setInputFiles({ name: "long-cfill-regression.py", mimeType: "text/x-python", buffer: Buffer.from(source) });
    await page.locator("#environment-file-input").setInputFiles({
      name: "test-environment.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(environment)),
    });
    assert.equal(await page.locator("#sequence-name").inputValue(), "long-cfill-regression");

    await page.locator("#simulate").click();
    await page.waitForFunction(() => ["pass", "warning"].includes(document.querySelector("#validation-state")?.dataset.state) &&
      document.querySelector('[data-check="runtime"]')?.dataset.state === "pass", null, { timeout: 30000 });
    assert.match(await page.locator("#diagnostics").textContent(), /Collapsed 500 repeated valve commands/);
    assert.equal(await page.locator("#event-count").textContent(), "4");
    assert.equal(await page.locator("#saved-count").textContent(), "1");
    assert.match(await page.locator(".saved-load").first().textContent(), /long-cfill-regression\.py/);
    // The UI runs at 5× real time, so scheduler overshoot can move the end by milliseconds.
    const duration = Number.parseFloat(await page.locator("#virtual-time").textContent());
    assert.ok(duration >= 12 && duration < 13, `Unexpected end time: ${duration}s`);
    assert.equal(await page.locator(".timeline-interactive").count(), 2);

    const valvePlot = page.locator(".timeline-interactive").first();
    const sensorPlot = page.locator(".timeline-interactive").last();
    await valvePlot.scrollIntoViewIfNeeded();
    const valveBounds = await valvePlot.boundingBox();
    const hoverAt = (bounds, fraction) => ({
      x: bounds.x + bounds.width * (150 + 819 * fraction) / 1000,
      y: bounds.y + Math.min(90, bounds.height / 2),
    });
    await page.mouse.move(...Object.values(hoverAt(valveBounds, 0.9)));
    await page.waitForFunction(() => document.querySelector(".timeline-table thead")?.textContent?.includes("LIVE"));
    const cursorTimes = async () => (await page.locator(".timeline-table thead th").allTextContents())
      .slice(1).map(label => ({ label, time: Number.parseFloat(label.split("·")[1]) }));
    let times = await cursorTimes();
    assert.ok(times.some(cursor => cursor.label.startsWith("LIVE") && Math.abs(cursor.time - duration * 0.9) < 0.1),
      `Late live cursor: ${JSON.stringify(times)}`);
    const cfillStates = page.locator(".timeline-table tbody tr").filter({ has: page.locator("th", { hasText: "CFILL" }) }).locator("td");
    assert.equal(await cfillStates.last().textContent(), "OPEN");

    const late = hoverAt(valveBounds, 0.9);
    await page.mouse.click(late.x, late.y);
    assert.match(await page.locator(".timeline-count").textContent(), /1\/4 pinned/);
    await sensorPlot.scrollIntoViewIfNeeded();
    const sensorBounds = await sensorPlot.boundingBox();
    const early = hoverAt(sensorBounds, 0.15);
    await page.mouse.move(early.x, early.y);
    times = await cursorTimes();
    assert.ok(times.some(cursor => cursor.label.startsWith("C1") && Math.abs(cursor.time - duration * 0.9) < 0.1),
      `Pinned cursor: ${JSON.stringify(times)}`);
    assert.ok(times.some(cursor => cursor.label.startsWith("LIVE") && Math.abs(cursor.time - duration * 0.15) < 0.1),
      `Early live cursor: ${JSON.stringify(times)}`);
    assert.deepEqual(await cfillStates.allTextContents(), ["OPEN", "CLOSED"]);
    assert.equal(pageErrors.length, 0, `Browser exceptions: ${pageErrors.join("; ")}`);

    // A library entry restores both the Python script and its environment.
    await page.locator("#source").fill("CMV.close()");
    page.once("dialog", dialog => dialog.accept());
    await page.locator(".saved-load").first().click();
    assert.equal(await page.locator("#source").inputValue(), source);
    assert.deepEqual(JSON.parse(await page.locator("#mapping").inputValue()).valves.map(valve => valve.name), ["CMV", "CFILL"]);
    await page.locator("#sequence-name").fill("cfill-followup");
    await page.locator("#save-sequence").click();
    assert.equal(await page.locator("#saved-count").textContent(), "2");
    await page.reload();
    await page.waitForFunction(() => document.querySelector("#saved-count")?.textContent === "2");
    assert.equal(await page.locator("#saved-count").textContent(), "2");
    assert.equal(await page.locator("#sequence-name").inputValue(), "cfill-followup");
    await page.locator(".saved-load").filter({ hasText: "long-cfill-regression" }).click();
    assert.equal(await page.locator("#sequence-name").inputValue(), "long-cfill-regression");
    assert.equal(await page.locator("#source").inputValue(), source);

    // The public Luna binding accepts booleans, not truthy string substitutes.
    await page.locator("#source").fill("CMV.actuate('CLOSED')");
    await page.locator("#validate").click();
    await page.waitForFunction(() => document.querySelector('[data-check="api"]')?.dataset.state === "fail");
    assert.match(await page.locator("#diagnostics").textContent(), /expects bool/);

    // Abort stages must render their trigger and delayed safing as well as the valve timeline.
    await page.locator('[data-example="abort"]').click();
    await page.locator("#simulate").click();
    await page.waitForFunction(() => ["pass", "warning"].includes(document.querySelector("#validation-state")?.dataset.state) &&
      document.querySelector('[data-check="runtime"]')?.dataset.state === "pass" &&
      document.querySelector(".abort-stage-card")?.textContent?.includes("TRIGGERED"), null, { timeout: 30000 });
    assert.equal(await page.locator(".abort-stage-card").count(), 1);
    assert.ok(await page.locator(".timeline-abort-marker").count() >= 3);
    const abortPlot = page.locator(".timeline-interactive").first();
    await abortPlot.scrollIntoViewIfNeeded();
    const abortBounds = await abortPlot.boundingBox();
    await page.mouse.move(...Object.values(hoverAt(abortBounds, 1)));
    await page.waitForFunction(() => document.querySelector(".timeline-table")?.textContent?.includes("ABORTED"));
    const abortedRows = page.locator(".timeline-table tbody tr");
    assert.equal(await abortedRows.filter({ has: page.locator("th", { hasText: "press_valve" }) }).locator("td").last().textContent(), "CLOSED");
    assert.equal(await abortedRows.filter({ has: page.locator("th", { hasText: "vent_valve" }) }).locator("td").last().textContent(), "OPEN");
    assert.equal(pageErrors.length, 0, `Browser exceptions: ${pageErrors.join("; ")}`);
    await page.close();
  } catch (error) {
    // Keep enough evidence in CI to distinguish a simulator failure from an assertion or UI bug.
    if (page && !page.isClosed()) {
      const state = await page.evaluate(() => ({
        engineStatus: document.querySelector("#engine-status")?.textContent,
        validationState: document.querySelector("#validation-state")?.textContent,
        checks: [...document.querySelectorAll("[data-check]")].map(el => [el.dataset.check, el.dataset.state]),
        diagnostics: document.querySelector("#diagnostics")?.textContent,
        virtualTime: document.querySelector("#virtual-time")?.textContent,
        eventCount: document.querySelector("#event-count")?.textContent,
        savedCount: document.querySelector("#saved-count")?.textContent,
      })).catch(e => ({ captureError: String(e) }));
      mkdirSync("browser-test-artifacts", { recursive: true });
      writeFileSync("browser-test-artifacts/state.json", JSON.stringify({ failure: String(error), pageErrors, state }, null, 2));
      await page.screenshot({ path: "browser-test-artifacts/failure.png", fullPage: true }).catch(() => {});
      console.error("Browser failure state:", JSON.stringify(state));
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill("SIGTERM");
  }
});
