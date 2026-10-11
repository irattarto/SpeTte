# Third-party notices

SpeTte itself is released under the MIT licence (see `LICENSE`). It is built on, or can download, the following
software. Each keeps its own licence; the full texts are in the packages themselves and on their project pages.

| Component | Used for | Licence |
|---|---|---|
| PyQt6 (Riverbank Computing) | the user interface | GPL v3 (so the distributed program is subject to the GPL v3 as well) |
| Qt 6 | the user interface | LGPL v3 / GPL v3 |
| faster-whisper, CTranslate2 | local speech recognition | MIT |
| OpenAI Whisper models (downloaded on first use) | local speech recognition | MIT |
| SpeechRecognition | recording and the optional Google recognizer | BSD-3-Clause |
| PyAudio / PortAudio | microphone | MIT |
| PyAV (FFmpeg libraries) | reading audio | BSD-3-Clause / LGPL v2.1+ |
| pynput, python-xlib | system-wide shortcut | LGPL v3 / LGPL v2.1+ |
| keyring (with pywin32-ctypes on Windows, SecretStorage and jeepney on Linux) | keeping the optional Google API key in the system keyring | MIT, BSD-3-Clause, BSD-3-Clause, MIT |
| requests | one-time NVIDIA library download | Apache-2.0 |
| NVIDIA CUDA runtime libraries (Windows, downloaded on request) | GPU recognition | NVIDIA CUDA EULA |
| PyInstaller | packaging only | GPL v2+ with the bootloader exception |
