"""SpaceMouse -> browser FRC simulator bridge.

Reads the SpaceMouse, runs it through the same processing as swerve_sim.py (calibration,
pan/tilt fusion, twist decoupling, expo) and streams the result as a standard Xbox-layout
gamepad to a browser page over ws://127.0.0.1:8765/ws.  In the browser, the bookmarklet from
http://127.0.0.1:8765/ installs a fake navigator.getGamepads() fed by this stream.

Gamepad mapping (WPILib / most sims convention):
  left stick  X/Y = translation (driver frame, push away = stick up)
  right stick X   = rotation   (twist clockwise = stick right, unless the preset inverts it)
  SpaceMouse buttons -> per-simulator preset (P key cycles presets, see PRESETS)

Run:  python spacemouse_bridge.py   [--port 8765] [--anti-deadzone 0.10]
"""
import asyncio
import json
import math
import os
import sys
import threading
from runtime_paths import state_path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
import pygame
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from swerve_sim import (C_BG, C_DIM, C_OUT, C_PAN, C_ROT, C_TEXT, C_TILT, MODES, MODE_DESC,
                        InputProcessor, SpaceMouseInput, SpaceMouseView, clamp, ui_font)

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM_PATH = os.path.join(HERE, "spacemouse_gamepad.js")
W, H = 960, 470


def arg(name, default, cast):
    if name in sys.argv:
        return cast(sys.argv[sys.argv.index(name) + 1])
    return default


PORT = arg("--port", 8765, int)
SETTINGS_PATH = state_path("bridge_settings.json")


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(d):
    s = load_settings()
    s.update(d)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


# Per-simulator tuning. buttons = (gamepad index for SpaceMouse left, right button) or None:
# pressing the buttons jolts the cap and 3DxWare pops its own menu, so by default they're unused
# and game actions come from right-hand keys mapped to gamepad buttons in spacemouse_gamepad.js.
PRESETS = [
    dict(key="rebuilt", name="REBUILT Sim 2026", url="https://tylerhandel.github.io/rebuilt-sim-2026/",
         invert_rot=False, expo=0.0, buttons=None,     # the game already squares the sticks
         note="右手键盘: J 吸球  K 射球  L 传球  ; 吐球 (SpaceMouse 自带按键不映射)"),
    dict(key="frc4206", name="frc4206.com", url="https://www.frc4206.com/",
         invert_rot=True, expo=0.35, buttons=None,     # its 3D view draws rotation mirrored
         note="右手键盘: J = LT 自动瞄准  K = RT 开飞轮 (SpaceMouse 自带按键不映射)"),
]
BTN_NAMES = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT"]


def anti_deadzone(v, adz):
    """Lift non-zero values over the simulator's own per-axis deadzone (e.g. |v| < 0.1 -> 0)."""
    if abs(v) < 0.01 or adz <= 0:
        return 0.0 if abs(v) < 0.01 else v
    return math.copysign(adz + (1.0 - adz) * min(abs(v), 1.0), v)


