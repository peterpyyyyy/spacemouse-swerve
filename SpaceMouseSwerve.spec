# Build with: .venv/bin/pyinstaller --noconfirm SpaceMouseSwerve.spec
from pathlib import Path
root = Path(SPECPATH)
a = Analysis(
    [str(root / 'macos_app.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root / 'spacemouse_gamepad.js'), '.'),
                        (str(root / 'desktop_policy.js'), '.'),
                        (str(root / 'assets/app-icon.svg'), 'assets'),
                        (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
                        (str(root / 'LICENSE'), '.'),
                        (str(root / 'build/licenses'), 'licenses')],
    hiddenimports=['hid', 'pygame', 'websockets.asyncio.server'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SpaceMouse Swerve',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, argv_emulation=False, target_arch='arm64',
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SpaceMouse Swerve')
app = BUNDLE(coll, name='SpaceMouse Swerve.app', icon=str(root/'build/SpaceMouse.icns'),
    bundle_identifier='com.peterpyyyyy.spacemouse-swerve',
    info_plist={
        'CFBundleShortVersionString':'1.0.0', 'CFBundleVersion':'1',
        'NSHighResolutionCapable':True, 'LSMinimumSystemVersion':'14.0',
        'LSMultipleInstancesProhibited':True,
        'NSHumanReadableCopyright':'SpaceMouse Swerve contributors',
    })
