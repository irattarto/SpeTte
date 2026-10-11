from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from spette.hotkey_edit import HotkeyEdit, qt_key_name


def press(edit, *keys):
    for key in keys:
        QTest.keyPress(edit, key)
    for key in reversed(keys):
        QTest.keyRelease(edit, key)


def test_key_names():
    assert qt_key_name(Qt.Key.Key_Control) == "ctrl" and qt_key_name(Qt.Key.Key_Meta) == "win"
    assert qt_key_name(Qt.Key.Key_R) == "r" and qt_key_name(Qt.Key.Key_5) == "5"
    assert qt_key_name(Qt.Key.Key_F9) == "f9" and qt_key_name(Qt.Key.Key_F24) == "f24"
    assert qt_key_name(Qt.Key.Key_PageUp) == "page_up" and qt_key_name(Qt.Key.Key_Tab) is None


def test_capturing_a_combination(app):
    edit = HotkeyEdit({"f9"})
    assert edit.text() == "F9"
    seen = []
    edit.combo_changed.connect(seen.append)
    edit.click()
    assert edit.text() == "Press the keys..."
    press(edit, Qt.Key.Key_Control, Qt.Key.Key_Shift)
    assert edit.combo == frozenset({"ctrl", "shift"}) and edit.text() == "Ctrl+Shift" and len(seen) == 1
    edit.click()
    press(edit, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_R)
    assert edit.combo == frozenset({"ctrl", "alt", "r"}) and edit.text() == "Ctrl+Alt+R"


def test_refused_combinations_keep_the_old_one_and_say_why(app):
    edit = HotkeyEdit({"f9"})
    problems = []
    edit.problem.connect(problems.append)
    edit.click()
    press(edit, Qt.Key.Key_R)                                   # a plain letter
    assert edit.combo == frozenset({"f9"}) and edit.text() == "F9" and "Ctrl" in problems[-1]
    edit.click()
    press(edit, Qt.Key.Key_Control)                             # one modifier alone
    assert edit.combo == frozenset({"f9"}) and "modifier" in problems[-1]
    edit.click()
    press(edit, Qt.Key.Key_Tab)
    assert "cannot be used" in problems[-1]


def test_escape_cancels(app):
    edit = HotkeyEdit({"f9"})
    edit.click()
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    assert edit.combo == frozenset({"f9"}) and edit.text() == "F9"
