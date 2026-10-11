"""Where SpeTte keeps its files (settings are stored by Qt; this is for models and logs)."""

import os
import shutil
import sys
from pathlib import Path

from spette.logger import get_logger


def _windows_dirs():
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "SpeTte"
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "SpeTte"
    return local, roaming


def get_data_dir() -> Path:
    """The data folder, created if needed.

    Order: the SPETTE_DATA_DIR environment variable (portable use, tests), then %LOCALAPPDATA%\\SpeTte on
    Windows (machine-local data of many GB does not belong in the roaming profile), then
    $XDG_DATA_HOME/SpeTte (default ~/.local/share/SpeTte) elsewhere.

    Versions up to 0.3.0 used %APPDATA%\\SpeTte on Windows; that folder is moved over once.
    """
    override = os.environ.get("SPETTE_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        path, legacy = _windows_dirs()
        _migrate(legacy, path)
    else:
        path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "SpeTte"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate(legacy: Path, new: Path) -> None:
    if new.exists() or not legacy.is_dir():
        return
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(new))
    except OSError as e:
        get_logger("paths").warning(f"Could not move {legacy} to {new}: {e}")
