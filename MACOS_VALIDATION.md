# macOS desktop validation — 2026-11-12

## Current supported path

Apple Silicon / macOS 27.2.1, Python 3.13.1, pygame 2.6.1, PySide6 6.12.0, SpaceMouse Wireless BT over USB, with 3DxWare installed. The app uses the installed ConnexionClient framework and **keeps 3DconnexionHelper running**. The framework itself is not bundled.

Earlier raw-HID experiments required stopping the helper. That exposed a documented macOS behavior: the cap can start moving the desktop pointer. Do not follow that old advice. The desktop app now uses the vendor client API instead, and the user confirmed game input works without moving the desktop pointer.

## Confirmed

- Repository integrity and source completeness: `git fsck --full` passed.
- Real hardware: 880 recorded raw reports covered positive and negative movement on all six axes; release returned to zero. Replayed data drove local swerve translation and rotation.
- Vendor driver input: native ConnexionClient connected, six-axis input reached the embedded game, and the user confirmed normal control without desktop pointer movement.
- The original browser path was tested in REBUILT: LX/LY/RX peaks 1.0/1.0/0.8547; J/K reached the game as `lt=1, intake=true` and `rt=1, shoot=true` during teleop. Native transport preserves this gamepad layout.
- Standalone arm64 app launched without an external Python process, loaded the online game and connected the vendor driver and virtual gamepad.
- Final packaged smoke test returned `ok: true`, `frozen: true`, `native: true`, and a connected SpaceMouse via 3DxWare.
- English app labels, collapsed sidebar, visible corner 3D pose, and pose hiding all passed packaged UI checks; screenshot inspected visually.
- REBUILT menus, settings, pause, results and editor screens output neutral axes/buttons. Gameplay HUD permits input; HUD popovers lock it again.
- Ten Python unit tests passed. JavaScript regression checks passed for keyboard mapping/release, blur, toggle, pause, stream stall, disconnect, native transport, and the real REBUILT screen policy.
- Dependency checks, source compilation and macOS deep/strict ad-hoc signature verification passed.
- Personal settings/calibration remain outside the bundle and repository. Browser profiles/logs are user-specific app data.

## Limits

One Mac and one device over USB were tested. Bluetooth, wireless receiver, Intel builds, Windows/Linux desktop builds, all other SpaceMouse models, and every robot/game mode remain unverified. The local pygame practice UI retains its existing Chinese teaching labels; the new desktop shell supports Chinese/English. Third-party game menus are served by their original authors.

The app is ad-hoc signed, not Apple Developer ID signed/notarized. The online game needs internet and has an optional HDR asset 404; gameplay still loaded during testing. The raw HID fallback without the vendor framework is experimental and is not the primary tested release path.

## Reproduce

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_gamepad.cjs
.venv/bin/python -m pip check
./tools/build_macos_app.sh
"dist/SpaceMouse Swerve.app/Contents/MacOS/SpaceMouse Swerve" --smoke-test /tmp/spacemouse-smoke.json
```

The packaged smoke test requires the physical device, official driver and internet access; synthetic tests do not replace hardware verification.
