"""The optional Google API key, kept in the operating system's keyring (Windows Credential Manager, the Linux
Secret Service) and never in the settings file, the log or an error message.

Without a working keyring nothing is stored: the key field stays disabled instead of writing the key to a file.
"""

from typing import Optional, Tuple

from spette.logger import get_logger

SERVICE = "SpeTte"
USER = "google-api-key"
MIN_LENGTH, MAX_LENGTH = 20, 200
logger = get_logger("keystore")


def _keyring():
    """The keyring module with a usable backend, or None."""
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
            return None
        return keyring
    except Exception as e:
        logger.info(f"No keyring is available: {type(e).__name__}")
        return None


def available() -> Tuple[bool, str]:
    """(usable, explanation when not)."""
    if _keyring() is None:
        return False, "No system keyring was found on this computer, so a key cannot be stored safely."
    return True, ""


def check(key: str) -> Optional[str]:
    """None when the text can be a key, otherwise a sentence saying why not (the key itself is never repeated)."""
    key = key.strip()
    if not key:
        return "Enter a key, or leave the field empty."
    if any(c.isspace() for c in key):
        return "A key has no spaces."
    if not MIN_LENGTH <= len(key) <= MAX_LENGTH:
        return f"A key is {MIN_LENGTH} to {MAX_LENGTH} characters long."
    if not key.isascii() or not key.isprintable():
        return "A key only uses plain letters, digits and signs."
    return None


def get() -> str:
    """The stored key, or an empty string (none stored, or the keyring cannot be read)."""
    keyring = _keyring()
    if keyring is None:
        return ""
    try:
        return keyring.get_password(SERVICE, USER) or ""
    except Exception as e:
        logger.warning(f"The keyring could not be read: {type(e).__name__}")
        return ""


def has_key() -> bool:
    return bool(get())


def set_key(key: str) -> Optional[str]:
    """Store the key. None when done, otherwise the reason it was not."""
    problem = check(key)
    if problem:
        return problem
    keyring = _keyring()
    if keyring is None:
        return available()[1]
    try:
        keyring.set_password(SERVICE, USER, key.strip())
    except Exception as e:
        logger.warning(f"The keyring could not store the key: {type(e).__name__}")
        return "The system keyring refused to store the key."
    return None


def delete() -> None:
    keyring = _keyring()
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE, USER)
    except Exception as e:                  # nothing stored is fine
        logger.debug(f"Deleting the key: {type(e).__name__}")
