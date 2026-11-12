// Cap movement drives the robot, never menus, settings or pause overlays.
window.__smNativeBridge = {
  controlsAllowed: () => location.hostname !== 'tylerhandel.github.io' ||
    (window.__sim?.ui?.screen === 'hud' && !window.__sim.ui.pop),
};
