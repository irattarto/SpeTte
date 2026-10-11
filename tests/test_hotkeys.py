import time

import pytest

from spette import hotkeys
from tests.helpers import wait_until
from spette.hotkeys import (
    GlobalHotkey, HotkeyMatcher, combo_to_setting, combo_to_text, key_name, parse_combo, validate_combo,
)


class Key:                       # stands in for a pynput Key member / KeyCode
    def __init__(self, name=None, char=None, vk=None):
        self.name, self.char, self.vk = name, char, vk


def test_text_and_parsing():
    assert combo_to_text({"shift", "ctrl"}) == "Ctrl+Shift"
    assert combo_to_text({"r", "alt", "ctrl"}) == "Ctrl+Alt+R"
    assert combo_to_text({"f9"}) == "F9" and combo_to_text({"page_up", "ctrl"}) == "Ctrl+Page Up"
    assert combo_to_setting({"r", "shift", "ctrl"}) == "ctrl+shift+r"
    assert parse_combo("ctrl+shift") == frozenset({"ctrl", "shift"})
    assert parse_combo("garbage++") == frozenset({"f9"}) and parse_combo("") == frozenset({"f9"})
    assert parse_combo("a") == frozenset({"f9"})              # a plain letter is refused


@pytest.mark.parametrize("combo,ok", [
    ({"ctrl", "shift"}, True), ({"ctrl", "alt", "shift"}, True), ({"f9"}, True), ({"ctrl", "r"}, True),
    ({"pause"}, True), ({"ctrl"}, False), ({"shift"}, False), ({"r"}, False), ({"space"}, False),
    ({"ctrl", "r", "t"}, False), ({"ctrl", "tab"}, False), (set(), False),
])
def test_validate_combo(combo, ok):
    assert (validate_combo(combo) is None) is ok


def feed(matcher, *events, step=0.2, start=100.0):
    """Feed (name, down) events with a fake clock: one event every ``step`` seconds."""
    return [matcher.feed(name, down, start + step * i) for i, (name, down) in enumerate(events, 1)]


def test_toggle_with_a_key_fires_when_completed_and_ignores_repeats():
    m = HotkeyMatcher({"ctrl", "alt", "r"})
    assert feed(m, ("ctrl", True), ("alt", True), ("r", True), ("r", True), ("r", True)) == \
           [None, None, "toggle", None, None]
    assert feed(m, ("r", False), ("alt", False), ("ctrl", False), start=200) == [None, None, None]
    assert feed(m, ("ctrl", True), ("alt", True), ("r", True), start=300) == [None, None, "toggle"]   # again later


def test_function_key_alone():
    m = HotkeyMatcher({"f9"})
    assert feed(m, ("f9", True), ("f9", False), ("f9", True), ("f9", False)) == ["toggle", None, "toggle", None]


def test_modifier_only_toggle_fires_on_release_and_not_for_shortcuts_that_use_it():
    m = HotkeyMatcher({"ctrl", "shift"})
    assert feed(m, ("ctrl", True), ("shift", True), ("shift", False), ("ctrl", False)) == \
           [None, None, "toggle", None]
    # Ctrl+Shift+C (copy in many programs) must not toggle recording
    assert feed(m, ("ctrl", True), ("shift", True), ("c", True), ("c", False), ("shift", False),
                ("ctrl", False), start=200) == [None] * 6
    # and an earlier foreign key still held taints it
    assert feed(m, ("a", True), ("ctrl", True), ("shift", True), ("shift", False), ("ctrl", False),
                ("a", False), start=300) == [None] * 6
    assert feed(m, ("ctrl", True), ("shift", True), ("ctrl", False), ("shift", False), start=400) == \
           [None, None, "toggle", None]


def test_push_to_talk_starts_when_held_and_stops_a_moment_after_release():
    m = HotkeyMatcher({"ctrl", "shift"}, "push")
    assert feed(m, ("ctrl", True), ("shift", True), ("shift", True)) == [None, "start", None]
    assert feed(m, ("shift", False), start=101) == [None]
    assert m.pending and m.poll(101.25) is None and m.poll(101.3) == "stop" and not m.pending and m.poll(102) is None
    k = HotkeyMatcher({"f9"}, "push")
    assert feed(k, ("f9", True), ("f9", True)) == ["start", None]
    feed(k, ("f9", False), start=110)
    assert k.poll(111) == "stop"


def test_key_repeat_that_releases_and_presses_again_does_not_break_the_recording():
    push = HotkeyMatcher({"f9"}, "push")
    assert push.feed("f9", True, 10.0) == "start"
    assert push.feed("f9", False, 10.50) is None and push.pending
    assert push.feed("f9", True, 10.51) is None                      # the keyboard repeating: still the same press
    assert not push.pending and push.poll(11) is None
    assert push.feed("f9", False, 12.0) is None and push.poll(12.2) == "stop"
    toggle = HotkeyMatcher({"f9"})
    assert toggle.feed("f9", True, 10.0) == "toggle"
    assert toggle.feed("f9", False, 10.5) is None
    assert toggle.feed("f9", True, 10.51) is None                    # repeat, not a second toggle
    assert toggle.feed("f9", False, 12.0) is None
    assert toggle.feed("f9", True, 13.0) == "toggle"                 # a real press later


