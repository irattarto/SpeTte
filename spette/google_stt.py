"""Speech recognition through Google's free web service, and clear explanations when it fails.

Without a key of its own, the SpeechRecognition library uses a shared public key. Google can limit or switch it
off at any time, and everybody using it shares its limit, so failures are explained in plain words.
"""

from typing import Optional

SHARED_KEY_WARNING = (
    "Google recognition sends your audio over the internet to Google and uses a free public key shared by all "
    "users of the library. Google can limit or switch that key off at any time, then this stops working. "
    "Local recognition (Whisper) is private, offline and does not depend on it."
)
USE_WHISPER = "Choose local recognition (Whisper) in Settings to work without it."


def explain_request_error(error: BaseException, key: str = "") -> str:
    """What a failed request means for the user. The key is never part of the text."""
    text = str(error)
    if key:
        text = text.replace(key, "***")
    lowered = text.lower()
    own = bool(key)
    if "connection failed" in lowered or "timed out" in lowered or "name or service" in lowered:
        return "Google could not be reached. Check the internet connection, or " + USE_WHISPER[0].lower() + USE_WHISPER[1:]
    if any(w in lowered for w in ("too many requests", "429", "quota", "rate")):
        return ("Google says too many requests were made" + (" with your key" if own else " with the shared free key")
                + ". Try again later. " + USE_WHISPER)
    if any(w in lowered for w in ("forbidden", "403", "unauthorized", "401", "bad request", "400", "invalid")):
        if own:
            return "Google refused the key you entered in Settings. Check it or remove it. " + USE_WHISPER
        return ("Google refused the shared free key: it is probably blocked or switched off. " + USE_WHISPER)
    return f"Google recognition failed ({text[:120]}). " + USE_WHISPER


def recognize(audio_data, language: str, key: Optional[str] = None) -> str:
    """Text for the recording. Raises ``speech_recognition.UnknownValueError`` when nothing was understood and
    ``speech_recognition.RequestError`` when the request failed."""
    import speech_recognition as sr
    return sr.Recognizer().recognize_google(audio_data, language=language, key=key or None)
