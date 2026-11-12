"""SpaceMouse -> FRC swerve drive feel simulator (demo, not physically accurate).

Run:  python swerve_sim.py
Keys: see the in-app help panel (H toggles it).
"""
import math
import os
import random
import sys
import time
from collections import deque

from spacemouse_hid import HIDSpaceMouse
from spacemouse_driver import DriverSpaceMouse, FRAMEWORK
from runtime_paths import state_path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
import pygame
from pygame.math import Vector2 as V2

# ---------------------------------------------------------------- constants
CANVAS_W, CANVAS_H = 1900, 900
VIEW3D_X = 1505                       # left edge of the 3D SpaceMouse column
ARENA_W, ARENA_H = 12.0, 8.0          # metres; driver stands at the bottom edge
PPM = 70                              # pixels per metre
FIELD_ORIGIN = (20, 20)               # top-left of arena on canvas

ROBOT_HALF = 0.43                     # bumper half-width (m)
ROBOT_RADIUS = 0.50                   # collision circle
MODULE_OFF = 0.29                     # module offset from centre
MODULES = [V2(MODULE_OFF, MODULE_OFF), V2(MODULE_OFF, -MODULE_OFF),
           V2(-MODULE_OFF, MODULE_OFF), V2(-MODULE_OFF, -MODULE_OFF)]  # FL FR BL BR (x fwd, y left)

MAX_SPEED = 4.5                       # m/s
MAX_OMEGA = math.radians(450)         # rad/s default rotation top speed
DRIVE_ACCEL = 11.0                    # m/s^2 per wheel
STEER_RATE = 22.0                     # rad/s module azimuth slew

OBSTACLES = [(V2(3.5, 4.0), 0.35), (V2(6.0, 2.6), 0.35), (V2(6.0, 5.4), 0.35),
             (V2(8.5, 4.0), 0.35), (V2(10.4, 6.4), 0.5), (V2(1.6, 6.6), 0.5)]

MODES = ["PAN", "TILT", "FUSE", "SUM", "DOMINANT"]
MODE_DESC = {
    "PAN": "只用平移(推帽子) / pan only",
    "TILT": "只用倾斜(pitch/roll) / tilt only",
    "FUSE": "方向=pan+tilt, 幅值=max (防叠加)",
    "SUM": "pan+tilt 直接相加 (对照组, 会叠加)",
    "DOMINANT": "取较大的一个源, 带迟滞",
}

C_BG = (18, 20, 26)
C_FIELD = (36, 40, 48)
C_GRID = (48, 53, 63)
C_PAN = (80, 160, 255)
C_TILT = (255, 160, 60)
C_OUT = (90, 230, 120)
C_ROT = (240, 110, 200)
C_TEXT = (220, 224, 232)
C_DIM = (130, 136, 150)


_FONT_NAMES = ("microsoftyaheiui,microsoftyahei,simhei,pingfangsc,pingfang,hiraginosansgb,"
               "stheitimedium,notosanscjksc,notosanscjk,wenquanyimicrohei,arialunicodems")
_FONT_FILES = [  # macOS / Linux CJK fonts that SysFont may not resolve by name
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]
_font_files = None


def ui_font(size, bold=False):
    """A font that can render Chinese on Windows, macOS and Linux."""
    global _font_files
    if _font_files is None:
        reg = pygame.font.match_font(_FONT_NAMES) or next(
            (p for p in _FONT_FILES if os.path.exists(p)), None)
        _font_files = (reg, pygame.font.match_font(_FONT_NAMES, bold=True) or reg)
    path = _font_files[bold]
    f = pygame.font.Font(path, size)
    if bold and path == _font_files[0]:
        f.set_bold(True)          # no separate bold face found: synthesise it
    return f


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def curve(mag, db, expo):
    """Deadband + expo on a non-negative magnitude in [0,1]."""
    if mag <= db:
        return 0.0
    x = min(1.0, (mag - db) / (1.0 - db))
    return (1 - expo) * x + expo * x ** 3


def radial(vec, db, expo):
    """Radial (direction-preserving) deadband + expo for a 2D vector."""
    m = vec.length()
    if m < 1e-9:
        return V2()
    return vec * (curve(min(m, 1.0), db, expo) / m)


def shrink_scalar(m, thr):
    """Subtractive deadband on a magnitude, rescaled so 1.0 still maps to 1.0."""
    if m <= thr or thr >= 1.0:
        return 0.0
    return (m - thr) / (1.0 - thr)


def shrink(vec, thr):
    m = vec.length()
    if m < 1e-9 or thr <= 0:
        return V2(vec)
    return vec * (shrink_scalar(min(m, 1.0), thr) / m)


CAL_DIRS = [("前", V2(0, 1)), ("右", V2(1, 0)), ("后", V2(0, -1)), ("左", V2(-1, 0))]
CAL_PATH = state_path("calibration.json")


