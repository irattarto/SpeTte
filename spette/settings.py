"""Speech-to-text settings, stored with QSettings."""

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QSettings

from spette.hotkeys import DEFAULT_COMBO, MODE_TOGGLE, MODES, combo_to_setting, parse_combo

PROVIDERS = ("whisper", "google")
DEVICES = ("auto", "cuda", "cpu")
MODEL_CHOICES = ("auto", "tiny", "base", "small", "medium", "large-v3-turbo", "large-v3")
LANGUAGES = [
    ("hu-HU", "Hungarian"), ("en-US", "English (US)"), ("en-GB", "English (UK)"), ("de-DE", "German"),
    ("fr-FR", "French"), ("es-ES", "Spanish"), ("it-IT", "Italian"), ("pt-BR", "Portuguese (Brazil)"),
    ("ru-RU", "Russian"), ("ja-JP", "Japanese"), ("ko-KR", "Korean"), ("zh-CN", "Chinese (Simplified)"),
]
MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS = 30, 480, 120
GOOGLE_MAX_SECONDS = 60   # the free Google recognizer rejects recordings of about a minute or more


@dataclass
class SttSettings:
    provider: str = "whisper"          # whisper (local, offline) or google (cloud)
    language: str = "hu-HU"
    device_index: Optional[int] = None  # microphone; None = system default
    device_name: str = ""               # the microphone's name: its index changes when devices come and go
    whisper_model: str = "small"
    whisper_device: str = "auto"
    max_seconds: int = DEFAULT_SECONDS
    gpu_prompt_declined: bool = False
    minimize_to_tray: bool = True       # minimizing hides the window in the tray
    close_to_tray: bool = True          # closing the window keeps the program running in the tray
    hotkey_enabled: bool = True         # system-wide recording shortcut
    hotkey: str = DEFAULT_COMBO         # e.g. "f9", "ctrl+shift", "ctrl+alt+r"
    hotkey_mode: str = MODE_TOGGLE      # toggle: press to start/stop; push: hold to record
    background_replace: bool = True     # recorded while SpeTte is in the background: replace the old text
    background_copy: bool = True        # recorded while SpeTte is in the background: copy the result to the clipboard

    def recording_limit(self) -> int:
        """Seconds after which a recording stops by itself (Google cannot take more than a minute)."""
        return min(self.max_seconds, GOOGLE_MAX_SECONDS) if self.provider == "google" else self.max_seconds


def _flag(value, default: bool) -> bool:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return default


class Settings:
    """Loads and saves SttSettings (and the window geometry)."""

    def __init__(self, qsettings: Optional[QSettings] = None):
        self._q = qsettings or QSettings("SpeTte", "SpeTte")
        self.stt = SttSettings()
        self.load()

    def load(self) -> None:
        q, s = self._q, self.stt
        provider = str(q.value("provider", "whisper"))
        s.provider = provider if provider in PROVIDERS else "whisper"
        language = str(q.value("language", "hu-HU"))
        s.language = language if language in dict(LANGUAGES) else "hu-HU"
        device = q.value("device_index", None)
        try:
            s.device_index = None if device in (None, "") else int(device)
        except (TypeError, ValueError):
            s.device_index = None
        s.device_name = str(q.value("device_name", "") or "")
        model = str(q.value("whisper_model", "small"))
        s.whisper_model = "large-v3" if model == "large" else model if model in MODEL_CHOICES else "small"
        whisper_device = str(q.value("whisper_device", "auto"))
        s.whisper_device = whisper_device if whisper_device in DEVICES else "auto"
        try:
            seconds = int(q.value("max_seconds", DEFAULT_SECONDS))
        except (TypeError, ValueError):
            seconds = DEFAULT_SECONDS
        s.max_seconds = min(MAX_SECONDS, max(MIN_SECONDS, seconds))
        s.gpu_prompt_declined = _flag(q.value("gpu_prompt_declined", "false"), False)
        s.minimize_to_tray = _flag(q.value("minimize_to_tray", "true"), True)
        s.close_to_tray = _flag(q.value("close_to_tray", "true"), True)
        s.hotkey_enabled = _flag(q.value("hotkey_enabled", "true"), True)
        s.hotkey = combo_to_setting(parse_combo(str(q.value("hotkey", DEFAULT_COMBO))))
        s.background_replace = _flag(q.value("background_replace", "true"), True)
        s.background_copy = _flag(q.value("background_copy", "true"), True)
        mode = str(q.value("hotkey_mode", MODE_TOGGLE))
        s.hotkey_mode = mode if mode in MODES else MODE_TOGGLE

    def save(self) -> None:
        q, s = self._q, self.stt
        q.setValue("provider", s.provider)
        q.setValue("language", s.language)
        q.setValue("device_index", "" if s.device_index is None else s.device_index)
        q.setValue("device_name", s.device_name)
        q.setValue("whisper_model", s.whisper_model)
        q.setValue("whisper_device", s.whisper_device)
        q.setValue("max_seconds", s.max_seconds)
        q.setValue("gpu_prompt_declined", s.gpu_prompt_declined)
        q.setValue("minimize_to_tray", s.minimize_to_tray)
        q.setValue("close_to_tray", s.close_to_tray)
        q.setValue("hotkey_enabled", s.hotkey_enabled)
        q.setValue("hotkey", s.hotkey)
        q.setValue("hotkey_mode", s.hotkey_mode)
        q.setValue("background_replace", s.background_replace)
        q.setValue("background_copy", s.background_copy)
        q.sync()

    def geometry(self):
        return self._q.value("window/geometry", None)

    def set_geometry(self, value) -> None:
        self._q.setValue("window/geometry", value)
        self._q.sync()
