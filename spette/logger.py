"""Logging to a rotating file in the data folder (and to the console)."""

import logging
from logging.handlers import RotatingFileHandler

_ROOT = 'spette'
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger(_ROOT)
    root.setLevel(logging.INFO)
    root.propagate = False
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(levelname)s - %(name)s - %(message)s'))
    root.addHandler(console)
    try:
        from spette.paths import get_data_dir
        log_dir = get_data_dir() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / 'spette.log', maxBytes=2 * 1024 * 1024, backupCount=3,
                                      encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'))
        root.addHandler(handler)
    except OSError:
        pass   # no writable data folder: the console is enough


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f'{_ROOT}.{name}')