class Calibration:
    """Per-hand direction calibration.

    For each source (pan / tilt) we store the raw vector the user actually produces when
    intending forward / right / back / left. A raw vector lying between two adjacent measured
    vectors a, b is decomposed as v = alpha*a + beta*b and remapped to alpha*u_a + beta*u_b.
    That is exact at the calibrated directions, piecewise linear in between, and also fixes
    sign flips, axis skew and per-direction sensitivity differences.
    """

    def __init__(self, path=CAL_PATH):
        self.path = path
        self.data = {"pan": None, "tilt": None}
        self.enabled = True
        self.load()

    def load(self):
        try:
            import json
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            for k in ("pan", "tilt"):
                if d.get(k) and self.valid([V2(v) for v in d[k]]):
                    self.data[k] = [V2(v) for v in d[k]]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def save(self):
        import json
        out = {k: ([[v.x, v.y] for v in m] if m else None) for k, m in self.data.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

    @staticmethod
    def valid(meas):
        if len(meas) != 4 or any(v.length() < 0.15 for v in meas):
            return False
        dets = [meas[i].cross(meas[(i + 1) % 4]) for i in range(4)]
        # adjacent directions must turn consistently, each step < ~170 deg
        if not (all(d > 0 for d in dets) or all(d < 0 for d in dets)):
            return False
        return all(abs((meas[i].angle_to(meas[(i + 1) % 4]) + 180) % 360 - 180) < 170 for i in range(4))

    def has(self, src):
        return self.enabled and self.data.get(src) is not None

    def map(self, src, v):
        meas = self.data.get(src)
        if not self.enabled or not meas or v.length() < 1e-9:
            return V2(v)
        for i in range(4):
            a, b = meas[i], meas[(i + 1) % 4]
            det = a.cross(b)
            if abs(det) < 1e-9:
                continue
            al = v.cross(b) / det
            be = a.cross(v) / det
            if al >= -1e-9 and be >= -1e-9:
                return CAL_DIRS[i][1] * al + CAL_DIRS[(i + 1) % 4][1] * be
        return V2(v)


def snap_dir(v, snap_deg):
    """Soft snap to the 4 cardinal directions: inner half of the window snaps fully,
    outer half ramps back to the true angle so there's no jump."""
    if snap_deg <= 0 or v.length() < 1e-9:
        return v
    ang = math.degrees(math.atan2(v.y, v.x))
    card = round(ang / 90.0) * 90.0
    d = ang - card
    half = snap_deg / 2.0
    if abs(d) < snap_deg:
        d = 0.0 if abs(d) <= half else math.copysign((abs(d) - half) * 2.0, d)
    a = math.radians(card + d)
    return V2(math.cos(a), math.sin(a)) * v.length()


# ---------------------------------------------------------------- input
class SpaceMouseInput:
    """Reads through SDL, with a direct HID fallback on macOS.
    Axis order: Tx Ty Tz Rx Ry Rz, each -1..1 (SDL normalises the HID logical range)."""

    def __init__(self):
        self.joy = None
        self.name = "SpaceMouse 未找到"
        self.scan()

    def scan(self):
        if self.joy is not None:
            self.joy.quit()
        self.joy = None
        self.last_scan = time.monotonic()
        self.name = "SpaceMouse 未找到"
        if sys.platform == 'darwin' and FRAMEWORK.exists():
            try:
                self.joy = DriverSpaceMouse.open()
                if self.joy is not None:
                    self.name = self.joy.name
                    return
            except OSError:
                self.name = '请打开 3Dconnexion 设置后重试'
            return
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            guid = j.get_guid().lower()
            name = j.get_name().lower()
            # GUID bytes 4-5 = vendor id little-endian (same layout on Windows and macOS);
            # 3Dconnexion = 0x256F, older models use Logitech's 0x046D. The axis-count check
            # also skips the "KMJ Emulator" virtual joystick that 3DxWare creates on Windows.
            is_3dx = (guid[8:12] == "6f25"
                      or any(s in name for s in ("spacemouse", "space mouse", "spacenavigator",
                                                 "spacepilot", "spaceexplorer", "3dconnexion")))
            if is_3dx and j.get_numaxes() >= 6:
                j.init()
                self.joy = j
                self.name = f"SpaceMouse (#{i}, {j.get_numaxes()} axes)"
                return

        if sys.platform == "darwin":
            try:
                self.joy = HIDSpaceMouse.open()
                if self.joy is not None:
                    self.name = f"{self.joy.name} (HID, 6 axes)"
            except ImportError:
                self.name = "缺少 hidapi: 请重新安装 requirements.txt"
            except OSError:
                self.name = "HID 被占用/无权限: 退出 3DconnexionHelper，检查输入监控"

    def read(self):
        if self.joy is None and time.monotonic() - self.last_scan > 2.0:
            self.scan()
        if self.joy is None:
            return [0.0] * 6, [False, False]
        try:
            if isinstance(self.joy, (HIDSpaceMouse,DriverSpaceMouse)):
                if isinstance(self.joy,DriverSpaceMouse):
                    self.joy.set_active(True)
                self.joy.poll()
            axes = [clamp(self.joy.get_axis(i), -1.0, 1.0) for i in range(6)]
            btns = [bool(self.joy.get_button(b)) for b in range(min(2, self.joy.get_numbuttons()))]
        except (pygame.error, OSError):
            self.joy.quit()
            self.joy = None
            self.name = "SpaceMouse 已断开，正在重新扫描"
            return [0.0] * 6, [False, False]
        return axes, btns + [False] * (2 - len(btns))


class InputProcessor:
    def __init__(self):
        self.mode = "FUSE"
        self.deadband = 0.06
        self.expo = 0.35
        self.pan_gain = 1.0
        self.tilt_gain = 1.0
        self.rot_gain = 1.3            # natural full twist measured ~0.65-0.85 raw
        self.decouple = True
        # Leak coefficients measured on this device/hand (leak ~= k * |source axis|):
        self.k_pan_from_twist = 0.08   # twisting barely moves Tx/Ty
        self.k_tilt_from_twist = 0.5   # twisting drags roll a lot (Ry up to ~0.47*Rz)
        self.k_twist_from_pan = 0.2    # pushing leaks Rz up to ~0.18
        self.inv_pitch = False
        self.inv_roll = False
        self.dominant_src = "PAN"
        self.cal = Calibration()
        self.snap_deg = 0.0
        self.out = {}

    def raw_vectors(self, ax):
        tx, ty, tz, rx, ry, rz = ax
        # Driver frame: x = right, y = forward (push away from you).
        # Measured: push fwd -> Ty<0, tilt fwd -> Rx<0, tilt right -> Ry<0.
        return V2(tx, -ty), V2(-ry, -rx)

    def process(self, ax):
        tx, ty, tz, rx, ry, rz = ax
        pan_raw, tilt_raw = self.raw_vectors(ax)
        thr_pan = thr_tilt = thr_rot = 0.0
        if self.decouple:
            # Dynamic deadbands: subtract the expected cross-axis leak, then rescale so full
            # deflection is still reachable. Intentional combined input passes at full gain.
            thr_pan = self.k_pan_from_twist * abs(rz)
            thr_tilt = self.k_tilt_from_twist * abs(rz)
            thr_rot = self.k_twist_from_pan * pan_raw.length()
            pan_raw = shrink(pan_raw, thr_pan)
            tilt_raw = shrink(tilt_raw, thr_tilt)
            rz = math.copysign(shrink_scalar(abs(rz), thr_rot), rz)
        pan = self.cal.map("pan", pan_raw) * self.pan_gain
        if self.cal.has("tilt"):
            tilt = self.cal.map("tilt", tilt_raw)   # calibration already fixes signs
        else:
            tilt = V2(tilt_raw.x * (-1 if self.inv_roll else 1), tilt_raw.y * (-1 if self.inv_pitch else 1))
        tilt *= self.tilt_gain
        db = self.deadband
        pan_d = radial(pan, db, 0.0)    # deadband only; expo applied after fusion
        tilt_d = radial(tilt, db, 0.0)
        pm, tm = pan_d.length(), tilt_d.length()

        if self.mode == "PAN":
            t = V2(pan_d)
        elif self.mode == "TILT":
            t = V2(tilt_d)
        elif self.mode == "SUM":
            t = pan_d + tilt_d
        elif self.mode == "DOMINANT":
            if self.dominant_src == "PAN" and tm > pm * 1.25 + 0.03:
                self.dominant_src = "TILT"
            elif self.dominant_src == "TILT" and pm > tm * 1.25 + 0.03:
                self.dominant_src = "PAN"
            t = V2(pan_d if self.dominant_src == "PAN" else tilt_d)
        else:  # FUSE
            if pm < 1e-6 or tm < 1e-6:
                t = V2(pan_d if pm >= tm else tilt_d)
            elif pan_d.dot(tilt_d) < 0.0:
                # Sources disagree (>90 deg apart) -> trust the stronger one.
                t = V2(pan_d if pm >= tm else tilt_d)
            else:
                # Agree (the natural push+tilt coupling) -> blend direction weighted by
                # magnitude^2 so the dominant source steers; magnitude = max (no gain stacking).
                d = pan_d * pm + tilt_d * tm
                t = d.normalize() * max(pm, tm) if d.length() > 1e-9 else V2()

        if t.length() > 1.0:
            t.scale_to_length(1.0)
        t = snap_dir(t, self.snap_deg)
        t = radial(t, 0.0, self.expo)

        rot = math.copysign(curve(min(abs(rz) * self.rot_gain, 1.0), db, self.expo), rz)

        angle_between = None
        if pm > 1e-3 and tm > 1e-3:
            angle_between = math.degrees(math.acos(clamp(pan_d.dot(tilt_d) / (pm * tm), -1, 1)))
        self.out = dict(pan=pan, tilt=tilt, pan_d=pan_d, tilt_d=tilt_d, trans=t, rot=rot,
                        thr_pan=thr_pan, thr_tilt=thr_tilt, thr_rot=thr_rot, tz=tz,
                        angle_between=angle_between)
        return t, rot


def keyboard_axes(keys):
    tx = (keys[pygame.K_d] - keys[pygame.K_a]) * 0.8
    ty = (keys[pygame.K_s] - keys[pygame.K_w]) * 0.8
    rz = (keys[pygame.K_e] - keys[pygame.K_q]) * 0.7
    return [tx, ty, 0.0, 0.0, 0.0, rz]


# ---------------------------------------------------------------- swerve model
class Module:
    def __init__(self, pos):
        self.pos = pos
        self.angle = 0.0
        self.speed = 0.0


class Swerve:
    def __init__(self):
        self.modules = [Module(p) for p in MODULES]
        self.reset()

    def reset(self):
        self.pos = V2(ARENA_W / 2, 1.2)
        self.theta = math.pi / 2          # facing away from driver
        self.gyro_offset = 0.0
        self.v_robot = V2()
        self.omega = 0.0
        for m in self.modules:
            m.angle = m.speed = 0.0
        self.trail = deque(maxlen=600)

    def drive_heading(self):
        return self.theta - self.gyro_offset

    def zero_gyro(self):
        self.gyro_offset = self.theta - math.pi / 2

    def step(self, cmd_driver, rot, field_oriented, speed_scale, dt, omega_max=MAX_OMEGA):
        vmax = MAX_SPEED * speed_scale
        omega_cmd = -rot * omega_max                           # twist CW -> robot turns CW
        if field_oriented:
            vr = (cmd_driver * vmax).rotate_rad(-self.drive_heading())  # field X = right, Y = forward
        else:
            vr = V2(cmd_driver.y, -cmd_driver.x) * vmax        # robot x = front, y = left

        targets = [V2(vr.x - omega_cmd * m.pos.y, vr.y + omega_cmd * m.pos.x) for m in self.modules]
        peak = max(t.length() for t in targets)
        if peak > MAX_SPEED:
            targets = [t * (MAX_SPEED / peak) for t in targets]

        for m, t in zip(self.modules, targets):
            spd = t.length()
            if spd > 0.02:
                ang = math.atan2(t.y, t.x)
                if abs(wrap(ang - m.angle)) > math.pi / 2:   # 180-degree flip optimisation
                    ang = wrap(ang + math.pi)
                    spd = -spd
            else:
                ang, spd = m.angle, 0.0
            err = wrap(ang - m.angle)
            m.angle = wrap(m.angle + clamp(err, -STEER_RATE * dt, STEER_RATE * dt))
            want = spd * max(0.0, math.cos(wrap(ang - m.angle)))  # cosine compensation
            m.speed += clamp(want - m.speed, -DRIVE_ACCEL * dt, DRIVE_ACCEL * dt)

        vx = sum(m.speed * math.cos(m.angle) for m in self.modules) / 4
        vy = sum(m.speed * math.sin(m.angle) for m in self.modules) / 4
        num = sum(m.pos.x * m.speed * math.sin(m.angle) - m.pos.y * m.speed * math.cos(m.angle)
                  for m in self.modules)
        den = sum(m.pos.length_squared() for m in self.modules)
        self.v_robot = V2(vx, vy)
        self.omega = num / den

        self.pos += self.v_robot.rotate_rad(self.theta) * dt
        self.theta = wrap(self.theta + self.omega * dt)
        self.collide()
        self.trail.append(V2(self.pos))

    def collide(self):
        r = ROBOT_RADIUS
        self.pos.x = clamp(self.pos.x, r, ARENA_W - r)
        self.pos.y = clamp(self.pos.y, r, ARENA_H - r)
        for c, cr in OBSTACLES:
            d = self.pos - c
            if 1e-9 < d.length() < r + cr:
                self.pos = c + d.normalize() * (r + cr)


# ---------------------------------------------------------------- challenge
class Challenge:
    """Park the robot on a random ghost pose (position + heading)."""

    def __init__(self):
        self.active = False
        self.target = None
        self.t = 0.0
        self.hold = 0.0
        self.times = []

    def new_target(self, robot_pos):
        p = V2(ARENA_W / 2, ARENA_H / 2)
        for _ in range(200):
            p = V2(random.uniform(1.0, ARENA_W - 1.0), random.uniform(1.0, ARENA_H - 1.0))
            if (p - robot_pos).length() < 3.0:
                continue
            if all((p - c).length() > cr + ROBOT_RADIUS + 0.3 for c, cr in OBSTACLES):
                break
        self.target = (p, random.uniform(-math.pi, math.pi))
        self.t = 0.0
        self.hold = 0.0

    def toggle(self, robot):
        self.active = not self.active
        if self.active:
            self.new_target(robot.pos)
        else:
            self.target = None

    def update(self, robot, dt):
        if not self.active or self.target is None:
            return
        self.t += dt
        p, h = self.target
        ok = ((robot.pos - p).length() < 0.12 and abs(math.degrees(wrap(robot.theta - h))) < 6
              and robot.v_robot.length() < 0.4 and abs(robot.omega) < 0.6)
        self.hold = self.hold + dt if ok else 0.0
        if self.hold > 0.25:
            self.times.append(self.t)
            self.new_target(robot.pos)


# ---------------------------------------------------------------- drawing helpers
def w2s(p):
    return (FIELD_ORIGIN[0] + p.x * PPM, FIELD_ORIGIN[1] + (ARENA_H - p.y) * PPM)


def draw_robot_shape(surf, pos, theta, color, width=0):
    corners = [V2(ROBOT_HALF, ROBOT_HALF), V2(ROBOT_HALF, -ROBOT_HALF),
               V2(-ROBOT_HALF, -ROBOT_HALF), V2(-ROBOT_HALF, ROBOT_HALF)]
    pygame.draw.polygon(surf, color, [w2s(pos + c.rotate_rad(theta)) for c in corners], width)
    front = [w2s(pos + V2(ROBOT_HALF, ROBOT_HALF * 0.8).rotate_rad(theta)),
             w2s(pos + V2(ROBOT_HALF, -ROBOT_HALF * 0.8).rotate_rad(theta))]
    pygame.draw.line(surf, (255, 220, 60), front[0], front[1], 4)


def arrow(surf, color, a, b, width=3, head=10):
    a, b = V2(a), V2(b)
    pygame.draw.line(surf, color, a, b, width)
    d = b - a
    if d.length() < 4:
        return
    d = d.normalize()
    n = V2(-d.y, d.x)
    pygame.draw.polygon(surf, color, [b, b - d * head + n * head * 0.5, b - d * head - n * head * 0.5])


V3 = pygame.math.Vector3
DIR8 = ["前", "右前", "右", "右后", "后", "左后", "左", "左前"]


def dir_label(v):
    """Driver-frame 2D vector (x=right, y=fwd) -> Chinese 8-way direction."""
    ang = math.degrees(math.atan2(v.x, v.y))
    return DIR8[int(round(ang / 45.0)) % 8]


def superellipse(n_seg, rx, ry, z, power):
    pts = []
    for i in range(n_seg):
        a = 2 * math.pi * i / n_seg
        c, s = math.cos(a), math.sin(a)
        pts.append(V3(rx * math.copysign(abs(c) ** (2 / power), c),
                      ry * math.copysign(abs(s) ** (2 / power), s), z))
    return pts


class SpaceMouseView:
    """Tiny flat-shaded software 3D renderer of a SpaceMouse mirroring the raw 6-axis input.

    World frame (mm): X = right, Y = forward (away from the user), Z = up.
    Displacements are exaggerated (the real cap only moves ~1-2 mm / a few degrees).
    """
    TRANS_MM = 14.0       # cap displacement per 1.0 of axis
    ROT_DEG = 22.0        # cap rotation per 1.0 of axis
    PIVOT = V3(0, 0, 23)  # cap bottom centre at rest

    def __init__(self, size):
        self.size = size
        self.surf = pygame.Surface(size)
        az, el, dist = math.radians(-20), math.radians(30), 230.0
        target = V3(-8, 0, 24)
        self.cam = target + V3(math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)) * dist
        self.fwd = (target - self.cam).normalize()
        self.right = self.fwd.cross(V3(0, 0, 1)).normalize()
        self.up = self.right.cross(self.fwd)
        self.focal = size[0] * 1.45
        self.light = V3(-0.35, -0.55, 1.0).normalize()
        self._build()

    def _build(self):
        n = 44
        bot = superellipse(n, 42, 40, 0, 3.2)
        top = superellipse(n, 33, 31, 20, 2.6)
        self.base = []
        for i in range(n):
            j = (i + 1) % n
            ang = math.degrees(2 * math.pi * i / n + math.pi / n) % 360
            col = (52, 54, 60)
            if min(abs(ang - 0), abs(ang - 360), abs(ang - 180)) < 13:
                col = (150, 152, 160)          # side buttons
            elif abs(ang - 270) < 6:
                col = (70, 150, 255)           # LED facing the user
            self.base.append(([bot[i], bot[j], top[j], top[i]], col))
        self.base.append((top, (64, 66, 74)))
        self.base_center = V3(0, 0, 8)

        r, h = 25.0, 29.0
        lo = [V3(math.cos(2 * math.pi * i / n) * r, math.sin(2 * math.pi * i / n) * r, 0) for i in range(n)]
        hi = [V3(p.x, p.y, h) for p in lo]
        tp = [V3(p.x * 0.9, p.y * 0.9, h + 2.5) for p in lo]
        self.cap = []
        for i in range(n):
            j = (i + 1) % n
            rib = (125, 128, 136) if i % 2 else (104, 107, 115)   # ribs make twist visible
            self.cap.append(([lo[i], lo[j], hi[j], hi[i]], rib))
            self.cap.append(([hi[i], hi[j], tp[j], tp[i]], (150, 153, 160)))
        self.cap.append((tp, (138, 141, 148)))
        z = h + 2.7
        # decals are always drawn after the cap body (coplanar with the top face)
        self.decals = [([V3(0, 19, z), V3(-7, 7, z), V3(7, 7, z)], (255, 210, 70)),   # "front" marker
                       ([V3(-2, -17, z), V3(2, -17, z), V3(2, -7, z), V3(-2, -7, z)], (235, 235, 240))]
        self.cap_center = V3(0, 0, h / 2)
        self.ghost = [lo, tp]

    def project(self, p):
        d = p - self.cam
        z = d.dot(self.fwd)
        return (self.size[0] / 2 + self.focal * d.dot(self.right) / z,
                self.size[1] / 2 - self.focal * d.dot(self.up) / z), z

    def cap_transform(self, axes):
        tx, ty, tz, rx, ry, rz = axes
        k = math.radians(self.ROT_DEG)
        # tilt fwd -> Rx<0 -> top toward +Y ; tilt right -> Ry<0 -> top toward +X ; CW twist -> Rz>0
        ax_, ay_, az_ = rx * k, -ry * k, -rz * k
        off = V3(tx, -ty, -tz) * self.TRANS_MM

        def tf(p):
            return self.PIVOT + off + p.rotate_z_rad(az_).rotate_x_rad(ax_).rotate_y_rad(ay_)
        return tf

    def draw_faces(self, faces, tf, center, sort=True):
        c_world = tf(center)
        polys = []
        for pts, col in faces:
            w = [tf(p) for p in pts]
            cen = sum(w, V3()) / len(w)
            nrm = (w[1] - w[0]).cross(w[2] - w[0])
            if nrm.length_squared() < 1e-12:
                continue
            nrm = nrm.normalize()
            if nrm.dot(cen - c_world) < 0:
                nrm = -nrm
            if nrm.dot(self.cam - cen) <= 0:
                continue                                     # back face
            shade = 0.38 + 0.62 * max(0.0, nrm.dot(self.light))
            proj = [self.project(p)[0] for p in w]
            polys.append((self.project(cen)[1], proj, tuple(min(255, int(c * shade)) for c in col)))
        if sort:
            polys.sort(key=lambda t: -t[0])
        for _, proj, col in polys:
            pygame.draw.polygon(self.surf, col, proj)

    def render(self, axes):
        s = self.surf
        s.fill((26, 29, 36))
        for g in range(-90, 91, 30):                         # floor grid
            pygame.draw.line(s, (44, 48, 58), self.project(V3(g, -90, 0))[0], self.project(V3(g, 90, 0))[0])
            pygame.draw.line(s, (44, 48, 58), self.project(V3(-90, g, 0))[0], self.project(V3(90, g, 0))[0])
        a, b = self.project(V3(-78, -25, 0))[0], self.project(V3(-78, 45, 0))[0]
        arrow(s, (90, 230, 120), a, b, 4, 14)
        self.draw_faces(self.base, lambda p: p, self.base_center)
        rest = lambda p: self.PIVOT + p
        for ring in self.ghost:                              # rest-position ghost
            pygame.draw.lines(s, (90, 96, 112), True, [self.project(rest(p))[0] for p in ring], 1)
        tf = self.cap_transform(axes)
        self.draw_faces(self.cap, tf, self.cap_center)
        self.draw_faces(self.decals, tf, self.cap_center, sort=False)
        return s


