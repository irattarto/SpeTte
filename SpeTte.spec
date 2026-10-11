# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SpeTte (Windows and Linux, onedir).
Build:  pyinstaller --noconfirm SpeTte.spec
Output: dist/SpeTte/ (Windows)  or  dist/spette/ (Linux)
Linux AppImage: packaging/linux/build_appimage.sh
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).absolute()
IS_WINDOWS = sys.platform == 'win32'
APP_NAME = 'SpeTte' if IS_WINDOWS else 'spette'
_ico = project_root / 'data' / 'icons' / 'app_icon.ico'   # generated from the PNG by the build workflow
ICON = str(_ico) if IS_WINDOWS and _ico.exists() else None

datas = [(str(project_root / 'data'), 'data'), (str(project_root / 'README.md'), '.'),
         (str(project_root / 'LICENSE'), '.'), (str(project_root / 'THIRD_PARTY_NOTICES.md'), '.')]
binaries = []
hiddenimports = []


# Parts of a package that only tools need. Importing them while PyInstaller collects the package crashed its
# helper process on Windows (onnxruntime.quantization), and SpeTte only runs models, never converts them.
_SKIP_SUBMODULES = {'onnxruntime': ('onnxruntime.quantization', 'onnxruntime.transformers', 'onnxruntime.tools')}


def _optional(pkg):
    """Bundle a package completely, if it is installed."""
    skip = _SKIP_SUBMODULES.get(pkg, ())
    try:
        d, b, h = collect_all(pkg, filter_submodules=lambda name: not name.startswith(skip) if skip else True)
    except Exception as e:
        print(f"WARNING: could not bundle optional package {pkg}: {e}")
        return
    datas.extend(d); binaries.extend(b); hiddenimports.extend(h)


for _pkg in ('pyaudio', 'speech_recognition', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'av', 'tokenizers',
             'pynput', 'Xlib'):   # pynput: system-wide shortcut (Xlib is its Linux backend)
    _optional(_pkg)

_excludes = [
    'PySide6', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
    'torch', 'torchvision', 'torchaudio', 'transformers', 'matplotlib',
    'pandas', 'scipy', 'IPython', 'notebook', 'tkinter',
    'onnxruntime.quantization', 'onnxruntime.transformers', 'onnxruntime.tools',
    # NOTE: numpy is intentionally NOT excluded (needed by ctranslate2/faster-whisper)
]

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=_excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON,
    console=False,
    upx=False,  # UPX can corrupt Qt libraries
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
