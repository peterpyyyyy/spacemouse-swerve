#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -sm)" != "Darwin arm64" ]; then
  echo "此构建脚本面向 Apple Silicon Mac。"
  exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements-build.txt
mkdir -p build/licenses
mkdir -p build/licenses/Qt build/licenses/Python
if [ ! -f build/licenses/Qt/LGPL-3.0.txt ]; then
  curl -fsSL https://www.gnu.org/licenses/lgpl-3.0.txt -o build/licenses/Qt/LGPL-3.0.txt
fi
if [ ! -f build/licenses/Qt/GPL-3.0.txt ]; then
  curl -fsSL https://www.gnu.org/licenses/gpl-3.0.txt -o build/licenses/Qt/GPL-3.0.txt
fi
.venv/bin/python tools/make_macos_icon.py build/SpaceMouse.icns
.venv/bin/python - <<'PY'
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys
python_license=Path(sys.base_prefix)/'Resources/English.lproj/Documentation/_sources/license.rst.txt'
if python_license.exists(): shutil.copy2(python_license,Path('build/licenses/Python/LICENSE.txt'))
for package in ('PySide6','PySide6_Essentials','PySide6_Addons','PySide6_WebEngine','shiboken6','pygame','websockets','hidapi','pyinstaller'):
    dist=distribution(package)
    for f in dist.files or []:
        if 'license' in str(f).lower() or 'copying' in str(f).lower():
            src=Path(dist.locate_file(f))
            if src.is_file():
                target=Path('build/licenses')/package/str(f)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,target)
PY
.venv/bin/pyinstaller --noconfirm SpaceMouseSwerve.spec
/usr/bin/codesign --verify --deep --strict "dist/SpaceMouse Swerve.app"
echo "完成：dist/SpaceMouse Swerve.app"
