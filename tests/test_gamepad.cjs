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
window.dispatchEvent(Object.assign(new Event('keyup'), {code:'KeyJ',ctrlKey:true}));
assert.equal(pad.buttons[6].pressed,false,'modifier changes must not leave a held trigger');
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

const nativeWindow = new EventTarget();
nativeWindow.__smNativeBridge = {};
let openedSocket = false;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../spacemouse_gamepad.js'), 'utf8'), {
  window: nativeWindow, Event,
  WebSocket: class { constructor() { openedSocket = true; } },
  navigator: { getGamepads: () => realPads },
  document: { createElement: () => ({ style: {} }), body: { appendChild() {} } },
  performance: { now: () => now }, setInterval() {}, setTimeout() {},
});
assert.equal(openedSocket, false, 'desktop mode must not connect to localhost');
const nativePad = nativeWindow.__smBridge.pad;
const receive = nativeWindow.__smNativeBridge.receive;
receive({a:[.8,-.6,.2,0],b:Array(17).fill(0),paused:false});
assert.equal(nativePad.axes[0], .8);
nativeWindow.dispatchEvent(Object.assign(new Event('keydown'), {code:'KeyK'}));
assert.equal(nativePad.buttons[7].pressed,true);
receive({a:[0,0,0,0],b:Array(17).fill(0),paused:true});
assert.ok(nativePad.buttons.every(b => !b.pressed));
nativeWindow.dispatchEvent(Object.assign(new Event('keydown'), {code:'KeyJ'}));
assert.ok(nativePad.buttons.every(b => !b.pressed), 'paused desktop must ignore keyboard input');
receive({a:[0,0,0,0],b:Array(17).fill(0),paused:false});
nativeWindow.dispatchEvent(Object.assign(new Event('keydown'), {code:'KeyJ'}));
assert.equal(nativePad.buttons[6].pressed,true);
console.log('PASS: native desktop transport, pause and resume without WebSocket');
nativeWindow.__smNativeBridge.controlsAllowed = () => false;
receive({a:[1,1,1,0],b:Array(17).fill(1),paused:false});
assert.ok(nativePad.axes.every(v=>v===0));
assert.ok(nativePad.buttons.every(b=>!b.pressed));
assert.equal(nativeWindow.__smNativeBridge.blocked,true);
nativeWindow.__smNativeBridge.controlsAllowed = () => true;
receive({a:[.5,0,0,0],b:Array(17).fill(0),paused:false});
assert.equal(nativePad.axes[0],.5);
console.log('PASS: menus lock cap input; gameplay unlocks it');
const policyWindow={__sim:{ui:{screen:'menu',pop:null}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../desktop_policy.js'),'utf8'),{
  window:policyWindow,location:{hostname:'tylerhandel.github.io'},
});
for (const screen of ['menu','pause','results','controls','editor','tuning']) {
  policyWindow.__sim.ui.screen=screen;
  assert.equal(policyWindow.__smNativeBridge.controlsAllowed(),false,screen);
}
policyWindow.__sim.ui.screen='hud';
assert.equal(policyWindow.__smNativeBridge.controlsAllowed(),true);
policyWindow.__sim.ui.pop={};
assert.equal(policyWindow.__smNativeBridge.controlsAllowed(),false);
console.log('PASS: actual REBUILT screen policy including HUD popovers');
