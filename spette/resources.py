"""Finding bundled files (icons), both from source and from the PyInstaller build."""

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def icon(name: str) -> QIcon:
    """An icon from data/icons (an empty QIcon when the file is missing)."""
    path = resource_path(f"data/icons/{name}")
    return QIcon(str(path)) if path.is_file() else QIcon()
