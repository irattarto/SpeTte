from PyQt6.QtCore import QSettings

from spette.settings import Settings, SttSettings


def test_defaults(settings):
    s = settings.stt
    assert (s.provider, s.language, s.device_index, s.whisper_model, s.whisper_device) == \
           ("whisper", "hu-HU", None, "small", "auto")
    assert s.max_seconds == 120 and s.gpu_prompt_declined is False


def test_round_trip(settings, tmp_path):
    s = settings.stt
    s.provider, s.language, s.device_index = "google", "en-US", 3
    s.whisper_model, s.whisper_device, s.max_seconds, s.gpu_prompt_declined = "medium", "cpu", 300, True
    settings.save()
    again = Settings(QSettings(str(tmp_path / "spette.ini"), QSettings.Format.IniFormat)).stt
    assert (again.provider, again.language, again.device_index) == ("google", "en-US", 3)
    assert (again.whisper_model, again.whisper_device, again.max_seconds, again.gpu_prompt_declined) == \
           ("medium", "cpu", 300, True)


def test_bad_stored_values_fall_back(tmp_path):
    q = QSettings(str(tmp_path / "bad.ini"), QSettings.Format.IniFormat)
    q.setValue("provider", "openai")
    q.setValue("language", "xx-XX")
    q.setValue("device_index", "not a number")
    q.setValue("whisper_model", "large")        # the old name maps to large-v3
    q.setValue("whisper_device", "tpu")
    q.setValue("max_seconds", 99999)
    s = Settings(q).stt
    assert (s.provider, s.language, s.device_index, s.whisper_model, s.whisper_device) == \
           ("whisper", "hu-HU", None, "large-v3", "auto")
    assert s.max_seconds == 480


def test_google_recordings_are_capped_at_a_minute():
    assert SttSettings(provider="google", max_seconds=300).recording_limit() == 60
    assert SttSettings(provider="whisper", max_seconds=300).recording_limit() == 300


def test_tray_and_shortcut_defaults(tmp_path):
    q = QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat)
    s = Settings(q).stt
    assert s.minimize_to_tray and s.close_to_tray and s.hotkey_enabled
    assert (s.hotkey, s.hotkey_mode) == ("f9", "toggle")


def test_tray_and_shortcut_round_trip_and_bad_values(settings, tmp_path):
    s = settings.stt
    s.minimize_to_tray, s.close_to_tray, s.hotkey_enabled = False, False, True
    s.hotkey, s.hotkey_mode = "ctrl+shift", "push"
    settings.save()
    again = Settings(QSettings(str(tmp_path / "spette.ini"), QSettings.Format.IniFormat)).stt
    assert (again.minimize_to_tray, again.close_to_tray, again.hotkey_enabled) == (False, False, True)
    assert (again.hotkey, again.hotkey_mode) == ("ctrl+shift", "push")

    q = QSettings(str(tmp_path / "bad.ini"), QSettings.Format.IniFormat)
    q.setValue("hotkey", "ctrl")           # one modifier alone is refused
    q.setValue("hotkey_mode", "hold")
    q.setValue("close_to_tray", "maybe")
    bad = Settings(q).stt
    assert (bad.hotkey, bad.hotkey_mode, bad.close_to_tray) == ("f9", "toggle", True)


def test_background_options_default_on_and_round_trip(settings, tmp_path):
    fresh = Settings(QSettings(str(tmp_path / "fresh2.ini"), QSettings.Format.IniFormat)).stt
    assert fresh.background_replace and fresh.background_copy
    settings.stt.background_replace, settings.stt.background_copy = False, False
    settings.save()
    again = Settings(QSettings(str(tmp_path / "spette.ini"), QSettings.Format.IniFormat)).stt
    assert not again.background_replace and not again.background_copy


def test_microphone_is_found_by_name_when_the_numbers_shift():
    from spette.audio_recording import resolve_device_index
    assert resolve_device_index(["A", "B", "C"], 0, "C") == (2, "")
    index, note = resolve_device_index(["A"], 5, "Gone")
    assert index is None and "Gone" in note
    assert resolve_device_index(["A", "B"], 1) == (1, "")
    assert resolve_device_index(["A"], 7) == (None, "")
