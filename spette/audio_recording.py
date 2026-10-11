"""
Microphone recording that can be stopped on demand.
"""

from typing import Tuple

from PyQt6.QtCore import QThread, pyqtSignal as Signal
from spette.logger import get_logger

MSG_NO_PYAUDIO = (
    "Microphone support is not installed in this build (the PyAudio component is missing). "
    "Install it with: pip install PyAudio"
)
MSG_NO_MICROPHONE = "No microphone found. Connect one (or choose another device in Settings) and try again."
MSG_ACCESS_DENIED = (
    "Microphone access is blocked. On Windows open Settings > Privacy & security > Microphone "
    "and allow desktop apps to use the microphone."
)


def microphone_support_status() -> Tuple[bool, str]:
    """Return (available, reason). Available only when PyAudio can be imported."""
    try:
        import pyaudio  # noqa: F401
    except Exception:
        return False, MSG_NO_PYAUDIO
    return True, ""


def resolve_device_index(names, index, name: str = ""):
    """The microphone to use: found by its name when it is known, else by the stored index, else the default.

    Indexes shift when devices are plugged in or removed, names do not. Returns (index or None, note or "").
    """
    names = list(names or [])
    if name:
        matches = [i for i, n in enumerate(names) if n == name]
        if matches:
            return matches[0], ""
        return None, f"The microphone '{name}' was not found, so the default microphone is used."
    if index is not None and 0 <= index < len(names):
        return index, ""
    return None, ""


def friendly_microphone_error(error: BaseException) -> str:
    """Turn a low-level microphone initialisation error into a message a user can act on.

    The technical text stays in the log; this is what the status bar shows.
    """
    text = str(error)
    lowered = text.lower()
    if isinstance(error, ImportError) or "pyaudio" in lowered:
        return MSG_NO_PYAUDIO
    if "10013" in text or ("access" in lowered and "denied" in lowered) or "permission" in lowered:
        return MSG_ACCESS_DENIED
    if ("no default input" in lowered or "invalid input device" in lowered or "-9996" in text
            or "no input device" in lowered or "device unavailable" in lowered):
        return MSG_NO_MICROPHONE
    return f"Failed to initialize microphone: {text}"


class AudioRecordingThread(QThread):
    """Thread for continuous audio recording that can be stopped on demand."""

    recording_finished = Signal(object)  # Emits AudioData object or None
    recording_error = Signal(str)  # Emits error message

    def __init__(self, device_index=None, parent=None, device_name: str = ""):
        super().__init__(parent)
        self.device_index = device_index
        self.device_name = device_name
        self._stop_requested = False
        self._frames = []
        self.logger = get_logger('audio_recording')

    def stop_recording(self):
        """Request to stop recording."""
        self._stop_requested = True

    def run(self):
        """Run the recording loop with timeout and error handling."""
        try:
            import speech_recognition as sr

            # Flag to track if microphone initialization succeeded
            mic_initialized = False
            microphone = None

            try:
                # Try to initialize microphone with timeout protection
                self.logger.debug("Initializing microphone...")

                # Create microphone object (the chosen one, found by name: the numbers change with the devices)
                index, note = resolve_device_index(sr.Microphone.list_microphone_names(), self.device_index,
                                                   self.device_name)
                if note:
                    self.logger.warning(note)
                if index is not None:
                    microphone = sr.Microphone(device_index=index)
                else:
                    microphone = sr.Microphone()

                mic_initialized = True
                self.logger.debug("Microphone initialized successfully")

            except Exception as e:
                # Permission errors (WinError 10013), missing PyAudio, no input device, ...
                self.logger.error(f"Microphone initialisation failed: {e!r}")
                self.recording_error.emit(friendly_microphone_error(e))
                return

            if not mic_initialized or microphone is None:
                self.recording_error.emit("Microphone initialization failed")
                return

            # Try to open microphone stream with timeout
            try:
                self.logger.debug("Opening microphone stream...")

                with microphone as source:
                    # Adjust for ambient noise briefly
                    self.logger.debug("Adjusting for ambient noise...")

                    # Start continuous recording
                    stream = source.stream
                    if not stream:
                        self.recording_error.emit("Failed to open audio stream")
                        return

                    # Read audio in chunks
                    chunk_size = 1024
                    while not self._stop_requested:
                        try:
                            # Read chunk
                            chunk = stream.read(chunk_size)
                            if chunk:
                                self._frames.append(chunk)
                        except Exception as e:
                            self.logger.debug(f"Stream read error: {e}")
                            break

                # Convert frames to AudioData
                if self._frames:
                    # Combine all frames
                    audio_data = b''.join(self._frames)
                    self.logger.debug(f"Recorded {len(audio_data)} bytes of audio data")

                    # Create AudioData object with proper parameters
                    audio = sr.AudioData(audio_data, source.SAMPLE_RATE, source.SAMPLE_WIDTH)
                    self.recording_finished.emit(audio)
                else:
                    # No frames recorded
                    self.logger.debug("No audio frames recorded")
                    self.recording_finished.emit(None)

            except OSError as e:
                # Handle stream access errors
                friendly = friendly_microphone_error(e)
                error_msg = friendly if not friendly.startswith("Failed to initialize") else f"Audio stream error: {e}"
                self.logger.error(error_msg)
                self.recording_error.emit(error_msg)

            except Exception as e:
                error_msg = f"Recording error: {str(e)}"
                self.logger.error(error_msg)
                self.recording_error.emit(error_msg)

        except ImportError:
            error_msg = "speech_recognition library not available"
            self.logger.error(error_msg)
            self.recording_error.emit(error_msg)

        except Exception as e:
            error_msg = f"Unexpected recording error: {str(e)}"
            self.logger.error(error_msg)
            import traceback
            traceback.print_exc()
            self.recording_error.emit(error_msg)
