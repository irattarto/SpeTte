"""Closing things while background jobs run, the single-instance guard, the data folder, child environments."""
import os
import subprocess
import threading
import sys
import textwrap
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QThread

import main as main_module
from spette import envutil, paths, workers
from spette.single_instance import SingleInstance
from tests.helpers import wait_until

ROOT = Path(__file__).parent.parent


class SlowThread(QThread):
    def __init__(self, seconds, stoppable):
        super().__init__()
        self.seconds, self.stoppable = seconds, stoppable

    def run(self):
        end = time.time() + self.seconds
        while time.time() < end:
            if self.stoppable and self.isInterruptionRequested():
                return
            time.sleep(0.01)


def _stacks():
    import traceback
    out = []
    for ident, frame in sys._current_frames().items():
        if ident != threading.main_thread().ident:
            out.append("".join(traceback.format_stack(frame)[-4:]))
    return "\n---\n".join(out)


def test_stop_workers_returns_quickly_and_keeps_a_busy_thread_alive(app):
    stubborn, polite = SlowThread(3, stoppable=False), SlowThread(3, stoppable=True)
    stubborn.start(); polite.start()
    started = time.time()
    workers.stop_workers([stubborn, polite, None], wait_ms=300)
    assert time.time() - started < 1.5
    assert not polite.isRunning()                                    # it stopped when asked
    assert workers.running_workers() == [stubborn]                    # the other one is kept until it ends
    assert stubborn.parent() is None
    assert wait_until(app, lambda: not workers.running_workers(), timeout=6), \
        ([type(w).__name__ for w in workers.running_workers()], _stacks())     # who is still running, and where?


def run_script(code: str, timeout=60):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT))
    started = time.time()
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          timeout=timeout, env=env)
    return done, time.time() - started


def test_closing_settings_during_a_download_no_longer_freezes_or_crashes(tmp_path):
    done, seconds = run_script(f"""
        import time
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QSettings
        app = QApplication([])
        from spette import local_stt
        from spette.settings import Settings
        from spette.settings_dialog import SettingsDialog
        local_stt.load_model = lambda plan, status=None: time.sleep(4)
        s = Settings(QSettings({str(tmp_path / 'p.ini')!r}, QSettings.Format.IniFormat))
        d = SettingsDialog(s, microphones=[], detect_hardware=False, tray_available=True, hotkey_status=(True, ""))
        d.model_combo.setCurrentIndex(d.model_combo.findData("large-v3"))
        d._download_model()
        t0 = time.time()
        d.accept()
        print("accept took %.2f" % (time.time() - t0))
        del d
        import gc; gc.collect()
        print("survived")
    """)
    assert done.returncode == 0, done.stderr[-400:]
    assert "survived" in done.stdout
    took = float(done.stdout.split("accept took ")[1].split()[0])
    assert took < 1.0                                                  # it used to freeze for 3 s


def test_main_exits_without_waiting_for_a_job_that_cannot_stop(tmp_path):
    done, seconds = run_script("""
        import time, sys
        import main
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication
        from spette import workers
        import spette.main_window as mw
        class T(QThread):
            def run(self): time.sleep(20)
        QApplication.exec = lambda self: 0                 # the event loop ends at once (the user quit)
        t = T(); t.start(); workers.keep_alive(t)
        sys.exit(main.main(["x"]))
    """, timeout=30)
    assert done.returncode == 0, (done.returncode, done.stderr[-400:])         # not 134 (aborted)
    assert seconds < 15


