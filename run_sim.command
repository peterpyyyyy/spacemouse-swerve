#!/bin/bash
# macOS: double-click in Finder to start the local swerve simulator.
cd "$(dirname "$0")" || exit 1
SCRIPT=swerve_sim.py exec ./run_bridge.command "$@"
