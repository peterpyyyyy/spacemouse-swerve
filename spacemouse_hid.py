"""Raw HID fallback for macOS SpaceMouse devices that SDL doesn't enumerate.

3Dconnexion motion reports contain signed little-endian values in Tx/Ty/Tz/Rx/Ry/Rz
order, with a logical range of -350..350. Older devices split translation (report 1)
and rotation (report 2); newer devices put all six axes in report 1.
"""
import struct
import time


class HIDSpaceMouse:
    """Small joystick-compatible adapter; hidapi is imported only when opening."""

    def __init__(self, device, name):
        self.device = device
        self.name = name
        self.axes = [0.0] * 6
        self.buttons = [False, False]
        self.motion_times = [0.0, 0.0]

    @classmethod
    def open(cls):
        import hid

        for info in hid.enumerate():
            name = info.get("product_string") or "SpaceMouse"
            if info["vendor_id"] not in (0x256F, 0x046D):
                continue
            # Skip virtual mice, keyboards and other collections on the same device.
            if info.get("usage_page") != 1 or info.get("usage") != 8:
                continue
            if info["vendor_id"] == 0x046D and not any(
                    s in name.lower() for s in ("space", "3dconnexion")):
                continue
            device = hid.device()
            try:
                device.open_path(info["path"])
                device.set_nonblocking(True)
            except OSError:
                device.close()
                raise
            return cls(device, name)
        return None

    def decode(self, data, now):
        if not data:
            return
        report = data[0]
        if report == 1 and len(data) >= 7:
            count = 6 if len(data) >= 13 else 3
            values = struct.unpack_from("<%dh" % count, bytes(data), 1)
            self.axes[:count] = [max(-1.0, min(1.0, v / 350.0)) for v in values]
            self.motion_times[0] = now
            if count == 6:
                self.motion_times[1] = now
        elif report == 2 and len(data) >= 7:
            values = struct.unpack_from("<3h", bytes(data), 1)
            self.axes[3:] = [max(-1.0, min(1.0, v / 350.0)) for v in values]
            self.motion_times[1] = now
        elif report == 3 and len(data) >= 2:
            self.buttons = [bool(data[1] & 1), bool(data[1] & 2)]

    def poll(self):
        now = time.monotonic()
        for _ in range(64):  # Drain queued reports without blocking the render loop.
            data = self.device.read(64)
            if not data:
                break
            self.decode(data, now)
        # Stop on a lost release report or a silent/disconnected device.
        for group, stamp in enumerate(self.motion_times):
            if now - stamp > 0.5:
                self.axes[group * 3:group * 3 + 3] = [0.0] * 3

    def get_axis(self, index):
        return self.axes[index]

    def get_button(self, index):
        return self.buttons[index]

    def get_numbuttons(self):
        return len(self.buttons)

    def quit(self):
        self.device.close()
