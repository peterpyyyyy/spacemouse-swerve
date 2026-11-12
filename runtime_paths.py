"""Separate bundled read-only resources from each user's writable settings."""
import os
import sys
from pathlib import Path


def resource_path(name):
    return Path(__file__).resolve().parent / name


def app_data_dir():
    override = os.environ.get("SPACEMOUSE_DATA_DIR")
    directory = Path(override) if override else Path.home() / "Library/Application Support/SpaceMouse Swerve"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def state_path(name):
    if getattr(sys, "frozen", False) or os.environ.get("SPACEMOUSE_DATA_DIR"):
        return str(app_data_dir() / name)
    return str(resource_path(name))
