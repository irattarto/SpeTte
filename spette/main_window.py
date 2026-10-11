"""The SpeTte window: record, clear, copy, and a text box."""

import threading
from typing import Optional

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from spette import resources
from spette.audio_recording import AudioRecordingThread, microphone_support_status
from spette.hotkeys import GlobalHotkey, MODE_PUSH, backend_status, combo_to_text, parse_combo
from spette.logger import get_logger
from spette.settings import Settings
from spette.version import APP_NAME
from spette.workers import stop_workers

RECORD_TEXT = "🎤 Record"
STOP_TEXT = "🔴 Stop"


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None):
        super().__init__()
        self.settings = settings or Settings()
        self.logger = get_logger('main_window')
        self._recording = False
        self._busy = False                      # transcribing or downloading
        self._recording_thread: Optional[AudioRecordingThread] = None
        self._transcription_worker = None
        self._cuda_worker = None
        self._gpu_download_failed = False
        self._quitting = False
        self._background_recording = False      # the current recording was started while SpeTte was in the background
        self._tray_hint_shown = False
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.idle_unload_ms = 5 * 60 * 1000     # free the graphics memory this long after the last use
        self._icon_idle = resources.icon("app_icon.png")
        self._icon_recording = resources.icon("icon_recording.png")
        self._tray_idle = resources.icon("tray_idle.png")
        self._tray_recording = resources.icon("tray_recording.png")
        self._icon_done = resources.icon("icon_done.png")
        self._tray_done = resources.icon("tray_done.png")
        self.blink_ms = 500                     # transcribing: the icon alternates red and blue
        self.done_flash_ms = 2500               # the text is ready (and copied): the icon is green for a moment
        self._blink_red = False
        self._done_tip = ""
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._on_blink)
        self._done_flash = QTimer(self)
        self._done_flash.setSingleShot(True)
        self._done_flash.timeout.connect(self._refresh_state)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._icon_idle)
        self.resize(640, 460)
        self._setup_ui()
        self._setup_tray()
        self.hotkey = GlobalHotkey(self)
        self.hotkey.triggered.connect(self._on_hotkey)
        saved = self.settings.geometry()
        if saved:
            self.restoreGeometry(saved)
        self.apply_settings()
        self._refresh_state()
        if not self.statusBar().currentMessage():
            self.statusBar().showMessage("Ready. Press Record and speak.")
        self._whisper_idle = QTimer(self)
        self._whisper_idle.setSingleShot(True)
        self._whisper_idle.timeout.connect(self._unload_whisper)
        self._prefetch_hardware()
        for delay in (3000, 10000, 30000):      # a tray that starts later than SpeTte (some desktops)
            QTimer.singleShot(delay, self._recheck_tray)

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        row = QHBoxLayout()

        self.record_button = QPushButton(RECORD_TEXT)
        self.record_button.setToolTip("Start recording; press again to stop and turn the speech into text")
        self.record_button.clicked.connect(self.toggle_recording)
        row.addWidget(self.record_button)

        self.clear_button = QPushButton("Clear text")
        self.clear_button.setToolTip("Remove all text (Ctrl+Z brings it back)")
        self.clear_button.clicked.connect(self.clear_text)
        row.addWidget(self.clear_button)

        self.copy_button = QPushButton("Copy to clipboard")
        self.copy_button.setToolTip("Copy the selected text, or all the text when nothing is selected (Ctrl+Shift+C)")
        self.copy_button.clicked.connect(self.copy_text)
        row.addWidget(self.copy_button)

        row.addStretch()
        self.settings_button = QPushButton("⚙ Settings")
        self.settings_button.clicked.connect(lambda: self.open_settings())
        row.addWidget(self.settings_button)
        layout.addLayout(row)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("The recognised text appears here. You can also type or edit it.")
        layout.addWidget(self.text_edit, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.copy_text)

    # -------------------------------------------------------- tray and state
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self._tray_idle, self)
        menu = QMenu(self)
        self.tray_show_action = QAction("Show SpeTte", self)
        self.tray_show_action.triggered.connect(self.toggle_window)
        self.tray_record_action = QAction("Start recording", self)
        self.tray_record_action.triggered.connect(self.toggle_recording)
        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(lambda: self.open_settings())
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        for action in (self.tray_show_action, self.tray_record_action, settings_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        menu.aboutToShow.connect(self._refresh_tray_menu)
        if self._tray_available:
            self.tray.show()

    def _recheck_tray(self):
        if not self._tray_available and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_available = True
            self.tray.show()

    def _prefetch_hardware(self):
        """Look for the graphics card in the background, so the first recording does not wait for it."""
        if self.settings.stt.provider != "whisper":
            return
        try:
            from spette import local_stt
            local_stt.prefetch_hardware()
        except Exception as e:
            self.logger.debug(f"Hardware prefetch skipped: {e}")

    def _unload_whisper(self):
        from spette import local_stt
        local_stt.clear_cache()                 # the model leaves the memory (and the graphics card) when idle

    def _refresh_tray_menu(self):
        self.tray_show_action.setText("Hide SpeTte" if self.isVisible() and not self.isMinimized() else "Show SpeTte")
        self.tray_record_action.setText("Stop recording" if self._recording else "Start recording")
        self.tray_record_action.setEnabled(self._recording or not self._busy)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_window()

    def _refresh_state(self):
        """Blue icons when idle, red while recording, red/blue blinking while transcribing, green when the text is
        ready."""
        if self._recording:
            state, tip = "recording", f"{APP_NAME} - recording..."
        elif self._busy:
            state, tip = "busy", f"{APP_NAME} - transcribing..."
        elif self._done_flash.isActive():
            state, tip = "done", f"{APP_NAME} - {self._done_tip}"
        else:
            state, tip = "idle", APP_NAME
        self.tray_state = state
        if state == "busy":
            if not self._blink.isActive():
                self._blink_red = True
                self._blink.start(self.blink_ms)
        else:
            self._blink.stop()
        self._show_icons()
        self.tray.setToolTip(tip)

    def _show_icons(self):
        """The tray and window icons for the current state."""
        state = self.tray_state
        if state == "recording" or (state == "busy" and self._blink_red):
            tray, window = self._tray_recording, self._icon_recording
        elif state == "done":
            tray, window = self._tray_done, self._icon_done
        else:
            tray, window = self._tray_idle, self._icon_idle
        self.tray.setIcon(tray)
        self.setWindowIcon(window)

    def _on_blink(self):
        self._blink_red = not self._blink_red
        self._show_icons()

    def _flash_done(self, copied: bool):
        """Green for a moment: the text is ready (and on the clipboard when it was copied)."""
        self._done_tip = "text ready, copied to the clipboard" if copied else "text ready"
        self._done_flash.start(self.done_flash_ms)
        self._refresh_state()

    def toggle_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.restore_window()

    def restore_window(self):
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def _hide_to_tray(self):
        self.hide()
        self._tray_hint()

    def _tray_hint(self):
        if not self._tray_hint_shown and self._tray_available:
            self._tray_hint_shown = True
            self.tray.showMessage(APP_NAME, "SpeTte keeps running in the tray. Click the icon to open it.",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)

    def quit_app(self):
        self._quitting = True
        self.close()

    def changeEvent(self, event):
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and self.settings.stt.minimize_to_tray and self._tray_available):
            QTimer.singleShot(0, self._hide_to_tray)
        super().changeEvent(event)

    # ---------------------------------------------------- global shortcut
    def apply_settings(self):
        """Start or stop the system-wide shortcut according to the settings."""
        s = self.settings.stt
        self.hotkey.stop()
        if not s.hotkey_enabled:
            self.record_button.setToolTip("Start recording; press again to stop and turn the speech into text")
            return
        combo = parse_combo(s.hotkey)
        ok, message = self.hotkey.start(combo, s.hotkey_mode)
        text = combo_to_text(combo)
        how = "hold to record" if s.hotkey_mode == MODE_PUSH else "press to start and stop"
        if ok:
            note = backend_status()[1]
            self.record_button.setToolTip(f"Start or stop recording. Shortcut anywhere: {text} ({how})")
            self.statusBar().showMessage(f"Ready. Shortcut anywhere: {text} ({how})." + (f" {note}" if note else ""))
        else:
            self.record_button.setToolTip("Start recording; press again to stop and turn the speech into text")
            self.statusBar().showMessage(f"The shortcut {text} is not active. {message}", 10000)

    def _on_hotkey(self, action: str):
        if action == "toggle":
            self.toggle_recording()
        elif action == "start":
            if not self._recording and not self._busy:
                self._start_recording()
        elif action == "stop":
            if self._recording:
                self._stop_recording()

    # -------------------------------------------------------------- text
    def clear_text(self):
        if not self.text_edit.toPlainText():
            self.statusBar().showMessage("Nothing to clear.", 3000)
            return
        cursor = self.text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()                # stays in the undo history, unlike clear()
        self.statusBar().showMessage("Text cleared (Ctrl+Z to bring it back).", 5000)

    def copy_text(self):
        """Copy the selected text, or all of it when nothing is selected."""
        text = self.text_to_copy()
        if not text.strip():
            self.statusBar().showMessage("Nothing to copy.", 3000)
            return
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {len(text)} characters to the clipboard.", 5000)

    def text_to_copy(self) -> str:
        """The selected text, or all the text when nothing is selected."""
        selected = self.text_edit.textCursor().selectedText().replace("\u2029", "\n").strip()
        return selected or self.text_edit.toPlainText()

    def is_in_background(self) -> bool:
        """Hidden in the tray, minimized, or simply not the window that has the focus."""
        return not self.isVisible() or self.isMinimized() or not self.isActiveWindow()

    def replace_text(self, text: str):
        """Replace all text with the recognised text (one undo step brings the old text back)."""
        cursor = self.text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text + "\n")
        self.text_edit.setTextCursor(cursor)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def append_text(self, text: str):
        """Add recognised text at the end, on a new line when there is text already."""
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        existing = self.text_edit.toPlainText()
        if existing and not existing.endswith("\n"):
            cursor.insertText("\n")
        cursor.insertText(text + "\n")
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()

    # --------------------------------------------------------- settings
    def open_settings(self, tab: Optional[int] = None):
        if self._recording or self._busy:
            self.statusBar().showMessage("Finish the current recording first.", 3000)
            return
        from spette.settings_dialog import SettingsDialog
        self.restore_window()
        self.hotkey.stop()                       # no recording while the keys are being chosen
        dialog = SettingsDialog(self.settings, self)
        if tab is not None:
            dialog.tabs.setCurrentIndex(tab)
        dialog.exec()
        self.apply_settings()

    # -------------------------------------------------------- recording
    def toggle_recording(self):
        if self._busy:
            return
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _set_idle_buttons(self):
        self.record_button.setText(RECORD_TEXT)
        self.record_button.setEnabled(True)

    def _start_recording(self):
        available, reason = microphone_support_status()
        if not available:
            self.statusBar().showMessage(f"❌ {reason}", 8000)
            return
        if self._recording_thread is not None and self._recording_thread.isRunning():
            self.statusBar().showMessage("The previous recording is still closing, try again in a moment.", 4000)
            return
        stt = self.settings.stt
        self._background_recording = self.is_in_background()
        self._recording = True
        self.record_button.setText(STOP_TEXT)
        self._refresh_state()
        limit = stt.recording_limit()
        self.statusBar().showMessage(f"🎤 Recording... press Stop when done (stops by itself after {limit} s)")
        self._recording_thread = AudioRecordingThread(device_index=stt.device_index, device_name=stt.device_name)
        self._recording_thread.recording_finished.connect(self._on_recording_finished)
        self._recording_thread.recording_error.connect(self._on_recording_error)
        self._recording_thread.start()
        self._timeout.start(limit * 1000)
        self._preload_local_model()

    def _stop_recording(self):
        if not self._recording:
            return
        self._timeout.stop()
        self._recording = False
        if self._recording_thread and self._recording_thread.isRunning():
            self._recording_thread.stop_recording()
        self.record_button.setEnabled(False)
        self.record_button.setText("⏳ Finishing...")
        self._refresh_state()

    def _on_timeout(self):
        if self._recording:
            self._stop_recording()
            self.statusBar().showMessage("Longest recording time reached, transcribing...", 3000)

    def _preload_local_model(self):
        """Load the local model while the user is still speaking (in the background: it can take seconds)."""
        stt = self.settings.stt
        if stt.provider != "whisper":
            return
        threading.Thread(target=self._preload_worker, args=(stt.whisper_model, stt.whisper_device,
                                                            stt.gpu_prompt_declined), daemon=True,
                         name="stt-preload").start()

    def _preload_worker(self, model: str, device: str, declined: bool):
        try:
            from spette import local_stt
            if device != "cpu" and not declined and local_stt.gpu_libs_missing():
                return   # the GPU libraries are offered first; do not load a CPU model meanwhile
            plan = local_stt.resolve_plan(model, device)
            local_stt.preload(plan)
        except Exception as e:
            self.logger.debug(f"Model preload skipped: {e}")

    def _on_recording_finished(self, audio_data):
        self._timeout.stop()
        self._recording = False
        self._refresh_state()
        if not audio_data or len(audio_data.frame_data) == 0:
            self._set_idle_buttons()
            self.statusBar().showMessage("❌ No audio was captured. Check the microphone in Settings.", 6000)
            return
        self._start_transcription(audio_data)

    def _on_recording_error(self, message: str):
        self._timeout.stop()
        self._recording = False
        self._set_idle_buttons()
        self._refresh_state()
        self.logger.error(f"Recording error: {message}")
        self.statusBar().showMessage(f"❌ Recording failed: {message}", 8000)

    # ---------------------------------------------------- transcription
    def _set_busy(self, busy: bool):
        self._busy = busy
        self.record_button.setEnabled(not busy)
        self.record_button.setText("⏳ Working..." if busy else RECORD_TEXT)
        self._refresh_state()

    def _start_transcription(self, audio_data):
        from spette.workers import TranscriptionWorker
        stt = self.settings.stt
        if self._offer_gpu_libraries(audio_data):
            return                                  # the transcription starts after the download
        worker = TranscriptionWorker(audio_data, stt.provider, stt.language, stt.whisper_model, stt.whisper_device)
        worker.status.connect(self.statusBar().showMessage)
        worker.result_ready.connect(self._on_transcription_ready)
        worker.error.connect(lambda msg: self.statusBar().showMessage(f"❌ {msg}", 10000))
        worker.finished.connect(lambda w=worker: self._on_transcription_finished(w))
        self._transcription_worker = worker
        self._set_busy(True)
        worker.start()

    def _on_transcription_ready(self, text: str):
        if not text:
            self.statusBar().showMessage("❌ Could not understand the audio.", 6000)
            return
        stt = self.settings.stt
        background = self._background_recording
        if background and stt.background_replace:
            self.replace_text(text)
        else:
            self.append_text(text)
        copied = background and stt.background_copy
        if copied:
            QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage("✅ Done." + (" Copied to the clipboard." if copied else ""), 5000)
        self._flash_done(bool(copied))             # green for a moment, whether the window is in front or not
        if not self.isVisible() and self._tray_available:
            note = "Copied to the clipboard." if copied else "Open SpeTte to copy it."
            self.tray.showMessage(APP_NAME, f"Text added ({len(text)} characters). {note}",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)

    def _on_transcription_finished(self, worker):
        if self._transcription_worker is worker:
            self._transcription_worker = None
            self._set_busy(False)
            self._whisper_idle.start(self.idle_unload_ms)
        worker.deleteLater()

    # ------------------------------------------------------ GPU libraries
    def _offer_gpu_libraries(self, audio_data) -> bool:
        """Offer (once) the one-time NVIDIA library download. True when a download was started."""
        stt = self.settings.stt
        if (stt.provider != "whisper" or stt.whisper_device == "cpu" or stt.gpu_prompt_declined
                or self._gpu_download_failed):
            return False
        try:
            from spette import local_stt
            hardware = local_stt.cached_hardware()      # never wait for the detection here
            if hardware is None or not hardware.libs_missing:
                return False
            gpu = hardware.gpu_name
        except Exception as e:
            self.logger.debug(f"GPU library check skipped: {e}")
            return False
        answer = QMessageBox.question(
            self, "Use the graphics card?",
            f"Your {gpu} can transcribe much faster than the processor, but it needs NVIDIA's CUDA libraries "
            "(about 1 GB, downloaded once from PyPI, checksum-verified).\n\nDownload them now?\n\n"
            "Choosing No keeps using the processor and will not ask again.")
        if answer != QMessageBox.StandardButton.Yes:
            stt.gpu_prompt_declined = True
            self.settings.save()
            return False
        from spette.workers import CudaDownloadWorker
        worker = CudaDownloadWorker(self)
        worker.status.connect(self.statusBar().showMessage)
        worker.done.connect(lambda: self._after_gpu_download(audio_data, None))
        worker.error.connect(lambda msg: self._after_gpu_download(audio_data, msg))
        worker.finished.connect(worker.deleteLater)
        self._cuda_worker = worker
        self._set_busy(True)
        worker.start()
        return True

    def _after_gpu_download(self, audio_data, error: Optional[str]):
        if error:
            self.statusBar().showMessage(f"❌ {error} Transcribing on the processor instead.", 8000)
            self._gpu_download_failed = True
        self._set_busy(False)
        self._start_transcription(audio_data)

    # ------------------------------------------------------------ closing
    def closeEvent(self, event):
        if not self._quitting and self.settings.stt.close_to_tray and self._tray_available:
            event.ignore()                      # keep running in the tray
            self._hide_to_tray()
            return
        self.hotkey.stop()
        self.tray.hide()
        if self._recording:
            self._timeout.stop()
            self._recording = False
            if self._recording_thread:
                self._recording_thread.stop_recording()
        stop_workers([self._recording_thread, self._transcription_worker, self._cuda_worker], 2000)
        self.settings.set_geometry(self.saveGeometry())
        super().closeEvent(event)
        QApplication.quit()
