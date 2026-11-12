@echo off
cd /d "%~dp0"
set SCRIPT=swerve_sim.py
call run_bridge.bat %*
