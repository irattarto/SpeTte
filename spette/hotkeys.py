"""The system-wide recording shortcut: key names, combination rules, and the global listener.

A combination is a set of key names such as {"ctrl", "shift"}, {"ctrl", "alt", "r"} or {"f9"}.
It works while any program has focus. Listening uses pynput (Windows, and Linux under X11/XWayland).
"""

import os
import sys
import threading
import time
from typing import Callable, Iterable, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from spette.logger import get_logger

MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
MODIFIERS = frozenset(MODIFIER_ORDER)
FUNCTION_KEYS = frozenset(f"f{n}" for n in range(1, 25))
SPECIAL_KEYS = frozenset({"space", "pause", "scroll_lock", "insert", "home", "end", "page_up", "page_down",
                          "print_screen"})
# usable without a modifier: they are not typed into text
ALONE_OK = FUNCTION_KEYS | {"pause", "scroll_lock", "print_screen"}
ALLOWED_KEYS = FUNCTION_KEYS | SPECIAL_KEYS | frozenset("abcdefghijklmnopqrstuvwxyz0123456789")

MODE_TOGGLE = "toggle"   # press once to start, again to stop
MODE_PUSH = "push"       # hold to record, release to stop
MODES = (MODE_TOGGLE, MODE_PUSH)
DEFAULT_COMBO = "f9"

_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "space": "Space", "pause": "Pause",
           "scroll_lock": "Scroll Lock", "insert": "Insert", "home": "Home", "end": "End",
           "page_up": "Page Up", "page_down": "Page Down", "print_screen": "Print Screen"}


# ----------------------------------------------------------- combinations
def sort_combo(combo: Iterable[str]) -> list:
    """Modifiers first (Ctrl, Alt, Shift, Win), then the other key."""
    names = set(combo)
    return [m for m in MODIFIER_ORDER if m in names] + sorted(names - MODIFIERS)


def combo_to_text(combo: Iterable[str]) -> str:
    """'ctrl+shift' -> 'Ctrl+Shift'."""
    return "+".join(_LABELS.get(n, n.upper()) for n in sort_combo(combo))


def combo_to_setting(combo: Iterable[str]) -> str:
    return "+".join(sort_combo(combo))


def parse_combo(text: str) -> frozenset:
    """Read a stored combination; anything invalid gives the default."""
    names = frozenset(part.strip().lower() for part in str(text or "").split("+") if part.strip())
    return names if names and validate_combo(names) is None else frozenset(DEFAULT_COMBO.split("+"))


def validate_combo(combo: Iterable[str]) -> Optional[str]:
    """None when the combination can be used, otherwise a sentence saying why not."""
    names = set(combo)
    if not names:
        return "Press the keys you want to use."
    keys = names - MODIFIERS
    mods = names & MODIFIERS
    if len(keys) > 1:
        return "Use at most one key besides Ctrl, Alt, Shift and Win."
    if keys and not keys <= ALLOWED_KEYS:
        return "That key cannot be used. Try a letter, a digit or an F key."
    if not keys and len(mods) < 2:
        return "A single modifier key is too easy to hit by accident. Add another modifier or a key."
    if keys and not mods and not keys <= ALONE_OK:
        return "Add Ctrl, Alt or Shift, otherwise you could not type that key anymore. F keys work alone."
    return None


# ---------------------------------------------------------------- matching
STALE_SECONDS = 600.0     # a key that has shown no sign of life for this long lost its release (lock screen, UAC)
REPEAT_GAP = 0.05         # a key released and pressed again this fast is the keyboard repeating, not the user
STOP_DELAY = 0.08         # push to talk: a release followed by a press within this time is key repeat
ALTGR_GAP = 0.05          # Windows sends a fake Ctrl just before the right Alt when AltGr is pressed


