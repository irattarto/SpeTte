"""Background threads: transcription, model download and the one-time GPU library download."""

import os
import tempfile
import time

from typing import Iterable, List

from PyQt6.QtCore import QThread, pyqtSignal

from spette.logger import get_logger

# Threads that are still busy when their owner goes away (a closed dialog, the closing window). A QThread must never
# be destroyed while it runs, so such a thread is kept here until it finishes, and the program ends without waiting.
_kept: set = set()


def keep_alive(worker: QThread) -> None:
    worker.setParent(None)
    _kept.add(worker)
    worker.finished.connect(lambda w=worker: _kept.discard(w))


def running_workers() -> List[QThread]:
    return [w for w in list(_kept) if w.isRunning()]


def stop_workers(workers: Iterable, wait_ms: int = 500) -> None:
    """Ask threads to stop and give them a moment; the ones that are still running are kept alive on their own."""
    workers = [w for w in workers if w is not None]
    for worker in workers:
        worker.requestInterruption()
    deadline = time.monotonic() + wait_ms / 1000.0
    for worker in workers:
        if worker.isRunning():
            worker.wait(max(0, int((deadline - time.monotonic()) * 1000)))
    for worker in workers:
        if worker.isRunning():
            keep_alive(worker)


class _UserMessage(Exception):
    """An error whose text can be shown to the user as is."""


def describe_error(error: Exception) -> str:
    """A short, actionable reason (the full traceback is in the log file)."""
    text = f"{type(error).__name__}: {error}".strip()
    lowered = text.lower()
    if any(w in lowered for w in ("connection", "resolve", "timed out", "offline", "huggingface", "ssl", "proxy")):
        return (f"the speech model could not be downloaded ({text[:160]}). Check the internet connection "
                "(only needed once), or choose Google in Settings.")
    if any(w in lowered for w in ("cuda", "cublas", "cudnn", "out of memory")):
        return f"the graphics card could not be used ({text[:160]}). Set the compute device to CPU in Settings."
    return text[:240]


class TranscriptionWorker(QThread):
    """Transcribe one recording; emits the text or a readable error."""

    status = pyqtSignal(str)
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_data, provider: str, language: str, whisper_model: str = "small",
                 whisper_device: str = "auto", parent=None):
        super().__init__(parent)
        self.audio_data = audio_data
        self.provider = provider
        self.language = language
        self.whisper_model = whisper_model
        self.whisper_device = whisper_device
        self.logger = get_logger('transcription_worker')

    def run(self):
        from spette.local_stt import TranscriptionCancelled
        try:
            text = self._whisper() if self.provider == "whisper" else self._google()
            if not self.isInterruptionRequested():
                self.result_ready.emit(text)
        except TranscriptionCancelled:
            self.logger.info("Transcription cancelled")
        except _UserMessage as e:
            self.error.emit(str(e))
        except Exception as e:
            self.logger.error(f"Transcription failed: {e}", exc_info=True)
            self.error.emit(f"Transcription failed: {describe_error(e)}")

    def _google(self) -> str:
        try:
            import speech_recognition as sr
        except ImportError:
            raise _UserMessage("Speech recognition is not available in this build.")
        from spette import google_stt, keystore
        key = keystore.get()                    # read here: a keyring can take a moment to answer
        self.status.emit(f"Transcribing with Google ({self.language})"
                         + (" with your own key" if key else " with the shared free key") + "...")
        try:
            return google_stt.recognize(self.audio_data, self.language, key)
        except sr.UnknownValueError:
            raise _UserMessage("Google could not understand the audio (the connection and the key are fine).")
        except sr.RequestError as e:
            self.logger.warning(f"Google request failed: {google_stt.explain_request_error(e, key)[:200]}")
            raise _UserMessage(google_stt.explain_request_error(e, key))

    def _whisper(self) -> str:
        """Local, offline transcription (GPU when usable, otherwise CPU)."""
        from spette import local_stt
        wav_data = self.audio_data.get_wav_data()
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(wav_data)
            temp_path = temp_file.name
        try:
            plan = local_stt.resolve_plan(self.whisper_model, self.whisper_device)
            self.status.emit(f"Transcribing locally with {plan.describe()}...")
            started = time.monotonic()
            self.logger.info(f"Local transcription started: plan={plan.model}/{plan.device}/{plan.compute_type}, "
                             f"{len(wav_data) // 32000} s of audio")
            segments, used = local_stt.transcribe_file(
                temp_path, plan, language=self.language, status=self.status.emit,
                should_stop=self.isInterruptionRequested)
            elapsed = time.monotonic() - started
            self.logger.info(f"Local transcription finished in {elapsed:.1f} s on {used.device}")
            if used.device != plan.device:
                self.status.emit(f"Transcribed on the CPU in {elapsed:.0f} s (the GPU could not be used).")
            else:
                self.status.emit(f"Transcribed on the {'GPU' if used.device == 'cuda' else 'CPU'} in {elapsed:.0f} s.")
            return " ".join(seg.text for seg in segments).strip()
        except RuntimeError as e:
            raise _UserMessage(str(e))
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


class CudaDownloadWorker(QThread):
    """Downloads the NVIDIA CUDA libraries for GPU transcription off the GUI thread."""

    status = pyqtSignal(str)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger('cuda_download_worker')

    def run(self):
        from spette import cuda_libs, local_stt
        try:
            cuda_libs.download(progress=self.status.emit, should_stop=self.isInterruptionRequested)
            local_stt.reset_gpu_state()
            self.done.emit()
        except cuda_libs.CudaDownloadError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.logger.error(f"CUDA library download failed: {e}", exc_info=True)
            self.error.emit(f"GPU library setup failed: {type(e).__name__}: {str(e)[:160]}")


class ModelDownloadWorker(QThread):
    """Downloads (or loads) a Whisper model so the first recording does not have to wait for it."""

    status = pyqtSignal(str)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, model: str, device: str, parent=None):
        super().__init__(parent)
        self.model = model
        self.device = device
        self.logger = get_logger('model_download_worker')

    def run(self):
        from spette import local_stt
        try:
            plan = local_stt.resolve_plan(self.model, self.device)
            local_stt.load_model(plan, self.status.emit)
            self.done.emit()
        except Exception as e:
            self.logger.error(f"Model download failed: {e}", exc_info=True)
            self.error.emit(f"Model download failed: {describe_error(e)}")


class HardwareWorker(QThread):
    """Looks for an NVIDIA GPU (can take a few seconds) without freezing the window."""

    result_ready = pyqtSignal(object)   # spette.local_stt.Hardware

    def run(self):
        from spette import local_stt
        try:
            self.result_ready.emit(local_stt.detect_hardware(refresh=True))
        except Exception as e:
            get_logger('hardware_worker').warning(f"Hardware detection failed: {e}")
            self.result_ready.emit(local_stt.Hardware())
