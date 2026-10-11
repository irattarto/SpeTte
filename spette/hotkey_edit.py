"""A button that records a key combination: click it, press the keys, let go."""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QPushButton

from spette.hotkeys import combo_to_text, validate_combo

_SPECIAL = {
    Qt.Key.Key_Control: "ctrl", Qt.Key.Key_Shift: "shift", Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win", Qt.Key.Key_Super_L: "win", Qt.Key.Key_Super_R: "win",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Pause: "pause", Qt.Key.Key_ScrollLock: "scroll_lock",
    Qt.Key.Key_Insert: "insert", Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page_up", Qt.Key.Key_PageDown: "page_down", Qt.Key.Key_Print: "print_screen",
}


def qt_key_name(key: int) -> Optional[str]:
    """Our key name for a Qt key code, or None when the key cannot be part of a shortcut."""
    try:
        special = _SPECIAL.get(Qt.Key(key))
    except ValueError:
        special = None
    if special:
        return special
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key).lower()
    return None


class HotkeyEdit(QPushButton):
    combo_changed = pyqtSignal(object)    # frozenset of key names
    problem = pyqtSignal(str)             # why a pressed combination was refused

    def __init__(self, combo=frozenset(), parent=None):
        super().__init__(parent)
        self._combo = frozenset(combo)
        self._capturing = False
        self._held = set()
        self._peak = set()
        self._unknown = False
        self.setToolTip("Click, then press the keys you want to use and let go. Esc cancels.")
        self.clicked.connect(self._begin)
        self._show()

    @property
    def combo(self) -> frozenset:
        return self._combo

    def set_combo(self, combo) -> None:
        self._combo = frozenset(combo)
        self._show()

    def _show(self) -> None:
        self.setText("Press the keys..." if self._capturing else (combo_to_text(self._combo) or "Not set"))

    def _begin(self) -> None:
        self._capturing = True
        self._held, self._peak, self._unknown = set(), set(), False
        self.setFocus()
        self._show()

    def _end(self) -> None:
        self._capturing = False
        self._held, self._peak = set(), set()
        self._show()

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False if self._capturing else super().focusNextPrevChild(forward)

    def focusOutEvent(self, event) -> None:
        if self._capturing:
            self._end()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape:
            self._end()
            return
        name = qt_key_name(event.key())
        if name is None:
            self._unknown = True
        else:
            self._held.add(name)
            if len(self._held) > len(self._peak):
                self._peak = set(self._held)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            return
        name = qt_key_name(event.key())
        self._held.discard(name)
        if not self._held:
            peak, unknown = self._peak, self._unknown
            self._end()
            if unknown:
                self.problem.emit("That key cannot be used. Try a letter, a digit or an F key.")
            elif peak:
                error = validate_combo(peak)
                if error:
                    self.problem.emit(error)
                else:
                    self._combo = frozenset(peak)
                    self._show()
                    self.combo_changed.emit(self._combo)
        event.accept()
