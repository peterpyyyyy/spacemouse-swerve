/* SpaceMouse -> virtual "standard" (Xbox layout) gamepad for browser FRC simulators.
   Injected via bookmarklet; receives processed sticks from spacemouse_bridge.py over WebSocket.
   Click the bookmarklet again (or the badge) to toggle the virtual pad on/off. */
(() => {
  if (window.__smBridge) { window.__smBridge.toggle(); return; }
  const WS_URL = 'ws://127.0.0.1:8765/ws';
  const mkBtn = () => ({ pressed: false, touched: false, value: 0 });
  const pad = {
    id: 'SpaceMouse Bridge (STANDARD GAMEPAD Vendor: 045e Product: 028e)',
    index: 0, connected: true, mapping: 'standard', timestamp: performance.now(),
    axes: [0, 0, 0, 0], buttons: Array.from({ length: 17 }, mkBtn),
    vibrationActuator: null, hapticActuators: [],
  };
  const origGet = navigator.getGamepads.bind(navigator);
  let enabled = true, online = false, ws = null, lastMsg = 0, perm = '';
  const checkPerm = async () => {
    for (const n of ['local-network-access', 'loopback-network']) {
      try { perm = (await navigator.permissions.query({ name: n })).state; return; } catch (e) { /* unknown name */ }
    }
  };

  /* Hide real controllers so the page always picks index 0 = our pad. */
  navigator.getGamepads = () => (enabled ? [pad, null, null, null] : origGet());
  const block = (e) => { if (enabled && e.gamepad !== pad) e.stopImmediatePropagation(); };
  window.addEventListener('gamepadconnected', block, true);
  window.addEventListener('gamepaddisconnected', block, true);
  const fire = (type) => {
    const ev = new Event(type);
    Object.defineProperty(ev, 'gamepad', { value: pad });
    window.dispatchEvent(ev);
  };

  const badge = document.createElement('div');
  badge.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:2147483647;padding:6px 12px;' +
    'border-radius:8px;font:600 13px system-ui,sans-serif;color:#fff;cursor:pointer;' +
    'box-shadow:0 2px 8px rgba(0,0,0,.4);user-select:none';
  badge.title = 'SpaceMouse bridge - click to toggle';
  document.body.appendChild(badge);
  const paint = () => {
    const s = !enabled ? ['#555', 'SpaceMouse: 已关闭 (点击开启)']
      : online ? ['#1f9d55', '● SM']
      : perm === 'denied' ? ['#c0392b', 'SpaceMouse: 浏览器拦截了本地连接 → 地址栏左侧网站设置里允许"本地网络访问"后刷新']
      : perm === 'prompt' ? ['#d35400', 'SpaceMouse: 浏览器弹窗询问时请点"允许" (本地网络/设备访问)']
      : ['#c0392b', 'SpaceMouse: 桥接未运行 (python spacemouse_bridge.py)'];
    badge.style.background = s[0];
    badge.textContent = s[1];
    badge.style.padding = online && enabled ? '2px 7px' : '6px 12px';
    badge.style.opacity = online && enabled ? '0.75' : '1';
  };

  const zero = () => {
    bridgeBtns = [];
    pad.axes = [0, 0, 0, 0];
    compose();
  };

  /* Right-hand keyboard -> gamepad buttons (the left hand is on the SpaceMouse). These keys are
     swallowed so the game doesn't also see them (e.g. J/L are its keyboard-rotate keys). */
  const KEYS = { KeyJ: 6, KeyK: 7, KeyL: 5, Semicolon: 4 };   /* J=LT  K=RT  L=RB  ;=LB */
  const held = new Set();
  let bridgeBtns = [];
  const compose = () => {
    pad.buttons = Array.from({ length: 17 }, (_, i) => {
      const v = Math.max(bridgeBtns[i] || 0, held.has(i) ? 1 : 0);
      return { pressed: v > 0.5, touched: v > 0, value: v };
    });
    pad.timestamp = performance.now();
  };
  const onKey = (down) => (e) => {
    const b = KEYS[e.code];
    if (!enabled || b === undefined || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    if (down) held.add(b); else held.delete(b);
    compose();
  };
  window.addEventListener('keydown', onKey(true), true);
  window.addEventListener('keyup', onKey(false), true);
  window.addEventListener('blur', () => { held.clear(); compose(); });

  const connect = () => {
    try { ws = new WebSocket(WS_URL); } catch (e) { setTimeout(connect, 1000); return; }
    ws.onopen = () => { online = true; paint(); };
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      pad.axes = d.a;
      bridgeBtns = d.b;
      compose();
      lastMsg = pad.timestamp;
    };
    ws.onclose = () => { online = false; zero(); checkPerm().then(paint); setTimeout(connect, 1000); };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
  };

  /* Failsafe: if the stream stalls, stop the robot. */
  setInterval(() => { if (online && performance.now() - lastMsg > 300) zero(); }, 100);

  const toggle = () => {
    enabled = !enabled;
    held.clear();
    zero();
    fire(enabled ? 'gamepadconnected' : 'gamepaddisconnected');
    paint();
  };
  badge.onclick = toggle;
  window.__smBridge = { toggle, pad };
  paint();
  connect();
  fire('gamepadconnected');
})();
