@echo off
chcp 65001 >nul
rem Windows: double-click. First run creates .venv and installs deps.
cd /d "%~dp0"
if "%SCRIPT%"=="" set SCRIPT=spacemouse_bridge.py
if not exist .venv\Scripts\python.exe (
  echo 首次运行: 创建 .venv 并安装依赖...
  py -3 -m venv .venv 2>nul || python -m venv .venv || (echo 需要 Python 3.9+ & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt || (rmdir /s /q .venv & echo 依赖安装失败 & pause & exit /b 1)
)
.venv\Scripts\python %SCRIPT% %*
if errorlevel 1 pause