class App:
    def __init__(self, selftest_frames=0):
        if sys.platform == "win32" and not selftest_frames:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        pygame.init()
        pygame.joystick.init()
        self.selftest = selftest_frames
        info = pygame.display.Info()
        sw, sh = (info.current_w or 1600), (info.current_h or 900)
        scale = min(1.0, (sw * 0.95) / CANVAS_W, (sh * 0.88) / CANVAS_H)
        self.win_size = (int(CANVAS_W * scale), int(CANVAS_H * scale))
        self.screen = pygame.display.set_mode(self.win_size, pygame.RESIZABLE)
        pygame.display.set_caption("SpaceMouse Swerve Sim")
        self.canvas = pygame.Surface((CANVAS_W, CANVAS_H))
        self.f_small = ui_font(15)
        self.f = ui_font(18)
        self.f_big = ui_font(24, bold=True)
        self.clock = pygame.time.Clock()

        self.sm = SpaceMouseInput()
        self.smview = SpaceMouseView((CANVAS_W - VIEW3D_X - 15, 400))
        self.f_huge = ui_font(30, bold=True)
        self.proc = InputProcessor()
        self.robot = Swerve()
        self.chal = Challenge()
        self.field_oriented = True
        self.speed_scale = 0.7
        self.rot_max_deg = math.degrees(MAX_OMEGA)
        self.use_keyboard = self.sm.joy is None
        self.show_help = True
        self.prev_btn = [False, False]
        self.history = deque(maxlen=300)
        self.raw = [0.0] * 6
        self.wiz = None          # calibration wizard state
        self.wiz_msg = ""

    # -------------------------------------------------- calibration wizard
    def wiz_start(self):
        self.wiz = dict(step=0, phase="wait_push", t=0.0, buf=[], meas={"pan": [], "tilt": []})
        self.wiz_msg = ""

    def wiz_finish(self, keep_tilt):
        cal = self.proc.cal
        cal.data["pan"] = self.wiz["meas"]["pan"]
        if keep_tilt:
            cal.data["tilt"] = self.wiz["meas"]["tilt"]
        cal.enabled = True
        try:
            cal.save()
            self.wiz_msg = "校准已保存 → calibration.json"
        except OSError as ex:
            self.wiz_msg = f"保存失败: {ex}"
        self.wiz = None

    def wiz_update(self, axes, dt):
        w = self.wiz
        src = "pan" if w["step"] < 4 else "tilt"
        pan_raw, tilt_raw = self.proc.raw_vectors(axes)
        v = pan_raw if src == "pan" else tilt_raw
        m = v.length()
        if w["phase"] == "wait_push":
            if m > 0.25:
                w.update(phase="collect", t=0.0, buf=[])
        elif w["phase"] == "collect":
            if m < 0.10:                        # let go too early -> retry this step
                w["phase"] = "wait_push"
                return
            w["buf"].append(V2(v))
            w["t"] += dt
            if w["t"] >= 1.2:
                peak = max(x.length() for x in w["buf"])
                sel = [x for x in w["buf"] if x.length() >= 0.8 * peak]
                w["meas"][src].append(sum(sel, V2()) / len(sel))
                w["phase"] = "wait_release"
        elif w["phase"] == "wait_release" and m < 0.08:
            w["step"] += 1
            w["phase"] = "wait_push"
            if w["step"] == 4 and not Calibration.valid(w["meas"]["pan"]):
                w["meas"]["pan"] = []
                w["step"] = 0
                self.wiz_msg = "pan 测量不一致(方向顺序乱/太弱), 请重做"
            elif w["step"] == 8:
                if Calibration.valid(w["meas"]["tilt"]):
                    self.wiz_finish(keep_tilt=True)
                else:
                    self.wiz_finish(keep_tilt=False)
                    self.wiz_msg = "tilt 测量不一致, 只保存了 pan 校准"

    # -------------------------------------------------- events
    def handle_key(self, k):
        p = self.proc
        if self.wiz:
            if k == pygame.K_ESCAPE:
                self.wiz = None
                self.wiz_msg = "校准已取消"
            elif k == pygame.K_s and self.wiz["step"] >= 4:
                self.wiz_finish(keep_tilt=False)
            return True
        if pygame.K_1 <= k <= pygame.K_5:
            p.mode = MODES[k - pygame.K_1]
        elif k == pygame.K_k:
            self.wiz_start()
        elif k == pygame.K_l:
            p.cal.enabled = not p.cal.enabled
        elif k == pygame.K_g:
            p.snap_deg = 0.0 if p.snap_deg else 15.0
        elif k == pygame.K_7:
            p.rot_gain = clamp(p.rot_gain - 0.1, 0.5, 3.0)
        elif k == pygame.K_8:
            p.rot_gain = clamp(p.rot_gain + 0.1, 0.5, 3.0)
        elif k == pygame.K_9:
            self.rot_max_deg = clamp(self.rot_max_deg - 45, 90, 1080)
        elif k == pygame.K_0:
            self.rot_max_deg = clamp(self.rot_max_deg + 45, 90, 1080)
        elif k == pygame.K_f:
            self.field_oriented = not self.field_oriented
        elif k == pygame.K_z:
            self.robot.zero_gyro()
        elif k == pygame.K_c:
            p.decouple = not p.decouple
        elif k == pygame.K_LEFTBRACKET:
            p.deadband = clamp(p.deadband - 0.02, 0.0, 0.4)
        elif k == pygame.K_RIGHTBRACKET:
            p.deadband = clamp(p.deadband + 0.02, 0.0, 0.4)
        elif k == pygame.K_SEMICOLON:
            p.expo = clamp(p.expo - 0.05, 0.0, 1.0)
        elif k == pygame.K_QUOTE:
            p.expo = clamp(p.expo + 0.05, 0.0, 1.0)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.speed_scale = clamp(self.speed_scale - 0.1, 0.2, 1.0)
        elif k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.speed_scale = clamp(self.speed_scale + 0.1, 0.2, 1.0)
        elif k == pygame.K_COMMA:
            p.tilt_gain = clamp(p.tilt_gain - 0.1, 0.0, 3.0)
        elif k == pygame.K_PERIOD:
            p.tilt_gain = clamp(p.tilt_gain + 0.1, 0.0, 3.0)
        elif k == pygame.K_n:
            p.pan_gain = clamp(p.pan_gain - 0.1, 0.0, 3.0)
        elif k == pygame.K_m:
            p.pan_gain = clamp(p.pan_gain + 0.1, 0.0, 3.0)
        elif k == pygame.K_i:
            p.inv_pitch = not p.inv_pitch
        elif k == pygame.K_o:
            p.inv_roll = not p.inv_roll
        elif k == pygame.K_t:
            self.chal.toggle(self.robot)
        elif k == pygame.K_x:
            self.chal.times.clear()
        elif k == pygame.K_SPACE:
            self.robot.reset()
        elif k == pygame.K_TAB:
            self.use_keyboard = not self.use_keyboard
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        elif k == pygame.K_ESCAPE:
            return False
        return True

    def run(self):
        running, frame = True, 0
        while running:
            dt = min(self.clock.tick(120) / 1000.0, 1 / 30)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    running = self.handle_key(e.key) and running
                elif e.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    self.sm.scan()
                elif e.type == pygame.VIDEORESIZE:
                    self.win_size = e.size
            self.update(dt, frame)
            self.draw()
            frame += 1
            if self.selftest and frame >= self.selftest:
                running = False
        pygame.quit()

    def update(self, dt, frame):
        axes, btns = self.sm.read()
        if self.selftest:   # synthetic coupled input: push fwd+right with tilt leak, plus twist
            ph = frame / 60.0
            axes = [0.6 * math.sin(ph), -0.8, 0.2, -0.5, 0.3 * math.sin(ph), 0.4 * math.cos(ph * 0.7)]
            if frame == 10:
                self.chal.toggle(self.robot)
            self.proc.mode = MODES[(frame // 40) % len(MODES)]
        elif self.use_keyboard:
            axes = keyboard_axes(pygame.key.get_pressed())
        self.raw = axes
        if self.wiz:
            self.wiz_update(axes, dt)
            self.proc.process(axes)
            self.robot.step(V2(), 0.0, self.field_oriented, self.speed_scale, dt)
            self.prev_btn = btns
            return
        # SpaceMouse buttons: left = zero gyro, right = cycle mode (edge-triggered)
        if btns[0] and not self.prev_btn[0]:
            self.robot.zero_gyro()
        if btns[1] and not self.prev_btn[1]:
            self.proc.mode = MODES[(MODES.index(self.proc.mode) + 1) % len(MODES)]
        self.prev_btn = btns

        t, rot = self.proc.process(axes)
        self.robot.step(t, rot, self.field_oriented, self.speed_scale, dt, math.radians(self.rot_max_deg))
        self.chal.update(self.robot, dt)
        self.history.append((t.y, t.x, rot))

    # -------------------------------------------------- drawing
    def text(self, s, pos, color=C_TEXT, font=None):
        img = (font or self.f).render(s, True, color)
        self.canvas.blit(img, pos)
        return img.get_height()

    def draw_field(self):
        c = self.canvas
        rect = pygame.Rect(FIELD_ORIGIN, (ARENA_W * PPM, ARENA_H * PPM))
        pygame.draw.rect(c, C_FIELD, rect)
        for i in range(1, int(ARENA_W)):
            x = FIELD_ORIGIN[0] + i * PPM
            pygame.draw.line(c, C_GRID, (x, rect.top), (x, rect.bottom))
        for i in range(1, int(ARENA_H)):
            y = FIELD_ORIGIN[1] + i * PPM
            pygame.draw.line(c, C_GRID, (rect.left, y), (rect.right, y))
        pygame.draw.rect(c, (120, 126, 140), rect, 3)
        pygame.draw.line(c, (60, 120, 255), (rect.left, rect.bottom + 4), (rect.right, rect.bottom + 4), 6)
        self.text("▼ DRIVER STATION (你站在这边, 往前推 = 往上走)", (rect.centerx - 170, rect.bottom + 8),
                  C_DIM, self.f_small)
        for ctr, r in OBSTACLES:
            pygame.draw.circle(c, (200, 90, 60), w2s(ctr), r * PPM)
            pygame.draw.circle(c, (255, 140, 90), w2s(ctr), r * PPM, 2)

        if len(self.robot.trail) > 2:
            pygame.draw.lines(c, (90, 100, 130), False, [w2s(p) for p in self.robot.trail], 2)

        if self.chal.target:
            p, h = self.chal.target
            col = (90, 230, 120) if self.chal.hold > 0 else (220, 210, 90)
            draw_robot_shape(c, p, h, col, 2)
            pygame.draw.circle(c, col, w2s(p), 0.12 * PPM, 1)

        r = self.robot
        draw_robot_shape(c, r.pos, r.theta, (40, 90, 200))
        draw_robot_shape(c, r.pos, r.theta, (150, 190, 255), 2)
        for m in r.modules:
            mp = r.pos + m.pos.rotate_rad(r.theta)
            d = V2(1, 0).rotate_rad(m.angle + r.theta)
            half = d * 0.11
            pygame.draw.line(c, (20, 20, 20), w2s(mp - half), w2s(mp + half), 9)
            pygame.draw.line(c, (230, 230, 230), w2s(mp - half), w2s(mp + half), 5)
            vec = d * m.speed * 0.18
            if vec.length() > 0.02:
                arrow(c, C_OUT, w2s(mp), w2s(mp + vec), 2, 7)
        if self.field_oriented and abs(r.gyro_offset) > 1e-3:
            # where "push forward" goes in the world after a gyro re-zero
            arrow(c, (255, 80, 80), w2s(r.pos), w2s(r.pos + V2(0, 0.8).rotate_rad(r.gyro_offset)), 2, 8)

    def draw_puck(self, cx, cy, R):
        c, o = self.canvas, self.proc.out
        pygame.draw.circle(c, (40, 44, 54), (cx, cy), R)
        pygame.draw.circle(c, (90, 96, 110), (cx, cy), R, 2)
        pygame.draw.circle(c, (70, 74, 86), (cx, cy), int(R * self.proc.deadband) + 1, 1)
        pygame.draw.line(c, (60, 64, 76), (cx - R, cy), (cx + R, cy))
        pygame.draw.line(c, (60, 64, 76), (cx, cy - R), (cx, cy + R))
        ctr = V2(cx, cy)
        for key, col, w in (("trans", C_OUT, 8), ("pan", C_PAN, 3), ("tilt", C_TILT, 3)):
            v = o.get(key, V2())
            arrow(c, col, ctr, ctr + V2(v.x, -v.y) * R, w, 12)
        rot = o.get("rot", 0.0)
        if abs(rot) > 1e-3:
            span = abs(rot) * math.pi * 0.9
            rect = pygame.Rect(cx - R - 10, cy - R - 10, 2 * R + 20, 2 * R + 20)
            start = math.pi / 2 - span if rot > 0 else math.pi / 2
            pygame.draw.arc(c, C_ROT, rect, start, start + span, 6)
        self.text("输入向量 (driver frame, 上=前)", (cx - R, cy - R - 40), C_TEXT, self.f_small)
        xs = cx - R - 10
        for lab, col in (("pan推", C_PAN), ("tilt倾", C_TILT), ("输出", C_OUT), ("扭转", C_ROT)):
            pygame.draw.rect(c, col, (xs, cy + R + 18, 12, 12))
            self.text(lab, (xs + 15, cy + R + 13), C_DIM, self.f_small)
            xs += 62

    def draw_bars(self, x, y, w):
        names = ["Tx 左右推", "Ty 前后推", "Tz 上下压", "Rx pitch", "Ry roll", "Rz 扭转"]
        cols = [C_PAN, C_PAN, C_DIM, C_TILT, C_TILT, C_ROT]
        self.text("原始 6 轴", (x, y - 26), C_TEXT, self.f_small)
        for i, (n, v) in enumerate(zip(names, self.raw)):
            yy = y + i * 34
            self.text(n, (x, yy), C_DIM, self.f_small)
            bx, bw = x + 90, w - 150
            pygame.draw.rect(self.canvas, (44, 48, 58), (bx, yy + 3, bw, 16))
            mid = bx + bw / 2
            pygame.draw.rect(self.canvas, cols[i], (min(mid, mid + v * bw / 2), yy + 3, abs(v) * bw / 2, 16))
            pygame.draw.line(self.canvas, (120, 120, 130), (mid, yy), (mid, yy + 22))
            self.text(f"{v:+.2f}", (bx + bw + 8, yy), C_TEXT, self.f_small)

    def draw_chart(self, x, y, w, h):
        c = self.canvas
        pygame.draw.rect(c, (30, 33, 40), (x, y, w, h))
        pygame.draw.line(c, (70, 74, 86), (x, y + h / 2), (x + w, y + h / 2))
        self.text("指令 5s: 前进(绿) 横移(蓝) 旋转(粉)", (x, y - 26), C_TEXT, self.f_small)
        if len(self.history) < 2:
            return
        n = self.history.maxlen
        for idx, col in ((0, C_OUT), (1, C_PAN), (2, C_ROT)):
            pts = [(x + i * w / (n - 1), y + h / 2 - s[idx] * h * 0.45) for i, s in enumerate(self.history)]
            pygame.draw.lines(c, col, False, pts, 2)

    def draw_panel(self, x):
        p, o, r = self.proc, self.proc.out, self.robot
        y = 20
        y += self.text("SpaceMouse → Swerve", (x, y), C_TEXT, self.f_big) + 6
        src = "键盘 WASD+QE (Tab 切换)" if self.use_keyboard else self.sm.name
        col = (255, 200, 80) if self.use_keyboard or self.sm.joy is None else C_OUT
        y += self.text(f"输入: {src}", (x, y), col) + 10

        y += self.text("平移融合模式 (数字键 1-5 / SpaceMouse 右键):", (x, y)) + 2
        for i, m in enumerate(MODES):
            sel = m == p.mode
            extra = f"  [当前: {p.dominant_src}]" if (m == "DOMINANT" and sel) else ""
            y += self.text(f"{'>>' if sel else '    '} {i + 1}. {m:<9} {MODE_DESC[m]}{extra}", (x, y),
                           C_OUT if sel else C_DIM, self.f_small) + 1
        y += 8
        cal = p.cal
        cal_state = (f"{'ON' if cal.enabled else 'OFF'}  (pan:{'已校准' if cal.data['pan'] else '无'}"
                     f"  tilt:{'已校准' if cal.data['tilt'] else '无'})")
        rows = [
            f"K  校准向导      L  方向校准: {cal_state}",
            f"G  轴吸附(±15°软吸附到前后左右): {'ON' if p.snap_deg else 'OFF'}",
            f"F  坐标系: {'Field-oriented' if self.field_oriented else 'Robot-oriented'}",
            f"C  动态死区解耦: {'ON' if p.decouple else 'OFF'}   阈值 pan {o.get('thr_pan', 0):.2f}"
            f"  tilt {o.get('thr_tilt', 0):.2f}  扭 {o.get('thr_rot', 0):.2f}",
            f"7 8  扭转灵敏度: {p.rot_gain:.1f}      9 0  旋转最大速度: {self.rot_max_deg:.0f}°/s",
            f"[ ]  死区 deadband: {p.deadband:.2f}        ; '  expo: {p.expo:.2f}",
            f"N M  pan 增益: {p.pan_gain:.1f}        , .  tilt 增益: {p.tilt_gain:.1f}",
            f"- =  速度上限: {self.speed_scale * 100:.0f}%  ({MAX_SPEED * self.speed_scale:.1f} m/s)",
            f"I O  反转 pitch: {'Y' if p.inv_pitch else 'N'}    反转 roll: {'Y' if p.inv_roll else 'N'}",
        ]
        for s in rows:
            y += self.text(s, (x, y), C_TEXT, self.f_small) + 3
        y += 8
        ab = o.get("angle_between")
        pm, tm = o.get("pan_d", V2()).length(), o.get("tilt_d", V2()).length()
        mix = "—" if ab is None else f"{ab:5.1f}°"
        y += self.text(f"|pan| {pm:.2f}   |tilt| {tm:.2f}   pan/tilt 夹角 {mix}   Tz {o.get('tz', 0):+.2f}",
                       (x, y), C_TEXT, self.f_small) + 3
        t = o.get("trans", V2())
        dir_s = f"{math.degrees(math.atan2(t.x, t.y)):+4.0f}°" if t.length() > 0.02 else "  —"
        y += self.text(f"输出指令: 前 {t.y:+.2f}  右 {t.x:+.2f}  方向 {dir_s}  扭 {o.get('rot', 0):+.2f}", (x, y),
                       C_OUT, self.f_small) + 3
        hd = math.degrees(wrap(r.drive_heading() - math.pi / 2))
        y += self.text(f"车速 {r.v_robot.length():.2f} m/s   ω {math.degrees(r.omega):+.0f}°/s   航向 {hd:+.0f}°",
                       (x, y), C_TEXT, self.f_small) + 12

        ch = self.chal
        y += self.text(f"T  定位挑战: {'进行中' if ch.active else '关闭'}    (X 清空成绩)", (x, y), C_TEXT) + 2
        if ch.active and ch.target:
            p_, h_ = ch.target
            e_pos = (r.pos - p_).length()
            e_h = abs(math.degrees(wrap(r.theta - h_)))
            y += self.text(f"   用时 {ch.t:5.1f}s   位置误差 {e_pos:4.2f}m   角度误差 {e_h:4.0f}°", (x, y),
                           C_TEXT, self.f_small) + 2
        if ch.times:
            last = ", ".join(f"{v:.1f}" for v in ch.times[-6:])
            avg = sum(ch.times) / len(ch.times)
            y += self.text(f"   完成 {len(ch.times)} 个, 平均 {avg:.2f}s", (x, y), C_OUT, self.f_small) + 2
            y += self.text(f"   最近: {last}", (x, y), C_DIM, self.f_small) + 2
        y += 12
        if self.wiz_msg:
            y += self.text(self.wiz_msg, (x, y), (255, 200, 80), self.f_small) + 6
        if self.show_help:
            helps = [
                "推帽子 / 倾斜帽子 = 平移,  扭转帽子 = 旋转   (H 隐藏帮助)",
                "跑偏? 先按 K 做方向校准, 再用 L 开关对比效果",
                "SpaceMouse 左键 = 陀螺仪归零,  右键 = 切换融合模式",
                "Z 归零航向   Space 重置机器人   Tab 键盘/SpaceMouse   Esc 退出",
                "挑战: 把车停进黄色虚影 (位置<12cm, 角度<6°, 基本静止)",
                "建议: 同一挑战分别用 PAN / TILT / FUSE 各跑 10 个对比平均用时",
            ]
            for s in helps:
                y += self.text(s, (x, y), C_DIM, self.f_small) + 2

    def draw_wizard(self):
        w = self.wiz
        if not w:
            return
        rect = pygame.Rect(FIELD_ORIGIN[0] + 90, FIELD_ORIGIN[1] + 150, ARENA_W * PPM - 180, 250)
        shade = pygame.Surface(rect.size, pygame.SRCALPHA)
        shade.fill((10, 12, 16, 225))
        self.canvas.blit(shade, rect)
        pygame.draw.rect(self.canvas, (255, 200, 80), rect, 2)
        step = w["step"]
        name, _ = CAL_DIRS[step % 4]
        x, y = rect.left + 24, rect.top + 20
        self.text(f"方向校准 {step + 1}/8", (x, y), (255, 200, 80), self.f_big)
        if step < 4:
            line = f"用平时开车的自然手法, 稳定地【推/平移】帽子向『{name}』并保持"
            sub = "不用刻意很纯, 就按你直觉的“往{}”来推。力度用你想要的『全速』力度。".format(name)
        else:
            line = f"只【倾斜】帽子向『{name}』并保持 (尽量不推)"
            sub = "按 S 跳过倾斜校准 (只保存 pan 校准)"
        self.text(line, (x, y + 50), C_TEXT, self.f)
        self.text(sub, (x, y + 80), C_DIM, self.f_small)
        phase_txt = {"wait_push": "等待输入…", "collect": "采集中, 保持住…", "wait_release": "OK! 松手回中"}
        self.text(phase_txt[w["phase"]], (x, y + 120), C_OUT, self.f)
        bar_w = rect.width - 48
        prog = clamp(w["t"] / 1.2, 0, 1) if w["phase"] == "collect" else (1.0 if w["phase"] == "wait_release" else 0)
        pygame.draw.rect(self.canvas, (50, 54, 64), (x, y + 160, bar_w, 14))
        pygame.draw.rect(self.canvas, C_OUT, (x, y + 160, bar_w * prog, 14))
        self.text("Esc 取消", (x, y + 190), C_DIM, self.f_small)

    def draw_3d(self):
        x, y = VIEW3D_X, 20
        self.text("SpaceMouse 实时姿态", (x, y), C_TEXT, self.f_big)
        img = self.smview.render(self.raw)
        self.canvas.blit(img, (x, y + 40))
        pygame.draw.rect(self.canvas, (70, 74, 86), (x, y + 40, *img.get_size()), 1)
        self.text("原始输入 (动作已放大)   绿箭头 = 前(远离你)", (x + 8, y + 46), C_DIM, self.f_small)

        tx, ty, tz, rx, ry, rz = self.raw
        pan, tilt = self.proc.raw_vectors(self.raw)
        thr = 0.08
        items = [
            ("推", C_PAN, f"{dir_label(pan)}  {pan.length():.2f}" if pan.length() > thr else "—"),
            ("倾", C_TILT, f"{dir_label(tilt)}  {tilt.length():.2f}" if tilt.length() > thr else "—"),
            ("扭", C_ROT, (f"{'顺时针' if rz > 0 else '逆时针'}  {abs(rz):.2f}") if abs(rz) > thr else "—"),
            ("压", C_DIM, (f"{'下压' if tz > 0 else '上提'}  {abs(tz):.2f}") if abs(tz) > thr else "—"),
        ]
        yy = y + 40 + img.get_height() + 14
        for i, (lab, col, val) in enumerate(items):
            cy = yy + i * 44
            pygame.draw.rect(self.canvas, col, (x, cy + 7, 6, 30))
            self.text(lab, (x + 14, cy + 1), col, self.f_huge)
            self.text(val, (x + 60, cy + 5), C_TEXT if val != "—" else C_DIM, self.f_big)

        yy += 4 * 44 + 10
        t, rot = self.proc.out.get("trans", V2()), self.proc.out.get("rot", 0.0)
        self.text("→ 底盘指令", (x, yy), C_OUT, self.f_big)
        move = f"{dir_label(t)} {t.length() * 100:3.0f}%" if t.length() > 0.02 else "停"
        spin = (f"{'顺' if rot > 0 else '逆'}转 {abs(rot) * 100:3.0f}%") if abs(rot) > 0.02 else "不转"
        self.text(f"平移: {move}    旋转: {spin}", (x, yy + 36), C_TEXT, self.f_big)
        self.text(f"模式 {self.proc.mode}   {'Field' if self.field_oriented else 'Robot'}-oriented"
                  f"   校准 {'ON' if self.proc.cal.enabled else 'OFF'}", (x, yy + 72), C_DIM, self.f)

    def draw(self):
        self.canvas.fill(C_BG)
        self.draw_field()
        self.draw_3d()
        self.draw_wizard()
        base_y = FIELD_ORIGIN[1] + ARENA_H * PPM + 40
        self.draw_puck(150, base_y + 135, 100)
        self.draw_bars(310, base_y + 40, 300)
        self.draw_chart(630, base_y + 40, 230, 230)
        self.draw_panel(FIELD_ORIGIN[0] + ARENA_W * PPM + 30)
        if self.win_size == (CANVAS_W, CANVAS_H):
            self.screen.blit(self.canvas, (0, 0))
        else:
            self.screen.blit(pygame.transform.smoothscale(self.canvas, self.win_size), (0, 0))
        pygame.display.flip()


if __name__ == "__main__":
    frames = 0
    if "--selftest" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--selftest") + 1])
    App(frames).run()
