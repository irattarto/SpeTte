from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication

from spette import main_window
from spette.main_window import MainWindow


class FakeAudio:
    frame_data = b"\0" * 100


def make(app, settings):
    return MainWindow(settings)


def test_clear_is_undoable_and_copy_uses_the_clipboard(app, settings):
    window = make(app, settings)
    window.text_edit.setPlainText("hello there")
    window.copy_button.click()
    assert QGuiApplication.clipboard().text() == "hello there"
    assert "Copied 11" in window.statusBar().currentMessage()

    window.clear_button.click()
    assert window.text_edit.toPlainText() == ""
    window.text_edit.undo()
    assert window.text_edit.toPlainText() == "hello there"

    window.text_edit.clear()
    window.copy_button.click()
    assert "Nothing to copy" in window.statusBar().currentMessage()    # the clipboard keeps the old text
    window.clear_button.click()
    assert "Nothing to clear" in window.statusBar().currentMessage()


def test_recognised_text_is_added_not_replaced(app, settings):
    window = make(app, settings)
    window.append_text("first")
    window.append_text("second")
    assert window.text_edit.toPlainText() == "first\nsecond\n"
    window.text_edit.setPlainText("typed")
    window.append_text("spoken")
    assert window.text_edit.toPlainText() == "typed\nspoken\n"


def test_empty_transcription_reports_and_changes_nothing(app, settings):
    window = make(app, settings)
    window.append_text("keep")
    window._on_transcription_ready("")
    assert window.text_edit.toPlainText() == "keep\n"
    assert "Could not understand" in window.statusBar().currentMessage()


def test_record_button_cycle(app, settings, monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, device_index=None, device_name=""):
            from PyQt6.QtCore import QObject, pyqtSignal

            class Signals(QObject):
                recording_finished = pyqtSignal(object)
                recording_error = pyqtSignal(str)
            self._signals = Signals()
            self.recording_finished = self._signals.recording_finished
            self.recording_error = self._signals.recording_error
            self.stopped = False
            started.append(self)

        def start(self): pass
        def isRunning(self): return not self.stopped
        def stop_recording(self): self.stopped = True

    monkeypatch.setattr(main_window, "AudioRecordingThread", FakeThread)
    monkeypatch.setattr(main_window, "microphone_support_status", lambda: (True, ""))
    window = make(app, settings)
    monkeypatch.setattr(window, "_preload_local_model", lambda: None)
    transcribed = []
    monkeypatch.setattr(window, "_start_transcription", transcribed.append)

    window.record_button.click()
    assert window._recording and window.record_button.text() == main_window.STOP_TEXT
    window.record_button.click()                                   # Stop
    assert started[0].stopped and not window._recording and not window.record_button.isEnabled()
    started[0].recording_finished.emit(FakeAudio())
    assert len(transcribed) == 1                                   # the audio goes on to transcription

    window._set_idle_buttons()
    window.record_button.click()
    started[1].recording_error.emit("No microphone found.")
    assert window.record_button.isEnabled() and window.record_button.text() == main_window.RECORD_TEXT
    assert "No microphone" in window.statusBar().currentMessage()


def test_missing_microphone_support_is_explained(app, settings, monkeypatch):
    monkeypatch.setattr(main_window, "microphone_support_status", lambda: (False, "PyAudio is missing"))
    window = make(app, settings)
    window.record_button.click()
    assert not window._recording and "PyAudio is missing" in window.statusBar().currentMessage()


def test_empty_recording_is_reported(app, settings):
    window = make(app, settings)
    window._recording = True
    window._on_recording_finished(None)
    assert not window._recording and window.record_button.isEnabled()
    assert "No audio" in window.statusBar().currentMessage()


# ------------------------------------------------------------ tray and shortcut
def tray_window(app, settings, monkeypatch, available=True):
    monkeypatch.setattr(main_window.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: available))
    return MainWindow(settings)


