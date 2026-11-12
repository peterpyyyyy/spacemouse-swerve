"""Driver ownership and writable settings are important across app launches."""
import os
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from macos_app import DriverSession, HELPER
from runtime_paths import state_path


class DriverTests(unittest.TestCase):
    @patch("macos_app.subprocess.Popen")
    @patch("macos_app.subprocess.run", return_value=SimpleNamespace(stdout="123\n"))
    def test_running_driver_is_left_running(self, run, popen):
        session = DriverSession()
        session.restore()
        popen.assert_not_called()

    @patch("macos_app.subprocess.Popen")
    @patch("macos_app.Path.exists", return_value=True)
    @patch("macos_app.os.kill")
    @patch("macos_app.subprocess.run", return_value=SimpleNamespace(stdout=""))
    def test_starts_driver_without_killing_any_process(self, run, kill, exists, popen):
        session = DriverSession()
        session.prepare()
        kill.assert_not_called()
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["/usr/bin/open", "-g", HELPER])

    def test_native_driver_abi(self):
        import ctypes
        from spacemouse_driver import DeviceState
        self.assertEqual(ctypes.sizeof(DeviceState),48)
        self.assertEqual(DeviceState.axis.offset,30)

    def test_app_settings_live_outside_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"SPACEMOUSE_DATA_DIR":directory}):
                self.assertEqual(Path(state_path("calibration.json")), Path(directory)/"calibration.json")


if __name__ == "__main__":
    unittest.main()