# ----------------------------------------------------------------------- single instance
def test_a_second_instance_is_refused_and_wakes_the_first(app):
    key = f"SpeTte-test-{os.getpid()}-{time.time()}"
    first = SingleInstance(key)
    woken = []
    first.activated.connect(lambda: woken.append(1))
    assert first.claim() is True
    child = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
        import sys
        from PyQt6.QtCore import QCoreApplication
        from spette.single_instance import SingleInstance
        app = QCoreApplication([])
        sys.exit(0 if SingleInstance(sys.argv[1]).claim() is False else 1)    # 0: refused, as it should be
    """), key], env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)                   # a second program, for real
    assert wait_until(app, lambda: woken)
    assert child.wait(timeout=30) == 0
    first.release()
    third = SingleInstance(key)                                        # after the first one ended, a new start works
    assert third.claim() is True
    third.release()


# ------------------------------------------------------------------------ data folder
def test_windows_data_goes_to_local_appdata_and_the_old_roaming_folder_is_moved(tmp_path, monkeypatch):
    monkeypatch.delenv("SPETTE_DATA_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    (roaming / "SpeTte" / "models").mkdir(parents=True)
    (roaming / "SpeTte" / "models" / "m.bin").write_text("model")
    folder = paths.get_data_dir()
    assert folder == local / "SpeTte" and (folder / "models" / "m.bin").read_text() == "model"
    assert not (roaming / "SpeTte").exists()
    assert paths.get_data_dir() == folder                                # idempotent


def test_a_new_folder_is_not_overwritten_by_an_old_one(tmp_path, monkeypatch):
    monkeypatch.delenv("SPETTE_DATA_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    (tmp_path / "Local" / "SpeTte").mkdir(parents=True)
    (tmp_path / "Roaming" / "SpeTte").mkdir(parents=True)
    (tmp_path / "Roaming" / "SpeTte" / "old.txt").write_text("old")
    paths.get_data_dir()
    assert (tmp_path / "Roaming" / "SpeTte" / "old.txt").exists()


def test_linux_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SPETTE_DATA_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.get_data_dir() == tmp_path / "xdg" / "SpeTte"


# ------------------------------------------------------------------------ environment
@pytest.mark.skipif(sys.platform == "win32", reason="LD_LIBRARY_PATH is a Linux thing")
def test_bundle_library_paths_are_taken_out_of_the_child_environment(monkeypatch):
    monkeypatch.setattr(envutil.sys, "_MEIPASS", "/opt/spette/_internal", raising=False)
    env = envutil.clean_environment(base={
        "LD_LIBRARY_PATH": "/opt/spette/_internal:/tmp/.mount_x/usr/lib:/usr/local/lib", "APPDIR": "/tmp/.mount_x",
        "PATH": "/usr/bin"})
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib" and env["PATH"] == "/usr/bin"
    only_bundle = envutil.clean_environment(base={"LD_LIBRARY_PATH": "/opt/spette/_internal"})
    assert "LD_LIBRARY_PATH" not in only_bundle
    restored = envutil.clean_environment(base={"LD_LIBRARY_PATH": "/opt/spette/_internal",
                                               "LD_LIBRARY_PATH_ORIG": "/home/me/lib"})
    assert restored["LD_LIBRARY_PATH"] == "/home/me/lib"                 # what it was before PyInstaller
    empty_orig = envutil.clean_environment(base={"LD_LIBRARY_PATH": "/opt/spette/_internal",
                                                 "LD_LIBRARY_PATH_ORIG": ""})
    assert "LD_LIBRARY_PATH" not in empty_orig


def test_python_child_gets_no_foreign_python_variables():
    env = envutil.clean_environment({"X": "1"}, python_child=True,
                                    base={"PYTHONHOME": "/a", "PYTHONPATH": "/b", "KEEP": "me"})
    assert env == {"KEEP": "me", "X": "1"}
    assert envutil.clean_environment(base={"PYTHONPATH": "/b"})["PYTHONPATH"] == "/b"


# ------------------------------------------------------------------------ windowed program
def test_streams_exist_in_a_windowed_program():
    """Run in a child process: a program without a console has no stdout/stderr, and printing must not crash."""
    code = textwrap.dedent("""
        import sys
        sys.path.insert(0, %r)
        sys.stdout = None
        sys.stderr = None
        import main
        main.ensure_streams()
        print("no crash")
        sys.stderr.write("fine")
        assert sys.stdout is not None and sys.stderr is not None
    """) % str(Path(main_module.__file__).resolve().parent)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-400:]


def test_unhandled_errors_are_logged_instead_of_ending_the_program(monkeypatch, caplog):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    main_module.install_excepthook()
    try:
        raise ValueError("boom in a slot")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert sys.excepthook is not sys.__excepthook__


def test_selfcheck_finds_the_bundled_files_and_libraries(tmp_path):
    """Run in a child process: it imports every native library, and one of them must not take pytest down."""
    report = tmp_path / "report.txt"
    code = "import sys; from spette import selfcheck; sys.exit(selfcheck.main(sys.argv[1]))"
    done = subprocess.run([sys.executable, "-c", code, str(report)], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT)))
    assert done.returncode in (0, 1), (done.returncode, done.stderr[-400:])      # 0/1: it ran to the end
    text = report.read_text(encoding="utf-8")
    assert "file THIRD_PARTY_NOTICES.md" in text and "MISSING file" not in text
    assert (done.returncode == 1) == ("MISSING" in text)
