"""Protocol checks for combined/split reports and lost-input handling."""
import struct
import unittest
from unittest.mock import patch

from spacemouse_hid import HIDSpaceMouse


class Device:
    def __init__(self, reports=()):
        self.reports = list(reports)

    def read(self, size):
        return self.reports.pop(0) if self.reports else []


class HIDTests(unittest.TestCase):
    def test_combined_axes_preserve_order_and_sign(self):
        sm = HIDSpaceMouse(Device(), "test")
        sm.decode(b"\x01" + struct.pack("<6h", 350, -350, 175, -175, 0, 35), 10)
        self.assertEqual(sm.axes, [1, -1, .5, -.5, 0, .1])
        self.assertEqual(sm.motion_times, [10, 10])

    def test_split_rotation_preserves_translation(self):
        sm = HIDSpaceMouse(Device(), "test")
        sm.decode(b"\x01" + struct.pack("<3h", 70, 140, 210), 10)
        sm.decode(b"\x02" + struct.pack("<3h", -70, -140, -210), 10.1)
        self.assertEqual(sm.axes, [.2, .4, .6, -.2, -.4, -.6])

    def test_buttons_and_unrelated_reports(self):
        sm = HIDSpaceMouse(Device(), "test")
        for report, expected in ((b"\x03\x01", [True, False]),
                                 (b"\x03\x02", [False, True]),
                                 (b"\x03\x00", [False, False])):
            sm.decode(report, 10)
            self.assertEqual(sm.buttons, expected)
        for report in ([], [1], [2, 0], [3], [23, 100]):
            sm.decode(report, 10)
        self.assertEqual(sm.axes, [0] * 6)

    def test_release_report_returns_to_zero(self):
        sm = HIDSpaceMouse(Device(), "test")
        sm.decode(b"\x01" + struct.pack("<6h", *([350] * 6)), 10)
        sm.decode(b"\x01" + bytes(12), 10.1)
        self.assertEqual(sm.axes, [0] * 6)

    def test_stale_translation_does_not_erase_fresh_rotation(self):
        sm = HIDSpaceMouse(Device(), "test")
        sm.decode(b"\x01" + struct.pack("<3h", 350, 350, 350), 10)
        sm.decode(b"\x02" + struct.pack("<3h", 350, 350, 350), 10.4)
        with patch("spacemouse_hid.time.monotonic", return_value=10.6):
            sm.poll()
        self.assertEqual(sm.axes, [0, 0, 0, 1, 1, 1])

    def test_poll_drains_queue_and_clamps_values(self):
        sm = HIDSpaceMouse(Device([
            b"\x01" + struct.pack("<6h", *([350] * 6)),
            b"\x01" + struct.pack("<6h", 700, -700, 0, 0, 0, 0),
        ]), "test")
        sm.poll()
        self.assertEqual(sm.axes, [1, -1, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