def test_tray_icon_follows_the_recording_state(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    assert window.tray_state == "idle" and window.tray.toolTip() == "SpeTte"
    window._recording = True
    window._refresh_state()
    assert window.tray_state == "recording" and "recording" in window.tray.toolTip()
    window._recording = False
    window._set_busy(True)
    assert window.tray_state == "busy" and "transcribing" in window.tray.toolTip()
    window._set_busy(False)
    assert window.tray_state == "idle"


def test_icons_are_bundled_and_the_recording_one_differs(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    for icon in (window._icon_idle, window._icon_recording, window._tray_idle, window._tray_recording):
        assert not icon.isNull()
    assert window._tray_idle.pixmap(32, 32).toImage() != window._tray_recording.pixmap(32, 32).toImage()


def test_closing_hides_to_the_tray_when_enabled(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    window.show()
    window.close()
    assert not window.isVisible() and not window._quitting          # still running
    window.toggle_window()
    assert window.isVisible()
    window.toggle_window()
    assert not window.isVisible()
    window.quit_app()                                               # the tray menu's Quit really closes
    assert window._quitting


def test_closing_really_closes_when_the_option_is_off_or_there_is_no_tray(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    settings.stt.close_to_tray = False
    window.show()
    window.close()
    assert not window.isVisible() and not window.hotkey.running

    window = tray_window(app, settings, monkeypatch, available=False)
    settings.stt.close_to_tray = True
    window.show()
    window.close()
    assert not window.isVisible()


def test_minimizing_hides_to_the_tray_only_when_enabled(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    window.show()
    window.setWindowState(Qt.WindowState.WindowMinimized)
    app.processEvents()
    app.processEvents()
    assert not window.isVisible()
    window.restore_window()
    assert window.isVisible() and not window.isMinimized()

    settings.stt.minimize_to_tray = False
    window.setWindowState(Qt.WindowState.WindowMinimized)
    app.processEvents()
    app.processEvents()
    assert window.isMinimized() or window.isVisible()               # normal minimizing, not hidden
    window.deleteLater()


def test_shortcut_actions_drive_the_recording(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    calls = []
    monkeypatch.setattr(window, "toggle_recording", lambda: calls.append("toggle"))
    monkeypatch.setattr(window, "_start_recording", lambda: calls.append("start"))
    monkeypatch.setattr(window, "_stop_recording", lambda: calls.append("stop"))
    window._on_hotkey("toggle")
    window._on_hotkey("start")
    window._on_hotkey("stop")                                      # not recording: ignored
    window._recording = True
    window._on_hotkey("start")                                     # already recording: ignored
    window._on_hotkey("stop")
    window._recording = False
    window._busy = True
    window._on_hotkey("start")                                     # busy transcribing: ignored
    assert calls == ["toggle", "start", "stop"]


def test_apply_settings_starts_and_stops_the_global_shortcut(app, settings, monkeypatch):
    started = []

    class FakeHotkey:
        running = False
        def start(self, combo, mode):
            started.append((sorted(combo), mode)); return True, ""
        def stop(self): started.append("stop")

    window = tray_window(app, settings, monkeypatch)
    window.hotkey = FakeHotkey()
    settings.stt.hotkey_enabled, settings.stt.hotkey, settings.stt.hotkey_mode = True, "ctrl+shift", "push"
    window.apply_settings()
    assert started == ["stop", (["ctrl", "shift"], "push")]
    assert "Ctrl+Shift" in window.record_button.toolTip() and "hold" in window.record_button.toolTip()
    settings.stt.hotkey_enabled = False
    window.apply_settings()
    assert started[-1] == "stop"


def test_unavailable_shortcut_is_explained_not_fatal(app, settings, monkeypatch):
    class BrokenHotkey:
        def start(self, combo, mode): return False, "No X11 display."
        def stop(self): pass

    window = tray_window(app, settings, monkeypatch)
    window.hotkey = BrokenHotkey()
    settings.stt.hotkey_enabled = True
    window.apply_settings()
    assert "not active" in window.statusBar().currentMessage() and "No X11 display" in window.statusBar().currentMessage()


# ------------------------------------------------------------ background behaviour
def test_background_recording_replaces_the_text_and_copies_the_result(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    QGuiApplication.clipboard().setText("old clipboard")
    window.append_text("old text")
    window._background_recording = True
    window._on_transcription_ready("new words")
    assert window.text_edit.toPlainText() == "new words\n"
    assert QGuiApplication.clipboard().text() == "new words"           # only the result, not the whole box
    assert "Copied to the clipboard" in window.statusBar().currentMessage()
    window.text_edit.undo()
    assert window.text_edit.toPlainText() == "old text\n"              # one undo step brings the old text back


def test_foreground_recording_adds_the_text_and_leaves_the_clipboard_alone(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    QGuiApplication.clipboard().setText("untouched")
    window.append_text("first")
    window._background_recording = False
    window._on_transcription_ready("second")
    assert window.text_edit.toPlainText() == "first\nsecond\n"
    assert QGuiApplication.clipboard().text() == "untouched"


def test_background_options_can_be_turned_off_separately(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    window._background_recording = True
    QGuiApplication.clipboard().setText("clip")
    settings.stt.background_replace = False                            # copy on, replace off
    window.append_text("keep")
    window._on_transcription_ready("one")
    assert window.text_edit.toPlainText() == "keep\none\n" and QGuiApplication.clipboard().text() == "one"
    settings.stt.background_replace, settings.stt.background_copy = True, False   # replace on, copy off
    window._on_transcription_ready("two")
    assert window.text_edit.toPlainText() == "two\n" and QGuiApplication.clipboard().text() == "one"


def test_an_empty_result_changes_neither_text_nor_clipboard(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    window.append_text("keep")
    QGuiApplication.clipboard().setText("clip")
    window._background_recording = True
    window._on_transcription_ready("")
    assert window.text_edit.toPlainText() == "keep\n" and QGuiApplication.clipboard().text() == "clip"


def test_background_is_decided_when_the_recording_starts(app, settings, monkeypatch):
    window = tray_window(app, settings, monkeypatch)
    assert window.is_in_background()                                   # never shown: hidden counts as background
    monkeypatch.setattr(main_window, "microphone_support_status", lambda: (True, ""))

    class FakeThread:
        def __init__(self, device_index=None, device_name=""):
            from PyQt6.QtCore import QObject, pyqtSignal

            class Signals(QObject):
                recording_finished = pyqtSignal(object)
                recording_error = pyqtSignal(str)
            self._signals = Signals()
            self.recording_finished = self._signals.recording_finished
            self.recording_error = self._signals.recording_error
        def start(self): pass
        def isRunning(self): return False
        def stop_recording(self): pass

    monkeypatch.setattr(main_window, "AudioRecordingThread", FakeThread)
    monkeypatch.setattr(window, "_preload_local_model", lambda: None)
    monkeypatch.setattr(window, "is_in_background", lambda: True)
    window._start_recording()
    assert window._background_recording is True
    window._recording = False
    monkeypatch.setattr(window, "is_in_background", lambda: False)
    window._start_recording()
    assert window._background_recording is False


def test_copy_button_copies_the_selection_or_everything(app, settings):
    window = make(app, settings)
    window.text_edit.setPlainText("one two three")
    window.copy_text()
    assert QGuiApplication.clipboard().text() == "one two three"
    cursor = window.text_edit.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(7, cursor.MoveMode.KeepAnchor)
    window.text_edit.setTextCursor(cursor)
    window.copy_text()
    assert QGuiApplication.clipboard().text() == "two"


def test_shortcut_is_stopped_while_settings_are_open(app, settings, monkeypatch):
    window = make(app, settings)
    stopped, applied = [], []
    monkeypatch.setattr(window.hotkey, "stop", lambda: stopped.append(True))
    monkeypatch.setattr(window, "apply_settings", lambda: applied.append(True))

    class Dialog:
        def __init__(self, *a, **k):
            from PyQt6.QtWidgets import QTabWidget
            self.tabs = QTabWidget()

        def exec(self):
            assert stopped                       # already stopped when the dialog is shown
            return 1

    import spette.settings_dialog as sd
    monkeypatch.setattr(sd, "SettingsDialog", Dialog)
    window.open_settings()
    assert stopped and applied                   # and started again by apply_settings afterwards


def test_tray_appearing_later_is_picked_up(app, settings, monkeypatch):
    window = make(app, settings)
    window._tray_available = False
    monkeypatch.setattr(main_window.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    shown = []
    monkeypatch.setattr(window.tray, "show", lambda: shown.append(True))
    window._recheck_tray()
    assert window._tray_available and shown


def test_whisper_unloads_when_idle(app, settings, monkeypatch):
    from spette import local_stt
    cleared = []
    monkeypatch.setattr(local_stt, "clear_cache", lambda: cleared.append(True))
    window = make(app, settings)
    window._unload_whisper()
    assert len(cleared) == 1
    worker = object.__new__(type("W", (), {"deleteLater": lambda self: None}))
    window._transcription_worker = worker
    window._on_transcription_finished(worker)
    assert window._whisper_idle.isActive()


def test_model_memory_estimates():
    from spette import local_stt
    assert local_stt.model_vram_mb("small") == 2000 and local_stt.model_vram_mb("large") == 6000


def test_icon_blinks_while_transcribing_and_flashes_green_when_the_text_is_ready(app, settings):
    window = make(app, settings)
    window.blink_ms = 20
    window.done_flash_ms = 60
    shown = []
    window._show_icons = lambda real=window._show_icons: (shown.append((window.tray_state, window._blink_red)), real())

    window._set_busy(True)
    assert window.tray_state == "busy" and window._blink.isActive()
    from tests.helpers import wait_until
    wait_until(app, lambda: {red for state, red in shown if state == "busy"} == {True, False}, timeout=2)
    assert {red for state, red in shown if state == "busy"} == {True, False}      # red and blue take turns

    window._on_transcription_ready("hello")                  # the text arrives, the worker is not finished yet
    window._set_busy(False)
    assert window.tray_state == "done" and "text ready" in window.tray.toolTip()
    assert not window._blink.isActive()                       # the blinking has stopped
    wait_until(app, lambda: window.tray_state == "idle", timeout=2)
    assert window.tray_state == "idle" and window.tray.toolTip() == "SpeTte"


def test_green_flash_mentions_the_clipboard_only_when_it_was_copied(app, settings):
    window = make(app, settings)
    window._background_recording = True                      # copied automatically (background option is on)
    window._set_busy(True)
    window._on_transcription_ready("hello")
    window._set_busy(False)
    assert "copied to the clipboard" in window.tray.toolTip()
    window._done_flash.stop()
    window._refresh_state()
    window._background_recording = False
    window._set_busy(True)
    window._on_transcription_ready("again")
    window._set_busy(False)
    assert window.tray_state == "done" and "clipboard" not in window.tray.toolTip()   # window in front: not copied


def test_no_green_flash_when_nothing_was_understood_and_recording_wins(app, settings):
    window = make(app, settings)
    window._set_busy(True)
    window._on_transcription_ready("")
    window._set_busy(False)
    assert window.tray_state == "idle"
    window._set_busy(True)
    window._on_transcription_ready("text")
    window._set_busy(False)
    window._recording = True                                  # a new recording starts during the flash
    window._refresh_state()
    assert window.tray_state == "recording"
    window._recording = False
    window._done_flash.stop()
    window._refresh_state()