# ---------------------------------------------------------------- web side
INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>SpaceMouse Bridge</title>
<style>body{font:15px/1.6 system-ui,'Microsoft YaHei UI','PingFang SC',sans-serif;background:#16181d;color:#dde;
max-width:760px;margin:40px auto;padding:0 20px}a.bm{display:inline-block;padding:10px 18px;
background:#1f9d55;color:#fff;border-radius:8px;text-decoration:none;font-weight:700;font-size:17px}
code{background:#2a2d35;padding:2px 6px;border-radius:4px}li{margin:6px 0}</style>
<h2>SpaceMouse &rarr; 浏览器 FRC 模拟器</h2>
<p>状态: <b id="st">检测中...</b></p>
<ol>
<li>把这个按钮 <b>拖到书签栏</b> (书签栏不显示就按 Ctrl+Shift+B, Mac 是 Cmd+Shift+B):
 <a class="bm" id="bm" href="#">SpaceMouse 手柄</a><br>
 <small style="color:#889">这是加载器, 每次从本机桥接加载最新代码, 以后更新不用重新拖.
 万一某个网站加载失败, 改用完整版: <a id="bmfull" href="#" style="color:#7bf">SpaceMouse 手柄(完整版)</a></small></li>
<li>打开模拟器:
 <a href="https://tylerhandel.github.io/rebuilt-sim-2026/" target="_blank" style="color:#7bf">REBUILT Sim 2026</a>
 (完整 2026 场地, 直接玩; 桥接窗口按 P 选对应预设)
 或 <a href="https://www.frc4206.com/" target="_blank" style="color:#7bf">frc4206.com</a> (跑队伍代码, 无场地)</li>
<li>在模拟器页面点一下书签. 左下角出现绿色小标 <code>● SM</code> 即可.
 若浏览器询问是否允许访问本地网络/设备, 选 <b>允许</b>.</li>
<li>再点一次书签或左下角徽标 = 关闭虚拟手柄 (恢复真实手柄).</li>
</ol>
<p>映射: 左摇杆 = 平移, 右摇杆 X = 旋转. SpaceMouse 自带按键不映射.<br>
右手键盘 &rarr; 手柄按键: <code>J</code> = LT (吸球) &nbsp; <code>K</code> = RT (射球) &nbsp;
<code>L</code> = RB (传球) &nbsp; <code>;</code> = LB (吐球). 游戏自己的其它键盘按键照常可用.</p>
<p>备选: 按 F12 打开控制台, 粘贴 <a href="/shim.js" style="color:#7bf">shim.js</a> 的全部内容回车.</p>
<script>
const code = __SHIM__;
const loader = "(()=>{if(window.__smBridge){window.__smBridge.toggle();return}" +
  "const s=document.createElement('script');s.src='http://" + location.host + "/shim.js?'+Date.now();" +
  "s.onerror=()=>alert('SpaceMouse: \u65e0\u6cd5\u4ece " + location.host + " \u52a0\u8f7d. " +
  "\u8bf7\u786e\u8ba4 spacemouse_bridge.py \u5728\u8fd0\u884c, \u5e76\u5728\u6d4f\u89c8\u5668\u8be2\u95ee\u65f6\u5141\u8bb8\u672c\u5730\u7f51\u7edc\u8bbf\u95ee.');" +
  "document.documentElement.appendChild(s)})()";
document.getElementById('bm').href = 'javascript:' + encodeURIComponent(loader);
document.getElementById('bmfull').href = 'javascript:' + encodeURIComponent(code);
const st = document.getElementById('st');
const ws = new WebSocket('ws://' + location.host + '/ws');
ws.onopen = () => st.textContent = '桥接运行中';
ws.onmessage = (m) => { const d = JSON.parse(m.data);
  st.textContent = '桥接运行中  LX ' + d.a[0].toFixed(2) + '  LY ' + d.a[1].toFixed(2) + '  RX ' + d.a[2].toFixed(2); };
ws.onclose = () => st.textContent = '桥接未运行';
</script>"""


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.msg = json.dumps({"a": [0, 0, 0, 0], "b": [0] * 17})
        self.clients = set()
        self.error = None

    def publish(self, axes, buttons):
        m = json.dumps({"a": [round(a, 4) for a in axes], "b": buttons})
        with self.lock:
            self.msg = m

    def process_request(self, connection, request):
        path = request.path.split("?")[0]
        if path == "/ws":
            return None
        if path == "/shim.js":
            body = open(SHIM_PATH, encoding="utf-8").read()
            return self._resp(200, body, "application/javascript; charset=utf-8")
        if path in ("/", "/index.html"):
            shim = open(SHIM_PATH, encoding="utf-8").read()
            html = INDEX_HTML.replace("__SHIM__", json.dumps(shim).replace("</", "<\\/"))
            return self._resp(200, html, "text/html; charset=utf-8")
        return self._resp(404, "not found", "text/plain")

    @staticmethod
    def _resp(code, text, ctype):
        body = text.encode("utf-8")
        headers = Headers([("Content-Type", ctype), ("Content-Length", str(len(body))),
                           ("Cache-Control", "no-store"), ("Access-Control-Allow-Origin", "*")])
        return Response(code, "OK" if code == 200 else "Not Found", headers, body)

    async def handler(self, ws):
        self.clients.add(ws)
        try:
            last, last_t = None, 0.0
            while True:
                with self.lock:
                    m = self.msg
                # Send on change, plus a ~10 Hz keepalive so the page failsafe stays happy.
                if m != last or asyncio.get_running_loop().time() - last_t > 0.1:
                    await ws.send(m)
                    last, last_t = m, asyncio.get_running_loop().time()
                await asyncio.sleep(1 / 120)
        except Exception:
            pass
        finally:
            self.clients.discard(ws)

    async def main(self):
        async with serve(self.handler, "127.0.0.1", PORT, process_request=self.process_request,
                         compression=None):
            await asyncio.Future()

    def start(self):
        def run():
            try:
                asyncio.run(self.main())
            except Exception as e:  # e.g. port already in use
                self.error = str(e)
        threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- app
class BridgeApp:
    def __init__(self, frames=0):
        self.frames_limit = frames
        pygame.init()
        flags = 0 if frames == 0 else pygame.HIDDEN
        self.screen = pygame.display.set_mode((W, H), flags)
        pygame.display.set_caption("SpaceMouse Bridge -> http://127.0.0.1:%d" % PORT)
        self.f = ui_font(17)
        self.f_small = ui_font(14)
        self.f_big = ui_font(24, bold=True)
        self.sm = SpaceMouseInput()
        self.proc = InputProcessor()
        self.view = SpaceMouseView((420, 330))
        self.adz = arg("--anti-deadzone", 0.10, float)
        keys = [p["key"] for p in PRESETS]
        saved = load_settings().get("preset")
        self.apply_preset(keys.index(saved) if saved in keys else 0)
        self.paused = False
        self.bridge = Bridge()
        self.bridge.start()
        self.axes = [0.0] * 4
        self.btns = [0] * 17
        self.raw = [0.0] * 6

    def text(self, s, pos, col=C_TEXT, font=None):
        self.screen.blit((font or self.f).render(s, True, col), pos)

    def apply_preset(self, i):
        self.preset_i = i
        p = PRESETS[i]
        self.preset = p
        self.invert_rot = p["invert_rot"]
        self.proc.expo = p["expo"]

    def handle_key(self, k):
        p = self.proc
        if k == pygame.K_p:
            self.apply_preset((self.preset_i + 1) % len(PRESETS))
            save_settings({"preset": self.preset["key"]})
        elif pygame.K_1 <= k <= pygame.K_5:
            p.mode = MODES[k - pygame.K_1]
        elif k == pygame.K_l:
            p.cal.enabled = not p.cal.enabled
        elif k == pygame.K_g:
            p.snap_deg = 0.0 if p.snap_deg else 15.0
        elif k == pygame.K_c:
            p.decouple = not p.decouple
        elif k == pygame.K_LEFTBRACKET:
            p.deadband = clamp(p.deadband - 0.01, 0.0, 0.3)
        elif k == pygame.K_RIGHTBRACKET:
            p.deadband = clamp(p.deadband + 0.01, 0.0, 0.3)
        elif k == pygame.K_SEMICOLON:
            p.expo = clamp(p.expo - 0.05, 0.0, 0.9)
        elif k == pygame.K_QUOTE:
            p.expo = clamp(p.expo + 0.05, 0.0, 0.9)
        elif k == pygame.K_7:
            p.rot_gain = clamp(p.rot_gain - 0.1, 0.3, 3.0)
        elif k == pygame.K_8:
            p.rot_gain = clamp(p.rot_gain + 0.1, 0.3, 3.0)
        elif k == pygame.K_MINUS:
            self.adz = clamp(round(self.adz - 0.02, 2), 0.0, 0.3)
        elif k == pygame.K_EQUALS:
            self.adz = clamp(round(self.adz + 0.02, 2), 0.0, 0.3)
        elif k == pygame.K_SPACE:
            self.paused = not self.paused
        elif k == pygame.K_v:
            self.invert_rot = not self.invert_rot
        elif k == pygame.K_r:
            self.sm.scan()

    def update(self):
        self.raw, sbtn = self.sm.read()
        t, rot = self.proc.process(self.raw)
        lx, ly, rx = t.x, -t.y, (-rot if self.invert_rot else rot)  # stick up = negative Y
        self.axes = [anti_deadzone(lx, self.adz), anti_deadzone(ly, self.adz),
                     anti_deadzone(rx, self.adz), 0.0]
        self.btns = [0] * 17
        if self.preset["buttons"]:
            bl, br = self.preset["buttons"]
            self.btns[bl] = 1 if sbtn[0] else 0
            self.btns[br] = 1 if sbtn[1] else 0
        if self.paused:
            self.axes, self.btns = [0.0] * 4, [0] * 17
        self.bridge.publish(self.axes, self.btns)

    def draw_stick(self, c, x, y, col, label):
        pygame.draw.circle(self.screen, (60, 64, 76), c, 56, 2)
        pygame.draw.line(self.screen, (50, 54, 64), (c[0] - 56, c[1]), (c[0] + 56, c[1]))
        pygame.draw.line(self.screen, (50, 54, 64), (c[0], c[1] - 56), (c[0], c[1] + 56))
        p = (int(c[0] + x * 56), int(c[1] + y * 56))
        pygame.draw.line(self.screen, col, c, p, 3)
        pygame.draw.circle(self.screen, col, p, 9)
        self.text(label, (c[0] - 56, c[1] + 62), C_DIM, self.f_small)

    def draw(self):
        s = self.screen
        s.fill(C_BG)
        self.text("SpaceMouse → 浏览器模拟器 (虚拟 Xbox 手柄)", (16, 10), C_TEXT, self.f_big)
        s.blit(self.view.render(self.raw), (16, 50))
        pygame.draw.rect(s, (70, 74, 86), (16, 50, 420, 330), 1)

        x = 460
        if self.bridge.error:
            st, col = f"服务器错误: {self.bridge.error[:60]}", (255, 90, 90)
        else:
            n = len(self.bridge.clients)
            st, col = (f"浏览器已连接: {n}", C_OUT) if n else ("等待浏览器连接 (点书签)", C_TILT)
        self.text(f"设备: {self.sm.name}", (x, 52), C_OUT if self.sm.joy else (255, 90, 90))
        self.text(f"网页: http://127.0.0.1:{PORT}   {st}", (x, 76), col)
        self.text(f"P 模拟器预设: {self.preset['name']}", (x, 100), C_OUT)
        if self.paused:
            self.text("已暂停输出", (x + 320, 250), (255, 90, 90))

        self.draw_stick((x + 70, 190), self.axes[0], self.axes[1], C_OUT, "左摇杆 = 平移")
        self.draw_stick((x + 220, 190), self.axes[2], 0.0, C_ROT, "右摇杆X = 旋转")
        self.text(f"LX {self.axes[0]:+.2f}", (x + 320, 150))
        self.text(f"LY {self.axes[1]:+.2f}", (x + 320, 174))
        self.text(f"RX {self.axes[2]:+.2f}", (x + 320, 198), C_ROT)
        b = " ".join(BTN_NAMES[i] for i in range(len(BTN_NAMES)) if self.btns[i])
        self.text(f"按键 {b or '-'}", (x + 320, 222), C_DIM)

        p = self.proc
        lines = [
            (f"1-5 融合模式: {p.mode}  {MODE_DESC[p.mode]}", C_PAN),
            (f"L 方向校准: {'ON' if p.cal.enabled else 'OFF'}   G 轴吸附: {'ON' if p.snap_deg else 'OFF'}"
             f"   C 解耦: {'ON' if p.decouple else 'OFF'}", C_TEXT),
            (f"[ ] 死区 {p.deadband:.2f}   ; ' expo {p.expo:.2f}   7 8 扭转灵敏度 {p.rot_gain:.1f}", C_TEXT),
            (f"- = 反死区 {self.adz:.2f} (抵消模拟器自带的 0.1 死区)", C_TILT),
            (f"V 反转旋转: {'ON' if self.invert_rot else 'OFF'}", C_ROT),
            ("Space 暂停输出   R 重新扫描设备   Esc 退出", C_DIM),
            (self.preset["note"], C_DIM),
        ]
        for i, (l, c) in enumerate(lines):
            self.text(l, (x, 280 + i * 25), c, self.f_small if i >= 5 else self.f)
        self.text("用 swerve_sim.py 的 K 向导做的校准会自动加载 (calibration.json)",
                  (16, 392), C_DIM, self.f_small)
        self.text("速度上限/旋转速度由模拟器决定; 这里只输出 -1..1 的摇杆量",
                  (16, 414), C_DIM, self.f_small)
        pygame.display.flip()

    def run(self):
        clock = pygame.time.Clock()
        frame = 0
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    pygame.quit()
                    return
                if e.type == pygame.KEYDOWN:
                    self.handle_key(e.key)
                if e.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    self.sm.scan()
            self.update()
            self.draw()
            clock.tick(120)
            frame += 1
            if self.frames_limit and frame >= self.frames_limit:
                pygame.quit()
                return


if __name__ == "__main__":
    BridgeApp(arg("--selftest", 0, int)).run()
