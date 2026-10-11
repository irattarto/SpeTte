"""SpeTte entry point."""

import getpass
import os
import sys


def ensure_streams() -> None:
    """A windowed program has no console: stdout/stderr are None and a library that prints would crash."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def install_excepthook() -> None:
    """PyQt ends the whole program on an unhandled error in a slot; log it and carry on instead."""
    from spette.logger import get_logger
    logger = get_logger("main")

    def hook(kind, value, trace):
        logger.error("Unhandled error", exc_info=(kind, value, trace))
    sys.excepthook = hook


def main(argv=None) -> int:
    ensure_streams()
    argv = list(sys.argv if argv is None else argv)
    if len(argv) > 1 and argv[1] == "--selfcheck":
        from spette.selfcheck import main as selfcheck
        return selfcheck(argv[2] if len(argv) > 2 else "")
    install_excepthook()

    from PyQt6.QtWidgets import QApplication
    from spette.version import APP_NAME, __version__

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)    # the window may be hidden in the tray; closing it for real quits

    from spette.single_instance import SingleInstance
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    instance = SingleInstance(f"SpeTte-{user}")
    if not instance.claim():
        return 0                            # SpeTte is already running: it has been asked to show its window

    from spette.main_window import MainWindow
    window = MainWindow()
    instance.activated.connect(window.restore_window)
    window.show()
    code = app.exec()
    instance.release()
    window.deleteLater()                    # the window goes before the application, never after it
    app.processEvents()
    del window

    from spette.workers import running_workers
    if running_workers():                   # a job that could not be stopped: leave without waiting for it
        os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
