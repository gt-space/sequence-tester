import test from 'node:test';
import assert from 'node:assert/strict';
import { sensorValueAt, valveStateAt, sensorRateAt, sampleScale } from '../src/timeline.js';

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

test('valve-driven cursor readout selects the active truth-table rate', () => {
  const sensor = { mode: 'valve', valves: ['CISO', 'CMV'], rates: {'00':0,'01':-25,'10':40,'11':0} };
  const initial = { CISO:'CLOSED', CMV:'CLOSED' };
  const events = [
    {time:1,kind:'valve',target:'CISO',detail:'OPEN'},
    {time:2,kind:'valve',target:'CMV',detail:'OPEN'},
    {time:3,kind:'valve',target:'CISO',detail:'CLOSED'}
  ];
  assert.deepEqual(sensorRateAt(sensor,initial,events,0),{key:'00',rate:0});
  assert.deepEqual(sensorRateAt(sensor,initial,events,1.5),{key:'10',rate:40});
  assert.deepEqual(sensorRateAt(sensor,initial,events,2.5),{key:'11',rate:0});
  assert.deepEqual(sensorRateAt(sensor,initial,events,3.5),{key:'01',rate:-25});
});