def test_altgr_typing_is_not_ctrl_alt_but_a_plain_right_alt_is_alt():
    m = HotkeyMatcher({"ctrl", "alt", "r"})
    # Windows: AltGr = a fake Ctrl, then the right Alt (pynput calls it alt_gr), then the letter
    assert [m.feed("ctrl", True, 1.000), m.feed("alt_gr", True, 1.001), m.feed("r", True, 1.2)] == [None, None, None]
    assert [m.feed("r", False, 1.3), m.feed("alt_gr", False, 1.35), m.feed("ctrl", False, 1.36)] == [None] * 3
    assert not m.held
    # a right Alt on its own (US layout) counts as Alt: Ctrl pressed long before it
    assert [m.feed("ctrl", True, 5.0), m.feed("alt_gr", True, 5.5), m.feed("r", True, 5.7)] == [None, None, "toggle"]
    assert m.feed("alt_gr", False, 6.0) is None and "alt" not in m.held


def test_a_key_whose_release_was_never_seen_is_forgotten():
    m = HotkeyMatcher({"ctrl", "shift"})
    assert m.feed("ctrl", True, 0.0) is None                         # its release is lost (lock screen, UAC)
    # a plain Shift tap long afterwards must not toggle recording
    assert [m.feed("shift", True, 1000.0), m.feed("shift", False, 1000.2)] == [None, None]
    assert m.held == set()
    push = HotkeyMatcher({"f9"}, "push")
    assert push.feed("f9", True, 0.0) == "start"
    assert push.feed("a", True, 1000.0) is None and push.poll(1000.0) == "stop"      # the stuck key ends the talk


def test_global_hotkey_emits_actions_from_listener_events(app):
    class FakeListener:
        def __init__(self, on_press, on_release):
            self.on_press, self.on_release, self.stopped = on_press, on_release, False
        def start(self): pass
        def stop(self): self.stopped = True
        def is_alive(self): return not self.stopped

    made = []

    def factory(on_press, on_release):
        made.append(FakeListener(on_press, on_release))
        return made[-1]

    hk = GlobalHotkey(listener_factory=factory)
    actions = []
    hk.triggered.connect(actions.append)
    ok, message = hk.start({"ctrl", "shift"}, "push")
    assert ok and message == "" and hk.running
    made[0].on_press(Key(name="ctrl_l"))
    time.sleep(0.06)
    made[0].on_press(Key(name="shift"))
    time.sleep(0.06)
    made[0].on_release(Key(name="shift"))
    assert actions == ["start"]                                      # the stop waits a moment
    assert wait_until(app, lambda: actions == ["start", "stop"], timeout=2)

    ok, message = hk.start({"ctrl"}, "toggle")                       # invalid: refused, old listener stopped
    assert not ok and "modifier" in message and made[0].stopped and not hk.running
    hk.stop()


def test_key_repeat_from_a_real_listener_does_not_chop_push_to_talk(app):
    class FakeListener:
        def __init__(self, on_press, on_release):
            self.on_press, self.on_release = on_press, on_release
        def start(self): pass
        def stop(self): pass

    made = []
    hk = GlobalHotkey(listener_factory=lambda p, r: made.append(FakeListener(p, r)) or made[-1])
    actions = []
    hk.triggered.connect(actions.append)
    hk.start({"f9"}, "push")
    made[0].on_press(Key(name="f9"))
    for _ in range(3):                                               # X11 style repeat: release + press pairs
        time.sleep(0.15)
        made[0].on_release(Key(name="f9"))
        made[0].on_press(Key(name="f9"))
    time.sleep(0.3)
    app.processEvents()
    assert actions == ["start"]
    made[0].on_release(Key(name="f9"))
    assert wait_until(app, lambda: actions == ["start", "stop"], timeout=2)
    hk.stop()


def test_a_listener_that_dies_at_once_is_reported(app):
    class DeadListener:
        def __init__(self, *a): pass
        def start(self): pass
        def is_alive(self): return False
        def stop(self): pass
    hk = GlobalHotkey(listener_factory=lambda p, r: DeadListener())
    ok, message = hk.start({"f9"})
    assert not ok and message and not hk.running


def test_global_hotkey_reports_a_missing_backend(app):
    def broken(on_press, on_release):
        raise RuntimeError("no display")
    hk = GlobalHotkey(listener_factory=broken)
    ok, message = hk.start({"f9"})
    assert not ok and message and not hk.running


def test_key_names_from_pynput_keys(monkeypatch):
    assert key_name(Key(name="ctrl_l")) == "ctrl" and key_name(Key(name="shift_r")) == "shift"
    assert key_name(Key(name="cmd")) == "win" and key_name(Key(name="f9")) == "f9"
    assert key_name(Key(char="R")) == "r"
    monkeypatch.setattr(hotkeys.sys, "platform", "linux")
    assert key_name(Key(char="\x12", vk=0x72)) == "r"                  # Ctrl+R arrives as a control character
    monkeypatch.setattr(hotkeys.sys, "platform", "win32")
    assert key_name(Key(char="\x12", vk=0x52)) == "r"
    assert key_name(Key(char=None, vk=0xAD)) is None


def test_backend_status_without_a_display(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *args, **kwargs):
        if name.startswith("pynput"):
            raise ImportError("this platform is not supported")
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake)
    ok, message = hotkeys.backend_status()
    assert not ok and "Record button still works" in message
