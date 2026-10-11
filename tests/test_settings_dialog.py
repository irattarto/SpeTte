from spette.settings_dialog import SettingsDialog


def test_dialog_shows_and_saves_choices(app, settings):
    dialog = SettingsDialog(settings, microphones=["Built-in", "USB mic"], detect_hardware=False)
    assert dialog.microphone_combo.count() == 3                    # default + two devices
    assert dialog.provider_combo.currentData() == "whisper"
    dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("google"))
    assert dialog.whisper_box.isHidden()                           # model/device only matter for local Whisper
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en-GB"))
    dialog.microphone_combo.setCurrentIndex(dialog.microphone_combo.findData(1))
    dialog.max_spin.setValue(45)
    dialog.model_combo.setCurrentIndex(dialog.model_combo.findData("medium"))
    dialog.device_combo.setCurrentIndex(dialog.device_combo.findData("cpu"))
    dialog.accept()
    s = settings.stt
    assert (s.provider, s.language, s.device_index, s.max_seconds, s.whisper_model, s.whisper_device) == \
           ("google", "en-GB", 1, 45, "medium", "cpu")


def test_cancel_changes_nothing(app, settings):
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False)
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("de-DE"))
    dialog.reject()
    assert settings.stt.language == "hu-HU"


def test_missing_microphone_support_disables_the_list(app, settings, monkeypatch):
    import spette.settings_dialog as sd
    monkeypatch.setattr(sd, "microphone_names", lambda: None)
    dialog = SettingsDialog(settings, detect_hardware=False)
    assert not dialog.microphone_combo.isEnabled()


def test_tray_and_shortcut_options_are_saved(app, settings):
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=True,
                            hotkey_status=(True, ""))
    assert dialog.minimize_check.isChecked() and dialog.close_check.isChecked()      # both on by default
    dialog.minimize_check.setChecked(False)
    dialog.close_check.setChecked(False)
    dialog.hotkey_check.setChecked(True)
    dialog.hotkey_edit.set_combo({"ctrl", "shift"})
    dialog.hotkey_mode_combo.setCurrentIndex(dialog.hotkey_mode_combo.findData("push"))
    dialog.accept()
    s = settings.stt
    assert (s.minimize_to_tray, s.close_to_tray, s.hotkey_enabled) == (False, False, True)
    assert (s.hotkey, s.hotkey_mode) == ("ctrl+shift", "push")


def test_shortcut_controls_follow_the_checkbox_and_missing_tray_is_explained(app, settings):
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=False,
                            hotkey_status=(False, "System-wide shortcuts are not available."))
    assert not dialog.minimize_check.isEnabled() and not dialog.close_check.isEnabled()
    assert not dialog.tray_note.isHidden()
    dialog.hotkey_check.setChecked(False)
    assert not dialog.hotkey_edit.isEnabled() and not dialog.hotkey_mode_combo.isEnabled()
    dialog.hotkey_check.setChecked(True)
    assert dialog.hotkey_edit.isEnabled() and dialog.hotkey_mode_combo.isEnabled()
    assert "not available" in dialog.hotkey_note.text()


def test_background_options_are_saved(app, settings):
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=True,
                            hotkey_status=(True, ""))
    assert dialog.replace_check.isChecked() and dialog.copy_check.isChecked()       # on by default
    dialog.replace_check.setChecked(False)
    dialog.accept()
    assert settings.stt.background_replace is False and settings.stt.background_copy is True


def test_there_are_only_the_speech_to_text_tabs(app, settings):
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=True,
                            hotkey_status=(True, ""))
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Recognition", "Window and shortcut"]


def test_shortcut_hints_warn_about_push_to_talk_with_modifiers_only(app, settings):
    from spette.hotkeys import MODE_PUSH, MODE_TOGGLE
    from spette.settings_dialog import SettingsDialog
    dialog = SettingsDialog(settings, microphones=[], detect_hardware=False, tray_available=True,
                            hotkey_status=(True, ""))
    assert "not blocked" in dialog.hotkey_hint.text() and "modifier" not in dialog.hotkey_hint.text()
    dialog.hotkey_edit.set_combo(frozenset({"ctrl", "alt"}))
    dialog.hotkey_mode_combo.setCurrentIndex(dialog.hotkey_mode_combo.findData(MODE_PUSH))
    assert "modifier" in dialog.hotkey_hint.text()
    dialog.hotkey_mode_combo.setCurrentIndex(dialog.hotkey_mode_combo.findData(MODE_TOGGLE))
    assert "modifier" not in dialog.hotkey_hint.text()
