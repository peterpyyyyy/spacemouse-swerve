// Exercise the shipped browser shim, including keyboard and lost-stream failsafes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const window = new EventTarget();
const intervals = [];
const realPads = [null];
let now = 1000;
let ws;
class WebSocket {
  constructor() { ws = this; }
  close() { this.onclose(); }
}
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../spacemouse_gamepad.js'), 'utf8'), {
  window, Event, WebSocket,
  navigator: { getGamepads: () => realPads, permissions: { query: async () => ({ state: 'granted' }) } },
  document: { createElement: () => ({ style: {} }), body: { appendChild() {} } },
  performance: { now: () => now },
  setInterval: fn => intervals.push(fn), setTimeout() {},
});
const pad = window.__smBridge.pad;
const key = (type, code) => window.dispatchEvent(Object.assign(new Event(type), { code }));
ws.onopen();
ws.onmessage({ data: JSON.stringify({ a: [.5, -.4, .3, 0], b: Array(17).fill(0) }) });
assert.equal(pad.axes[0], .5);
for (const [code, index] of [['KeyJ', 6], ['KeyK', 7], ['KeyL', 5], ['Semicolon', 4]]) {
  key('keydown', code); assert.equal(pad.buttons[index].pressed, true);
  key('keyup', code); assert.equal(pad.buttons[index].pressed, false);
}
key('keydown', 'KeyJ');
now += 500;
intervals[0]();
assert.ok(pad.axes.every(v => v === 0), 'stalled stream must stop translation/rotation');
assert.ok(pad.buttons.every(b => !b.pressed), 'stalled stream must release held keys');
ws.onmessage({ data: JSON.stringify({ a: [.5, 0, 0, 0], b: Array(17).fill(0) }) });
key('keydown', 'KeyK');
ws.onclose();
assert.ok(pad.axes.every(v => v === 0));
assert.ok(pad.buttons.every(b => !b.pressed));
key('keydown', 'KeyK');
assert.ok(pad.buttons.every(b => !b.pressed), 'offline keyboard input must stay neutral');
ws.onopen();
key('keydown', 'KeyJ');
window.dispatchEvent(new Event('blur'));
assert.ok(pad.buttons.every(b => !b.pressed));
window.__smBridge.toggle();
window.__smBridge.toggle();
assert.ok(pad.buttons.every(b => !b.pressed));
console.log('PASS: gamepad axes, four keyboard mappings, release, blur, toggle, stall and disconnect');
