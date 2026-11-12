"""macOS 3DxWare client: keep the official driver running to suppress pointer input.

Uses the installed ConnexionClient API and its documented packed DeviceState ABI.
The vendor framework is loaded from /Library at runtime, never redistributed.
"""
import ctypes as C
import threading
import time
from pathlib import Path

FRAMEWORK = Path('/Library') / 'Frameworks/3DconnexionClient.framework/3DconnexionClient'


class DeviceState(C.Structure):
    _pack_ = 2
    _fields_ = [('version',C.c_uint16),('client',C.c_uint16),('command',C.c_uint16),
                ('param',C.c_int16),('value',C.c_int32),('time',C.c_uint64),
                ('report',C.c_uint8*8),('buttons8',C.c_uint16),('axis',C.c_int16*6),
                ('address',C.c_uint16),('buttons',C.c_uint32)]


def fourcc(text):
    return int.from_bytes(text.encode('ascii'),'big')


class DriverSpaceMouse:
    def __init__(self, lib):
        self.lib = lib
        self.name = 'SpaceMouse (3DxWare)'
        self.axes = [0.0]*6
        self.buttons = [False,False]
        self.lock = threading.Lock()
        self.stamp = 0.0
        self.checked = 0.0
        self.active = False
        self.client = 0
        callback_type = C.CFUNCTYPE(None,C.c_uint32,C.c_uint32,C.c_void_p)
        self.callback = callback_type(self.message)
        lib.SetConnexionHandlers.argtypes = [callback_type,C.c_void_p,C.c_void_p,C.c_bool]
        lib.SetConnexionHandlers.restype = C.c_int16
        lib.RegisterConnexionClient.argtypes = [C.c_uint32,C.c_char_p,C.c_uint16,C.c_uint32]
        lib.RegisterConnexionClient.restype = C.c_uint16
        lib.ConnexionClientControl.argtypes = [C.c_uint16,C.c_uint32,C.c_int32,C.POINTER(C.c_int32)]
        lib.ConnexionClientControl.restype = C.c_int16
        lib.ConnexionControl.argtypes = [C.c_uint32,C.c_int32,C.POINTER(C.c_int32)]
        lib.ConnexionControl.restype = C.c_int16
        lib.UnregisterConnexionClient.argtypes = [C.c_uint16]
        lib.SetConnexionClientButtonMask.argtypes = [C.c_uint16,C.c_uint32]
        if lib.SetConnexionHandlers(self.callback,None,None,True) != 0:
            raise OSError('Cannot connect to 3DconnexionHelper')
        name = b'SpaceMouse Swerve'
        self.client = lib.RegisterConnexionClient(0x2B2B2B2B,bytes([len(name)])+name,1,0x3FFF)
        if not self.client:
            lib.CleanupConnexionHandlers()
            raise OSError('Cannot register SpaceMouse client')
        lib.SetConnexionClientButtonMask(self.client,0xFFFFFFFF)

    @classmethod
    def open(cls):
        if not FRAMEWORK.exists():
            return None
        lib = C.CDLL(str(FRAMEWORK))
        device = cls(lib)
        result = C.c_int32()
        if lib.ConnexionControl(fourcc('3did'),0,C.byref(result)) != 0 or not result.value:
            device.quit()
            return None
        return device

    def set_active(self, active):
        if active == self.active:
            return
        result = C.c_int32()
        code = fourcc('3dac' if active else '3ddc')
        error = self.lib.ConnexionClientControl(self.client,code,0,C.byref(result))
        if error != 0:
            raise OSError('Cannot activate SpaceMouse client')
        self.active = active
        if not active:
            with self.lock:
                self.axes = [0.0]*6
                self.buttons = [False,False]

    def message(self, product, message, argument):
        if message != fourcc('3dSR') or not argument:
            return
        state = C.cast(argument,C.POINTER(DeviceState)).contents
        if state.client != self.client:
            return
        with self.lock:
            if state.command == 3:
                self.axes = [max(-1.0,min(1.0,v/350.0)) for v in state.axis]
                self.stamp = time.monotonic()
            if state.command in (2,3):
                self.buttons = [bool(state.buttons&1),bool(state.buttons&2)]

    def poll(self):
        now = time.monotonic()
        if now-self.checked>1:
            self.checked = now
            result = C.c_int32()
            if self.lib.ConnexionControl(fourcc('3did'),0,C.byref(result)) != 0 or not result.value:
                raise OSError('SpaceMouse disconnected')
        with self.lock:
            if now-self.stamp>.5:
                self.axes = [0.0]*6

    def get_axis(self,index):
        return self.axes[index]

    def get_button(self,index):
        return self.buttons[index]

    def get_numbuttons(self):
        return 2

    def quit(self):
        if self.client:
            self.lib.UnregisterConnexionClient(self.client)
            self.lib.CleanupConnexionHandlers()
            self.client = 0
