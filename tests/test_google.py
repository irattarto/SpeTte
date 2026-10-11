import pytest

from spette import google_stt, keystore

KEY = "AIzaSyExampleExampleExampleExample1234"


def test_key_check_refuses_odd_text_without_repeating_it():
    assert keystore.check(KEY) is None
    for bad in ("", "short", "has a space in the middle of it", "x" * 300, "ünïcode" * 5):
        problem = keystore.check(bad)
        assert problem and bad.strip() not in problem or not bad.strip()


def test_key_is_kept_in_the_keyring_only(memory_keyring, tmp_path):
    assert keystore.available() == (True, "")
    assert keystore.get() == "" and not keystore.has_key()
    assert keystore.set_key(f"  {KEY}  ") is None
    assert keystore.get() == KEY and memory_keyring.items == {("SpeTte", "google-api-key"): KEY}
    assert keystore.set_key("bad key") is not None and keystore.get() == KEY      # a refused key changes nothing
    keystore.delete()
    assert keystore.get() == "" and memory_keyring.items == {}
    keystore.delete()                                                             # nothing stored: no error


def test_without_a_keyring_nothing_is_stored(monkeypatch):
    import keyring
    from keyring.backends import fail
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    usable, why = keystore.available()
    assert not usable and "keyring" in why
    assert keystore.set_key(KEY) == why and keystore.get() == ""


def test_a_broken_keyring_never_raises(monkeypatch, memory_keyring):
    def boom(*args):
        raise RuntimeError("locked")
    monkeypatch.setattr(memory_keyring, "get_password", boom)
    monkeypatch.setattr(memory_keyring, "set_password", boom)
    assert keystore.get() == ""
    assert "refused" in keystore.set_key(KEY)


@pytest.mark.parametrize("text,own,expect", [
    ("recognition connection failed: [Errno 11001] getaddrinfo failed", False, "could not be reached"),
    ("recognition connection failed: timed out", True, "could not be reached"),
    ("recognition request failed: Too Many Requests", False, "shared free key"),
    ("recognition request failed: Too Many Requests", True, "with your key"),
    ("recognition request failed: Forbidden", False, "shared free key"),
    ("recognition request failed: Forbidden", True, "refused the key you entered"),
    ("something odd", False, "failed (something odd)"),
])
def test_google_failures_are_explained(text, own, expect):
    message = google_stt.explain_request_error(RuntimeError(text), KEY if own else "")
    assert expect in message and "Whisper" in message


def test_the_key_never_appears_in_an_explanation():
    message = google_stt.explain_request_error(RuntimeError(f"failed for key={KEY}"), KEY)
    assert KEY not in message


def test_the_worker_uses_the_stored_key_and_explains_failures(app, monkeypatch):
    import speech_recognition as sr
    from spette.workers import TranscriptionWorker
    seen = {}

    def fake(audio, language, key=None):
        seen["key"] = key
        raise sr.RequestError("recognition request failed: Too Many Requests")
    monkeypatch.setattr(google_stt, "recognize", fake)
    keystore.set_key(KEY)
    worker, errors, statuses = TranscriptionWorker(object(), "google", "en-US"), [], []
    worker.error.connect(errors.append)
    worker.status.connect(statuses.append)
    worker.run()
    assert seen["key"] == KEY and "your own key" in statuses[0]
    assert "with your key" in errors[0] and KEY not in errors[0]
    keystore.delete()
    worker.run()
    assert seen["key"] == "" and "shared free key" in statuses[-1]


def test_unclear_audio_is_not_blamed_on_the_key(app, monkeypatch):
    import speech_recognition as sr
    from spette.workers import TranscriptionWorker

    def fake(audio, language, key=None):
        raise sr.UnknownValueError()
    monkeypatch.setattr(google_stt, "recognize", fake)
    worker, errors = TranscriptionWorker(object(), "google", "en-US"), []
    worker.error.connect(errors.append)
    worker.run()
    assert "could not understand" in errors[0] and "key are fine" in errors[0]


def make_dialog(settings):
    from spette.settings_dialog import SettingsDialog
    return SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=True,
                          hotkey_status=(True, ""))


def test_dialog_shows_the_warning_only_for_google_and_stores_the_key(app, settings, memory_keyring):
    dialog = make_dialog(settings)
    assert dialog.google_box.isHidden() and "Whisper" in google_stt.SHARED_KEY_WARNING
    dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("google"))
    assert not dialog.google_box.isHidden()
    assert "shared free key" in dialog.google_key_status.text() and not dialog.google_key_remove.isEnabled()
    dialog.google_key_edit.setText(KEY)
    dialog.accept()
    assert keystore.get() == KEY
    assert KEY not in "".join(str(v) for v in settings._q.allKeys()) and \
        all(KEY != str(settings._q.value(k)) for k in settings._q.allKeys())       # not in the settings file


def test_dialog_keeps_open_when_the_key_is_refused_and_can_remove_a_key(app, settings, memory_keyring):
    dialog = make_dialog(settings)
    dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("google"))
    dialog.google_key_edit.setText("bad key")
    dialog.accept()
    assert dialog.result() == 0 and "no spaces" in dialog.google_key_status.text() and keystore.get() == ""
    keystore.set_key(KEY)
    dialog._refresh_google_key()
    assert "stored" in dialog.google_key_status.text() and dialog.google_key_remove.isEnabled()
    dialog._remove_google_key()
    assert keystore.get() == "" and not dialog.google_key_remove.isEnabled()


def test_dialog_disables_the_key_field_without_a_keyring(app, settings, monkeypatch):
    import keyring
    from keyring.backends import fail
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    dialog = make_dialog(settings)
    assert not dialog.google_key_edit.isEnabled() and "keyring" in dialog.google_key_status.text()