class HotkeyMatcher:
    """Turns key down/up events into 'toggle', 'start' or 'stop' (no Qt, no pynput: easy to test).

    Toggle mode: a combination with a key fires when it is completed; a modifier-only one (such as
    Ctrl+Shift) fires when it is released, and only if no other key was pressed meanwhile, so
    Ctrl+Shift+C is not mistaken for it. Push mode: 'start' when the combination is held, 'stop' shortly after
    it is released (``poll`` delivers it; a quick re-press, as key repeat makes, cancels it).

    Also: AltGr (Windows sends Ctrl+Alt for it) is not taken for Ctrl+Alt, a right Alt key without that fake Ctrl
    counts as Alt, and a key whose release was never seen is forgotten after STALE_SECONDS.
    """

    def __init__(self, combo: Iterable[str], mode: str = MODE_TOGGLE, clock: Callable[[], float] = time.monotonic):
        self.combo = frozenset(combo)
        self.mode = mode if mode in MODES else MODE_TOGGLE
        self.modifier_only = self.combo <= MODIFIERS
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.held: set = set()
        self._seen: dict = {}
        self._released: dict = {}
        self._ctrl_down = float("-inf")
        self._altgr_chord = False
        self._complete = False
        self._tainted = False
        self._pending_stop: Optional[float] = None

    @property
    def pending(self) -> bool:
        return self._pending_stop is not None

    # ------------------------------------------------------------------ input
    def feed(self, name: str, down: bool, now: Optional[float] = None) -> Optional[str]:
        now = self._clock() if now is None else now
        self._expire(now)
        if name == "alt_gr":
            if down:
                if "ctrl" in self.held and now - self._ctrl_down <= ALTGR_GAP:
                    self.held.discard("ctrl")                  # that Ctrl was AltGr's, not the user's
                    self._altgr_chord = True
                    self._break_if_incomplete(now)
                    return None
                name = "alt"                                   # a plain right Alt key
            else:
                if self._altgr_chord:
                    self._altgr_chord = False
                    return None
                name = "alt"
        return self._down(name, now) if down else self._up(name, now)

    def poll(self, now: Optional[float] = None) -> Optional[str]:
        """The delayed 'stop' of push to talk, once nothing has re-pressed the key."""
        now = self._clock() if now is None else now
        if self._pending_stop is not None and now >= self._pending_stop:
            self._pending_stop = None
            return "stop"
        return None

    # ------------------------------------------------------------------ steps
    def _down(self, name: str, now: float) -> Optional[str]:
        if name == "ctrl":
            self._ctrl_down = now
        self._seen[name] = now
        if name in self.held:
            return None                                        # key repeat
        released = self._released.get(name)
        repeated = released is not None and now - released < REPEAT_GAP and name in self.combo
        self.held.add(name)
        if name not in self.combo:
            self._tainted = True
        if self._complete or not self.combo <= self.held:
            return None
        self._complete = True
        if repeated or self._pending_stop is not None:         # the same press continuing
            self._pending_stop = None
            return None
        if self.mode == MODE_PUSH:
            return "start"
        return None if self.modifier_only else "toggle"

    def _up(self, name: str, now: float) -> Optional[str]:
        self._released[name] = now
        if name not in self.held:
            return None
        self.held.discard(name)
        action = self._break_if_incomplete(now, from_release=True)
        if not self.held:
            self._tainted = False
        return action

    def _break_if_incomplete(self, now: float, from_release: bool = False) -> Optional[str]:
        if not self._complete or self.combo <= self.held:
            return None
        self._complete = False
        if self.mode == MODE_PUSH:
            self._pending_stop = now + (STOP_DELAY if from_release else 0.0)
            return None
        if from_release and self.modifier_only and not self._tainted:
            return "toggle"
        return None

    def _expire(self, now: float) -> None:
        stale = [k for k in self.held if now - self._seen.get(k, now) > STALE_SECONDS]
        for key in stale:
            self.held.discard(key)
            self._seen.pop(key, None)
        if stale:
            self._break_if_incomplete(now)
            if not self.held:
                self._tainted = False


