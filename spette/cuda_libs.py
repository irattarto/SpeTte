"""
NVIDIA CUDA libraries (cuBLAS + cuDNN) for GPU transcription on Windows.

The build does not ship them (about 1 GB). When an NVIDIA GPU is present the app offers to download them once
from PyPI (NVIDIA's own wheels, SHA-256 verified) into its data folder; this module finds, downloads and registers them.
"""

import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from spette.logger import get_logger

logger = get_logger('cuda_libs')

# Exact wheels (version, SHA-256 of the file, size in bytes). The hash is part of the program, not taken from the
# download's own metadata, so a changed or swapped file is refused. To update: look up the new wheel on PyPI.
PINNED = {
    'nvidia-cublas-cu12': ('12.9.2.10', '623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661', 553162896),
    'nvidia-cudnn-cu12': ('9.27.0.42', '06e9b0026f3bad97d2b58666330fabec04fe1672f776661ecb0ce0029c27f142', 743068852),
}
PACKAGES = tuple(PINNED)
DOWNLOAD_HOST = 'https://files.pythonhosted.org/'
MAX_UNPACKED = 3 * 1024 ** 3          # a wheel that unpacks to more than this is not what we expect
REQUIRED_DLLS = ('cublas64_12.dll', 'cublasLt64_12.dll', 'cudnn64_9.dll')
_registered = False


class CudaDownloadError(Exception):
    """An error whose text can be shown to the user as is."""


def supported() -> bool:
    """Only Windows builds need this (Linux uses the system CUDA install)."""
    return sys.platform == 'win32'


def cuda_dir() -> Path:
    from spette.paths import get_data_dir
    path = get_data_dir() / 'models' / 'cuda'
    path.mkdir(parents=True, exist_ok=True)
    return path


def libs_present() -> bool:
    folder = cuda_dir()
    return all((folder / name).exists() for name in REQUIRED_DLLS)


def register() -> bool:
    """Make the downloaded DLLs loadable by ctranslate2. Safe to call repeatedly; True when they are available."""
    global _registered
    if not supported() or not libs_present():
        return False
    if not _registered:
        folder = str(cuda_dir())
        try:
            os.add_dll_directory(folder)
        except (OSError, AttributeError) as e:
            logger.debug(f"add_dll_directory failed: {e}")
        os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')
        _registered = True
    return True


def download(progress: Optional[Callable[[str], None]] = None,
             should_stop: Optional[Callable[[], bool]] = None) -> None:
    """Download and unpack the libraries. Raises CudaDownloadError with a readable reason."""
    if not supported():
        raise CudaDownloadError("Automatic CUDA setup is only available on Windows.")
    import requests
    say = progress or (lambda _msg: None)
    folder = cuda_dir()
    try:
        for number, package in enumerate(PACKAGES, 1):
            say(f"Looking up {package}...")
            wheel = _find_wheel(requests, package)
            archive = folder / (wheel['filename'] + '.part')
            try:
                _download_file(requests, wheel, archive, lambda m, n=number: say(f"GPU libraries, part {n} of {len(PACKAGES)}: {m}"), should_stop)
                _extract_dlls(archive, folder)
            finally:
                archive.unlink(missing_ok=True)
    except requests.exceptions.RequestException as e:
        raise CudaDownloadError(f"Download failed ({type(e).__name__}). Check the internet connection and try again.")
    except zipfile.BadZipFile:
        raise CudaDownloadError("The downloaded file was damaged. Try again.")
    if not libs_present():
        raise CudaDownloadError("The download finished but the expected CUDA libraries were not found.")
    register()
    say("GPU libraries installed.")


def _find_wheel(requests, package: str) -> dict:
    """The pinned wheel's download address from PyPI; the expected hash and size are ours."""
    version, sha256, size = PINNED[package]
    data = requests.get(f"https://pypi.org/pypi/{package}/{version}/json", timeout=30).json()
    for entry in data.get('urls', []):
        if entry.get('filename', '').endswith('win_amd64.whl') and entry.get('url', '').startswith(DOWNLOAD_HOST):
            if entry.get('digests', {}).get('sha256') == sha256:
                return {**entry, 'size': size, 'digests': {'sha256': sha256}}
    raise CudaDownloadError(f"The expected Windows build of {package} {version} was not found on PyPI.")


def _download_file(requests, wheel: dict, target: Path, say, should_stop) -> None:
    digest = hashlib.sha256()
    total = int(wheel['size'])
    done = 0
    with requests.get(wheel['url'], stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(target, 'wb') as out:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if should_stop and should_stop():
                    raise CudaDownloadError("Cancelled.")
                done += len(chunk)
                if done > total:
                    raise CudaDownloadError("The download is larger than expected and was stopped.")
                out.write(chunk)
                digest.update(chunk)
                pct = f" {done * 100 // total}%" if total else ""
                say(f"{done // (1024 * 1024)} MB{pct}")
    if digest.hexdigest() != wheel['digests']['sha256']:
        raise CudaDownloadError("The downloaded file failed its checksum and was discarded.")


def _extract_dlls(archive: Path, folder: Path) -> List[str]:
    names = []
    with zipfile.ZipFile(archive) as zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNPACKED:
            raise CudaDownloadError("The downloaded file unpacks to more than expected and was refused.")
        for info in zf.infolist():
            parts = info.filename.split('/')
            if len(parts) >= 2 and parts[-2] == 'bin' and parts[-1].lower().endswith('.dll'):
                target = folder / parts[-1]  # flat file name only: nothing can escape the folder
                partial = target.with_name(target.name + '.tmp')
                try:
                    with zf.open(info) as src, open(partial, 'wb') as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    os.replace(partial, target)  # a DLL is either complete or absent, never cut off
                finally:
                    partial.unlink(missing_ok=True)
                names.append(parts[-1])
    return names
