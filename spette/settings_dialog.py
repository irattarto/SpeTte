"""The settings: voice recognition, window and shortcut."""

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from spette import cuda_libs, google_stt, keystore, local_stt
from spette.hotkey_edit import HotkeyEdit
from spette.hotkeys import MODE_PUSH, MODE_TOGGLE, MODIFIERS, backend_status, combo_to_setting, parse_combo
from spette.logger import get_logger
from spette.settings import (
    DEVICES, LANGUAGES, MAX_SECONDS, MIN_SECONDS, GOOGLE_MAX_SECONDS, Settings,
)
from spette.workers import CudaDownloadWorker, HardwareWorker, ModelDownloadWorker, stop_workers

DEVICE_LABELS = {
    "auto": "Automatic (GPU if usable, otherwise CPU)",
    "cuda": "NVIDIA GPU (faster)",
    "cpu": "CPU (works everywhere, slower)",
}
PROVIDER_LABELS = {
    "whisper": "Local, offline (Whisper)",
    "google": "Google cloud (sends the audio to Google)",
}


def microphone_names() -> Optional[List[str]]:
    """Names of the input devices, or None when microphone support is missing."""
    try:
        import speech_recognition as sr
        return list(sr.Microphone.list_microphone_names())
    except Exception as e:
        get_logger('settings_dialog').warning(f"Could not list microphones: {e}")
        return None


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, microphones: Optional[List[str]] = None,
                 detect_hardware: bool = True, tray_available: Optional[bool] = None,
                 hotkey_status: Optional[Tuple[bool, str]] = None):
        super().__init__(parent)
        self.settings = settings
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable() if tray_available is None else tray_available
        self._hotkey_status = backend_status() if hotkey_status is None else hotkey_status
        self.logger = get_logger('settings_dialog')
        self._workers: List = []
        self.setWindowTitle("SpeTte settings")
        self.setModal(True)
        self.setMinimumSize(560, 380)                         # every tab scrolls, so a small screen can still reach OK
        width, height = 600, 700
        screen = QGuiApplication.primaryScreen()
        if screen is not None:                                # never taller than the screen (the title bar and the
            available = screen.availableGeometry()            # taskbar take some of it)
            width, height = min(width, int(available.width() * 0.95)), min(height, int(available.height() * 0.88))
        self.resize(width, height)
        self._microphones = microphone_names() if microphones is None else microphones
        self._setup_ui()
        self._load()
        if detect_hardware:
            self._start_hardware_check()
        else:
            self.hardware_label.setText("")

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        """A tab page that scrolls when it is taller than the window (the buttons below the tabs stay reachable)."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        recognition_page, window_page = QWidget(), QWidget()
        for page, title in ((recognition_page, "Recognition"), (window_page, "Window and shortcut")):
            self.tabs.addTab(self._scrolling(page), title)
        layout = QVBoxLayout(recognition_page)
        window_layout = QVBoxLayout(window_page)
        form = QFormLayout()
        layout.addLayout(form)

        self.provider_combo = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.provider_combo.addItem(label, key)
        self.provider_combo.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Recognition:", self.provider_combo)

        self.language_combo = QComboBox()
        for code, name in LANGUAGES:
            self.language_combo.addItem(f"{name} ({code})", code)
        form.addRow("Language:", self.language_combo)

        self.microphone_combo = QComboBox()
        self.microphone_combo.addItem("Default system microphone", None)
        if self._microphones is None:
            self.microphone_combo.addItem("Microphone support is not available", None)
            self.microphone_combo.setEnabled(False)
        else:
            for index, name in enumerate(self._microphones):
                self.microphone_combo.addItem(f"{index}: {name}", index)
        self._mic_names = list(self._microphones or [])
        form.addRow("Microphone:", self.microphone_combo)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(MIN_SECONDS, MAX_SECONDS)
        self.max_spin.setSuffix(" s")
        self.max_spin.setToolTip(f"A recording stops by itself after this long. Google accepts at most "
                                 f"{GOOGLE_MAX_SECONDS} s, so it stops there even if this is higher.")
        form.addRow("Longest recording:", self.max_spin)

        # --- local Whisper only
        self.whisper_box = QWidget()
        whisper_form = QFormLayout(self.whisper_box)
        whisper_form.setContentsMargins(0, 0, 0, 0)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Automatic (best for this PC)", "auto")
        for model in local_stt.MODELS:
            self.model_combo.addItem(f"{model.label} ({model.download_mb} MB) - {model.note}", model.key)
        self.model_combo.currentIndexChanged.connect(self._update_model_status)
        whisper_form.addRow("Model:", self.model_combo)

        model_row = QHBoxLayout()
        self.model_status = QLabel("")
        self.model_status.setWordWrap(True)
        model_row.addWidget(self.model_status, 1)
        self.model_button = QPushButton("Download now")
        self.model_button.clicked.connect(self._download_model)
        model_row.addWidget(self.model_button)
        whisper_form.addRow("", model_row)

        self.device_combo = QComboBox()
        for key in DEVICES:
            self.device_combo.addItem(DEVICE_LABELS[key], key)
        whisper_form.addRow("Compute device:", self.device_combo)

        gpu_row = QHBoxLayout()
        self.hardware_label = QLabel("Looking for a graphics card...")
        self.hardware_label.setWordWrap(True)
        gpu_row.addWidget(self.hardware_label, 1)
        self.gpu_button = QPushButton("Install GPU libraries")
        self.gpu_button.setToolTip("Downloads NVIDIA's CUDA libraries once (about 1 GB, checksum verified)")
        self.gpu_button.setVisible(False)
        self.gpu_button.clicked.connect(self._download_gpu_libs)
        gpu_row.addWidget(self.gpu_button)
        whisper_form.addRow("Hardware:", gpu_row)
        layout.addWidget(self.whisper_box)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self._setup_google_box(layout)

        # --- window and tray
        tray_box = QGroupBox("Window and tray")
        tray_layout = QVBoxLayout(tray_box)
        self.minimize_check = QCheckBox("Minimize to the tray (the taskbar button disappears)")
        self.close_check = QCheckBox("Closing the window keeps SpeTte running in the tray")
        tray_layout.addWidget(self.minimize_check)
        tray_layout.addWidget(self.close_check)
        self.tray_note = QLabel("No system tray was found on this desktop, so these two options have no effect.")
        self.tray_note.setWordWrap(True)
        self.tray_note.setVisible(not self._tray_available)
        tray_layout.addWidget(self.tray_note)
        if not self._tray_available:
            self.minimize_check.setEnabled(False)
            self.close_check.setEnabled(False)
        window_layout.addWidget(tray_box)

        # --- background behaviour
        background_box = QGroupBox("When SpeTte is in the background (in the tray, minimized or not in front)")
        background_layout = QVBoxLayout(background_box)
        self.replace_check = QCheckBox("Each new recording replaces the previous text")
        self.copy_check = QCheckBox("Copy the recognised text to the clipboard automatically")
        background_layout.addWidget(self.replace_check)
        background_layout.addWidget(self.copy_check)
        window_layout.addWidget(background_box)

        # --- recording shortcut
        key_box = QGroupBox("Recording shortcut (works in any program)")
        key_layout = QFormLayout(key_box)
        self.hotkey_check = QCheckBox("Use a shortcut to record")
        self.hotkey_check.toggled.connect(self._update_hotkey_enabled)
        key_layout.addRow(self.hotkey_check)
        self.hotkey_edit = HotkeyEdit()
        self.hotkey_edit.problem.connect(self._show_hotkey_problem)
        self.hotkey_edit.combo_changed.connect(lambda _c: self._show_hotkey_problem(""))
        self.hotkey_edit.combo_changed.connect(lambda _c: self._update_hotkey_hint())
        key_layout.addRow("Keys:", self.hotkey_edit)
        self.hotkey_mode_combo = QComboBox()
        self.hotkey_mode_combo.addItem("Press to start, press again to stop", MODE_TOGGLE)
        self.hotkey_mode_combo.addItem("Hold to record, release to stop (push to talk)", MODE_PUSH)
        self.hotkey_mode_combo.currentIndexChanged.connect(lambda _i: self._update_hotkey_hint())
        key_layout.addRow("Behaviour:", self.hotkey_mode_combo)
        self.hotkey_note = QLabel(self._hotkey_status[1])
        self.hotkey_note.setWordWrap(True)
        self.hotkey_note.setTextFormat(Qt.TextFormat.PlainText)
        self.hotkey_note.setVisible(bool(self._hotkey_status[1]))
        key_layout.addRow(self.hotkey_note)
        self.hotkey_hint = QLabel("")
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setTextFormat(Qt.TextFormat.PlainText)
        key_layout.addRow(self.hotkey_hint)
        window_layout.addWidget(key_box)
        window_layout.addStretch()
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------ values
    def _load(self):
        s = self.settings.stt
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(s.provider)))
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(s.language)))
        found = s.device_index
        if s.device_name and s.device_name in self._mic_names:
            found = self._mic_names.index(s.device_name)       # the name wins: indexes shift
        self.microphone_combo.setCurrentIndex(max(0, self.microphone_combo.findData(found)))
        self.max_spin.setValue(s.max_seconds)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(s.whisper_model)))
        self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(s.whisper_device)))
        self.minimize_check.setChecked(s.minimize_to_tray)
        self.close_check.setChecked(s.close_to_tray)
        self.replace_check.setChecked(s.background_replace)
        self.copy_check.setChecked(s.background_copy)
        self.hotkey_check.setChecked(s.hotkey_enabled)
        self.hotkey_edit.set_combo(parse_combo(s.hotkey))
        self.hotkey_mode_combo.setCurrentIndex(max(0, self.hotkey_mode_combo.findData(s.hotkey_mode)))
        self._update_hotkey_enabled()
        self._update_hotkey_hint()
        self._update_visibility()
        self._update_model_status()

    def _setup_google_box(self, layout: QVBoxLayout):
        box = QGroupBox("Google recognition: warning and optional key")
        self.google_box = box
        column = QVBoxLayout(box)
        warning = QLabel(google_stt.SHARED_KEY_WARNING)
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.PlainText)
        column.addWidget(warning)
        row = QHBoxLayout()
        self.google_key_edit = QLineEdit()
        self.google_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_key_edit.setPlaceholderText("Your own Google API key (optional)")
        self.google_key_edit.setMaxLength(keystore.MAX_LENGTH + 20)
        self.google_key_edit.setToolTip("Optional. Leave empty to use the shared free key. A key is kept in the "
                                        "system keyring, never in the settings file or the log.")
        row.addWidget(self.google_key_edit, 1)
        self.google_key_remove = QPushButton("Remove key")
        self.google_key_remove.clicked.connect(self._remove_google_key)
        row.addWidget(self.google_key_remove)
        column.addLayout(row)
        self.google_key_status = QLabel("")
        self.google_key_status.setWordWrap(True)
        self.google_key_status.setTextFormat(Qt.TextFormat.PlainText)
        column.addWidget(self.google_key_status)
        layout.addWidget(box)
        self._refresh_google_key()

    def _refresh_google_key(self, message: str = ""):
        usable, why_not = keystore.available()
        self.google_key_edit.setEnabled(usable)
        stored = usable and keystore.has_key()
        self.google_key_remove.setEnabled(stored)
        if message:
            text = message
        elif not usable:
            text = why_not + " The shared free key is used."
        elif stored:
            text = "Your own key is stored in the system keyring and is used. Type a new one to replace it."
        else:
            text = "No key of your own: the shared free key is used."
        self.google_key_status.setText(text)

    def _remove_google_key(self):
        keystore.delete()
        self.google_key_edit.clear()
        self._refresh_google_key("The key was removed. The shared free key is used.")

    def _update_hotkey_enabled(self):
        enabled = self.hotkey_check.isChecked()
        self.hotkey_edit.setEnabled(enabled)
        self.hotkey_mode_combo.setEnabled(enabled)

    def _update_hotkey_hint(self):
        """Things worth knowing about the chosen shortcut (it is allowed, but may surprise)."""
        combo = self.hotkey_edit.combo
        lines = ["The shortcut is not blocked for other programs: they receive the same keys too."]
        if combo and not (set(combo) - MODIFIERS) and self.hotkey_mode_combo.currentData() == MODE_PUSH:
            lines.append("Push to talk with only modifier keys also triggers when you press them for another "
                         "shortcut; a letter or F key is safer.")
        self.hotkey_hint.setText(" ".join(lines))

    def _show_hotkey_problem(self, message: str):
        self.hotkey_note.setText(message or self._hotkey_status[1])
        self.hotkey_note.setVisible(bool(message or self._hotkey_status[1]))

    def values(self) -> Tuple[str, str, Optional[int], int, str, str]:
        return (self.provider_combo.currentData(), self.language_combo.currentData(),
                self.microphone_combo.currentData(), self.max_spin.value(),
                self.model_combo.currentData(), self.device_combo.currentData())

    def accept(self):
        typed = self.google_key_edit.text().strip()
        if typed and self.google_key_edit.isEnabled():
            problem = keystore.set_key(typed)
            if problem:
                self.tabs.setCurrentIndex(0)
                self._refresh_google_key(problem)
                return                              # stay open: the key was not stored
            self.google_key_edit.clear()
        s = self.settings.stt
        (s.provider, s.language, s.device_index, s.max_seconds,
         s.whisper_model, s.whisper_device) = self.values()
        names = getattr(self, "_mic_names", [])
        s.device_name = names[s.device_index] if s.device_index is not None and s.device_index < len(names) else ""
        s.minimize_to_tray = self.minimize_check.isChecked()
        s.close_to_tray = self.close_check.isChecked()
        s.background_replace = self.replace_check.isChecked()
        s.background_copy = self.copy_check.isChecked()
        s.hotkey_enabled = self.hotkey_check.isChecked()
        s.hotkey = combo_to_setting(self.hotkey_edit.combo)
        s.hotkey_mode = self.hotkey_mode_combo.currentData()
        self.settings.save()
        self._stop_workers()
        super().accept()

    def reject(self):
        self._stop_workers()
        super().reject()

    # ------------------------------------------------------------ state
    def _update_visibility(self):
        local = self.provider_combo.currentData() == "whisper"
        self.whisper_box.setVisible(local)
        self.google_box.setVisible(not local)
        self.note.setText(
            "The audio is processed on this computer. The first use of a model downloads it once."
            if local else
            "The audio is sent to Google for recognition, so this needs an internet connection. "
            f"Recordings longer than {GOOGLE_MAX_SECONDS} seconds are not accepted.")

    def _selected_model(self) -> str:
        return self.model_combo.currentData() or "auto"

    def _update_model_status(self):
        model = self._selected_model()
        busy = any(w.isRunning() for w in self._workers)
        if model == "auto":
            self.model_status.setText("The model is chosen when you record.")
            self.model_button.setEnabled(False)
        elif local_stt.is_downloaded(model):
            self.model_status.setText("Downloaded.")
            self.model_button.setEnabled(False)
        else:
            self.model_status.setText("Not downloaded yet. It downloads on first use, or now.")
            self.model_button.setEnabled(not busy)

    def _track(self, worker):
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        worker.start()

    def _worker_finished(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _stop_workers(self):
        stop_workers(list(self._workers), 200)       # a job that cannot stop (a download) goes on by itself
        self._workers.clear()

    # ------------------------------------------------------------ actions
    def _start_hardware_check(self):
        worker = HardwareWorker(self)
        worker.result_ready.connect(self._on_hardware)
        self._track(worker)

    def _on_hardware(self, hardware):
        self.hardware_label.setText(hardware.describe())
        self.gpu_button.setVisible(bool(hardware.libs_missing and cuda_libs.supported()))

    def _download_model(self):
        model = self._selected_model()
        worker = ModelDownloadWorker(model, self.device_combo.currentData() or "auto", self)
        worker.status.connect(self.model_status.setText)
        worker.done.connect(self._update_model_status)
        worker.error.connect(self.model_status.setText)
        self.model_button.setEnabled(False)
        self._track(worker)

    def _download_gpu_libs(self):
        worker = CudaDownloadWorker(self)
        worker.status.connect(self.hardware_label.setText)
        worker.done.connect(self._start_hardware_check)
        worker.error.connect(self.hardware_label.setText)
        self.gpu_button.setEnabled(False)
        worker.finished.connect(lambda: self.gpu_button.setEnabled(True))
        self._track(worker)
