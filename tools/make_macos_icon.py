"""Render the repository's vector icon into a standard macOS .icns."""
import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication([])
root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve()
iconset = out.parent / "SpaceMouse.iconset"
iconset.mkdir(parents=True, exist_ok=True)
renderer = QSvgRenderer(str(root / "assets/app-icon.svg"))
for size in (16,32,128,256,512):
    for scale in (1,2):
        image = QImage(size*scale,size*scale,QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        suffix = "@2x" if scale==2 else ""
        image.save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
subprocess.run(["/usr/bin/iconutil","-c","icns",str(iconset),"-o",str(out)],check=True)