# ----------------------------------------------------------- pynput glue
_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
}


def key_name(key) -> Optional[str]:
    """Our name for a pynput key (a Key member or a KeyCode), or None for keys we do not know."""
    name = getattr(key, "name", None)
    if name:
        return _MODIFIER_ALIASES.get(name, name)
    char = getattr(key, "char", None)
    if char and len(char) == 1 and char.isprintable() and not char.isspace():
        return char.lower()
    vk = getattr(key, "vk", None)
    if isinstance(vk, int):          # Ctrl+letter can arrive as a control character: use the key code
        if sys.platform == "win32":
            if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
                return chr(vk).lower()
        elif 0x20 < vk < 0x7F:
            return chr(vk).lower()
    return None


def backend_status() -> Tuple[bool, str]:
    """(available, explanation). Available when system-wide key listening can work here."""
    try:
        import pynput.keyboard  # noqa: F401
    except Exception as e:
        get_logger("hotkeys").info(f"System-wide shortcuts are not available: {str(e)[:200]}")
        return False, ("System-wide shortcuts are not available on this system (no X11 display or no permission "
                       "to listen to the keyboard). The Record button still works.")
    if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True, ("On Wayland the shortcut only reacts while a program running through X11 (XWayland) has "
                      "the focus; it may not work on a native Wayland window.")
    return True, ""


class GlobalHotkey(QObject):
    """Listens to the keyboard system-wide and emits ``triggered('toggle' | 'start' | 'stop')``."""

    triggered = pyqtSignal(str)

    def __init__(self, parent=None, listener_factory: Optional[Callable] = None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self._factory = listener_factory
        self._clock = clock
        self._listener = None
        self._matcher: Optional[HotkeyMatcher] = None
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self.logger = get_logger("hotkeys")

    @property
    def running(self) -> bool:
        return self._listener is not None

    def start(self, combo: Iterable[str], mode: str = MODE_TOGGLE) -> Tuple[bool, str]:
        """(Re)start listening. Returns (ok, message for the user when not ok)."""
        self.stop()
        error = validate_combo(combo)
        if error:
            return False, error
        with self._lock:
            self._matcher = HotkeyMatcher(combo, mode, self._clock)
        try:
            if self._factory is not None:
                listener = self._factory(self._on_press, self._on_release)
            else:
                from pynput import keyboard
                listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            listener.daemon = True
            listener.start()
            time.sleep(0.1)                                 # a listener that cannot hook the keyboard ends at once
            if hasattr(listener, "is_alive") and not listener.is_alive():
                raise RuntimeError("the key listener ended right after it started")
        except Exception as e:
            self.logger.warning(f"Could not start the global shortcut: {e}")
            with self._lock:
                self._matcher = None
            return False, backend_status()[1] or "The system-wide shortcut could not be started."
        self._listener = listener
        return True, ""

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception as e:
                self.logger.debug(f"Stopping the key listener failed: {e}")
        with self._lock:
            self._matcher = None
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def _on_press(self, key) -> None:
        self._handle(key, True)

    def _on_release(self, key) -> None:
        self._handle(key, False)

    def _handle(self, key, down: bool) -> None:
        name = key_name(key)
        if name is None:
            return
        with self._lock:
            action = self._matcher.feed(name, down) if self._matcher else None
            pending = bool(self._matcher and self._matcher.pending)
        if action:
            self.triggered.emit(action)     # queued to the GUI thread by Qt
        if pending:
            self._schedule_poll()

    def _schedule_poll(self) -> None:
        """The 'stop' of push to talk is delayed a moment (key repeat releases and presses the key again)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(STOP_DELAY + 0.02, self._poll)
            self._timer.daemon = True
            self._timer.start()

    def _poll(self) -> None:
        with self._lock:
            action = self._matcher.poll() if self._matcher else None
            pending = bool(self._matcher and self._matcher.pending)
        if action:
            self.triggered.emit(action)
        if pending:
            self._schedule_poll()
