import test from 'node:test';
import assert from 'node:assert/strict';
import { createTimelineView } from '../src/timeline.js';

class MockElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this.handlers = {};
    this.className = '';
    this.textContent = '';
    this.style = { setProperty() {} };
    this.classList = {
      add: (...classes) => { this.className += ` ${classes.join(' ')}`; },
    };
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
}

globalThis.document = {
  createElement: tag => new MockElement(tag),
  createElementNS: (ns, tag) => new MockElement(tag),
};

function nodes(root) {
  return [root, ...root.children.flatMap(nodes)];
}
function matches(node, name) {
  return `${node.className} ${node.attrs.class || ''}`.split(/\s+/).includes(name);
}

test('abort timeline renders synchronized markers, source links, and condition coverage', () => {
  const container = new MockElement('div');
  const jumped = [];
  const timeline = createTimelineView({ container, onJumpToSource: line => jumped.push(line) });
  const result = {
    virtual_time: 4.5,
    events: [
      { time: 0, kind: 'abort_config', target: 'press', detail: 'created', line: 1 },
      { time: 0, kind: 'abort_stage', target: 'press', detail: 'active', line: 2 },
      { time: 0, kind: 'valve', target: 'FBB', detail: 'OPEN', line: 3 },
      { time: 3, kind: 'abort', target: 'press', detail: 'FTPT > 450*psi', line: 1 },
      { time: 3.5, kind: 'valve', target: 'FBB', detail: 'CLOSED', line: 1, origin: 'abort' },
      { time: 3.5, kind: 'abort_safe', target: 'FBB', detail: 'CLOSED after 500ms', line: 1 },
    ],
    simulation: {
      initial_valves: { FBB: 'CLOSED' },
      sensors: { FTPT: { unit: 'psi', interpolation: 'step', samples: [{ at: 0, value: 400 }, { at: 3, value: 500 }] } },
      sensor_read_lines: { FTPT: [1] },
      abort_stages: [{ name: 'press', condition: 'FTPT > 450*psi', defined_line: 1,
        activated: [0], triggered: 3, safe_states: [{ name: 'FBB', state: 'CLOSED', delay_ms: 500 }] }],
      aborted: true,
    },
  };
  timeline.load(result);
  assert.equal(container.hidden, false);
  assert.equal(nodes(container).filter(node => matches(node, 'timeline-section')).length, 3);
  assert.equal(nodes(container).filter(node => matches(node, 'timeline-abort-marker')).length, 3);
  const card = nodes(container).find(node => matches(node, 'abort-stage-card'));
  assert.ok(card);
  assert.ok(nodes(card).some(node => String(node.textContent).includes('TRIGGERED')));
  card.onclick();
  assert.deepEqual(jumped, [1]);
  timeline.highlightLine(1);
  timeline.selectEvent(3);
});

test('untriggered stage displays coverage warning in plot card', () => {
  const container = new MockElement('div');
  const timeline = createTimelineView({ container, onJumpToSource() {} });
  timeline.load({ events: [], virtual_time: 2, simulation: {
    initial_valves: {}, sensors: {}, sensor_read_lines: {},
    abort_stages: [{ name: 'press', condition: 'FTPT > 450*psi', defined_line: 1,
      activated: [0], triggered: null, safe_states: [] }],
  } });
  assert.ok(nodes(container).some(node => String(node.textContent).includes('CONDITION NEVER TRIGGERED')));
  assert.equal(nodes(container).filter(node => matches(node, 'timeline-abort-marker')).length, 0);
});
