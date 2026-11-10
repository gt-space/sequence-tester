import test from 'node:test';
import assert from 'node:assert/strict';
import { sensorValueAt, valveStateAt, sampleScale, abortStatusAt } from '../src/timeline.js';

test('step profile holds each reading until the next time point', () => {
  const sensor = { interpolation: 'step', samples: [{at:0,value:100}, {at:2,value:200}] };
  assert.equal(sensorValueAt(sensor, 0), 100);
  assert.equal(sensorValueAt(sensor, 1.99), 100);
  assert.equal(sensorValueAt(sensor, 2), 200);
  assert.equal(sensorValueAt(sensor, 12), 200);
});

test('linear profile interpolates readings and clamps endpoints', () => {
  const sensor = { interpolation: 'linear', samples: [{at:0,value:100}, {at:2,value:300}] };
  assert.equal(sensorValueAt(sensor, 1), 200);
  assert.equal(sensorValueAt(sensor, 4), 300);
  assert.equal(sensorValueAt(sensor, -1), 100);
});

test('valve state follows the configured initial state and transition times', () => {
  const events = [
    { time: 0.5, kind: 'valve', target: 'FBB', detail: 'CLOSED' },
    { time: 0.8, kind: 'command', target: 'abort', detail: '' },
    { time: 1.0, kind: 'valve', target: 'FBB', detail: 'OPEN' },
    { time: 1.0, kind: 'valve', target: 'FBB', detail: 'CLOSED' }
  ];
  const initial = { FBB: 'OPEN' };
  assert.equal(valveStateAt(initial, events, 'FBB', 0), 'OPEN');
  assert.equal(valveStateAt(initial, events, 'FBB', 0.5), 'CLOSED');
  assert.equal(valveStateAt(initial, events, 'FBB', 1), 'CLOSED');
});

test('constant sensor profiles retain nonzero vertical range', () => {
  const scale = sampleScale({ samples: [{at:0,value:416}] });
  assert.ok(scale.max > scale.min);
  assert.ok(scale.min < 416 && scale.max > 416);
});

test('abort stage and trigger state follow the same virtual time cursors', () => {
  const events = [
    { time: 0, kind: 'abort_config', target: 'press', detail: '' },
    { time: 2, kind: 'abort_stage', target: 'press', detail: '' },
    { time: 4, kind: 'abort', target: 'press', detail: 'condition true' },
    { time: 4.5, kind: 'abort_safe', target: 'FBB', detail: 'CLOSED' }
  ];
  assert.deepEqual(abortStatusAt(events, 1), { stage: 'DEFAULT', aborted: false });
  assert.deepEqual(abortStatusAt(events, 3), { stage: 'press', aborted: false });
  assert.deepEqual(abortStatusAt(events, 4.1), { stage: 'press', aborted: true });
});
