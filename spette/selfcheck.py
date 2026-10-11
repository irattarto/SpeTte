"""`SpeTte --selfcheck [report-file]`: checks a built package (bundled files, libraries) and exits 0 or 1.

The build workflow runs this on the packaged program, so a missing file or library fails the build
instead of failing on a user's computer.
"""

import importlib
import sys
from typing import List, Tuple

REQUIRED_FILES = (
    "data/icons/app_icon.png", "data/icons/tray_idle.png", "data/icons/tray_recording.png",
    "data/icons/tray_done.png", "data/icons/icon_done.png",
    "LICENSE", "THIRD_PARTY_NOTICES.md",
)
REQUIRED_MODULES = (
    "PyQt6.QtWidgets", "speech_recognition", "pyaudio",
    "faster_whisper", "ctranslate2", "onnxruntime", "av", "pynput", "requests", "keyring",
    "spette.keystore",
    "spette.main_window",
)


def run_checks() -> List[Tuple[bool, str]]:
    from spette.resources import resource_path
    results = []
    for relative in REQUIRED_FILES:
        path = resource_path(relative)
        results.append((path.is_file(), f"file {relative}"))
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
            results.append((True, f"module {name}"))
        except ImportError as e:
            if name == "pynput" and "platform is not supported" in str(e):
                results.append((True, "module pynput (no display here; the program reports this itself)"))
            else:
                results.append((False, f"module {name}: {type(e).__name__}: {e}"))
        except Exception as e:                      # a library that fails to load
            results.append((False, f"module {name}: {type(e).__name__}: {e}"))
    return results


def main(report_path: str = "") -> int:
    results = run_checks()
    lines = [("ok      " if ok else "MISSING ") + what for ok, what in results]
    failed = [what for ok, what in results if not ok]
    lines.append(f"{len(results) - len(failed)} of {len(results)} checks passed")
    text = "\n".join(lines) + "\n"
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 1 if failed else 0
