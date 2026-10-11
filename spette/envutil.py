"""The environment for programs SpeTte starts (nvidia-smi).

A PyInstaller build and an AppImage point LD_LIBRARY_PATH at their own bundled libraries. A child program that
inherits it can load those instead of the system's and fail, so the bundle's folders are taken out again.
"""

import os
import sys
from typing import Dict, Mapping, Optional


def _under(path: str, folders) -> bool:
    path = path.rstrip("/")
    return any(path == f.rstrip("/") or path.startswith(f.rstrip("/") + "/") for f in folders if f)


def clean_environment(extra: Optional[Mapping[str, str]] = None,
                      base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """A copy of the environment that is safe to give to another program.

    ``extra`` is added last.
    """
    env = dict(os.environ if base is None else base)
    bundle = [getattr(sys, "_MEIPASS", None), env.get("APPDIR")]
    if "LD_LIBRARY_PATH_ORIG" in env:                   # set by the PyInstaller bootloader: the value before it
        original = env["LD_LIBRARY_PATH_ORIG"]
        if original:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    parts = [p for p in env.get("LD_LIBRARY_PATH", "").split(os.pathsep) if p and not _under(p, bundle)]
    if parts:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(parts)
    else:
        env.pop("LD_LIBRARY_PATH", None)
    if extra:
        env.update(extra)
    return env
