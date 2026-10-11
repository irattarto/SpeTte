import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Keep models and logs out of the real profile."""
    monkeypatch.setenv("SPETTE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="session")
def app():
    import gc
    from PyQt6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()          # widgets and threads of the tests go before the application does
    gc.collect()
    application.processEvents()


_exit_status = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _exit_status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    """Windows can crash while the interpreter shuts down with Qt objects still around (exit code 0xC0000409), which
    would turn a passing run into a failing one. The results are all printed by now: leave with the real status."""
    import sys
    if sys.platform == "win32":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status["code"])


@pytest.fixture
def settings(tmp_path):
    from PyQt6.QtCore import QSettings
    from spette.settings import Settings
    loaded = Settings(QSettings(str(tmp_path / "spette.ini"), QSettings.Format.IniFormat))
    loaded.stt.hotkey_enabled = False        # tests never listen to the real keyboard
    return loaded


@pytest.fixture(autouse=True)
def memory_keyring():
    """Tests never touch the real system keyring."""
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self.items = {}

        def get_password(self, service, username):
            return self.items.get((service, username))

        def set_password(self, service, username, password):
            self.items[(service, username)] = password

        def delete_password(self, service, username):
            self.items.pop((service, username), None)

    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
