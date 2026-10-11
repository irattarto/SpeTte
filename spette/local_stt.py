"""
Local (offline) speech-to-text with faster-whisper.

Nothing here talks to the network except the one-time model download from Hugging Face.
The model runs on an NVIDIA GPU when one is usable and falls back to the CPU otherwise, so
weak or missing graphics cards only make it slower, never unusable.
"""

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from spette.envutil import clean_environment
from spette.logger import get_logger

logger = get_logger('local_stt')


class TranscriptionCancelled(Exception):
    """Raised when the user cancels a running transcription."""


@dataclass(frozen=True)
class ModelInfo:
    key: str
    label: str
    download_mb: int
    vram_mb: int       # rough GPU memory needed (int8_float16/float16)
    note: str


MODELS: List[ModelInfo] = [
    ModelInfo('tiny', 'Tiny', 75, 1000, 'Very fast, poor with Hungarian'),
    ModelInfo('base', 'Base', 145, 1000, 'Fast, weak with Hungarian'),
    ModelInfo('small', 'Small', 480, 2000, 'Good balance, minimum for Hungarian on weak PCs'),
    ModelInfo('medium', 'Medium', 1500, 4000, 'Good quality'),
    ModelInfo('large-v3-turbo', 'Large v3 Turbo', 1600, 5000, 'Near-best quality, fast'),
    ModelInfo('large-v3', 'Large v3', 3000, 6000, 'Best quality (recommended with a 6+ GB GPU)'),
]
_MODEL_KEYS = {m.key for m in MODELS}


def model_vram_mb(name: str) -> int:
    """Rough graphics memory a model needs."""
    key = normalize_model_name(name)
    return next((m.vram_mb for m in MODELS if m.key == key), 6000)


def normalize_model_name(name: str) -> str:
    """Old settings used 'large'; map it to the current best model."""
    name = (name or 'small').strip().lower()
    if name == 'large':
        return 'large-v3'
    return name if name in _MODEL_KEYS else 'small'


def normalize_language(code: Optional[str]) -> Optional[str]:
    """'hu-HU' -> 'hu'; 'auto' or empty -> None (let Whisper detect it)."""
    if not code or code.strip().lower() == 'auto':
        return None
    return code.strip().split('-')[0].lower()


def models_dir() -> Path:
    """Where downloaded models live (SpeTte keeps its own copy, separate from other programs)."""
    from spette.paths import get_data_dir
    path = get_data_dir() / 'models' / 'whisper'
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- hardware ---------------------------------------------------------------
@dataclass
class Hardware:
    gpu_name: Optional[str] = None
    vram_mb: int = 0
    cuda_available: bool = False
    cpu_threads: int = 1
    libs_missing: bool = False  # NVIDIA GPU found, but the CUDA libraries are not installed yet (Windows)

    def describe(self) -> str:
        if self.gpu_name:
            gpu = f"{self.gpu_name} ({self.vram_mb // 1024 or '?'} GB)"
            if self.cuda_available:
                return gpu
            reason = "the GPU libraries are not installed yet" if self.libs_missing else "CUDA libraries missing"
            return f"{gpu}, but it cannot be used for transcription ({reason})"
        return f"No NVIDIA GPU found, using the CPU ({self.cpu_threads} threads)"


_hardware: Optional[Hardware] = None
_hardware_lock = threading.Lock()
_cuda_broken = False  # a GPU run failed in this session; stop retrying (and reloading the model) every time


def detect_hardware(refresh: bool = False) -> Hardware:
    """The hardware (found once; the first call can take seconds: nvidia-smi and the ctranslate2 import)."""
    global _hardware
    with _hardware_lock:
        if _hardware is None or refresh:
            _hardware = _detect_hardware()
        return _hardware


def cached_hardware() -> Optional[Hardware]:
    """The hardware if it has been found already, else None (never waits)."""
    return _hardware


def prefetch_hardware() -> None:
    """Find the hardware in the background, so that no recording or window has to wait for it."""
    if _hardware is None:
        threading.Thread(target=detect_hardware, daemon=True, name="hardware-prefetch").start()


def reset_gpu_state() -> None:
    """Forget a failed GPU attempt and re-detect (after the CUDA libraries were installed)."""
    global _cuda_broken
    _cuda_broken = False
    clear_cache()
    detect_hardware(refresh=True)


def gpu_libs_missing() -> bool:
    """True when an NVIDIA GPU is present but the downloadable CUDA libraries are not installed."""
    return detect_hardware().libs_missing


def _detect_hardware() -> Hardware:
    from spette import cuda_libs
    cuda_libs.register()
    hw = Hardware(cpu_threads=os.cpu_count() or 1)
    exe = shutil.which('nvidia-smi')
    if exe:
        try:
            out = subprocess.run(
                [exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=8, env=clean_environment(),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            ).stdout.strip().splitlines()
            if out:
                name, mem = [p.strip() for p in out[0].rsplit(',', 1)]
                hw.gpu_name, hw.vram_mb = name, int(float(mem))
        except Exception as e:
            logger.debug(f"nvidia-smi failed: {e}")
    try:
        import ctranslate2
        driver_ok = ctranslate2.get_cuda_device_count() > 0
        libs_ok = not cuda_libs.supported() or cuda_libs.libs_present()
        hw.cuda_available = driver_ok and libs_ok
        hw.libs_missing = driver_ok and not libs_ok
    except Exception as e:
        logger.debug(f"ctranslate2 CUDA check failed: {e}")
    return hw


@dataclass
class Plan:
    model: str
    device: str        # 'cuda' or 'cpu'
    compute_type: str

    def describe(self) -> str:
        where = "GPU" if self.device == 'cuda' else "CPU"
        return f"{self.model} on the {where}"


def recommend(hw: Hardware) -> Plan:
    """Best model/device for this PC. Weak or missing GPUs get a smaller model on the CPU."""
    if hw.cuda_available and hw.vram_mb >= 6000:
        return Plan('large-v3', 'cuda', 'float16' if hw.vram_mb >= 8000 else 'int8_float16')
    if hw.cuda_available and hw.vram_mb >= 4000:
        return Plan('medium', 'cuda', 'int8_float16')
    if hw.cuda_available and hw.vram_mb >= 2000:
        return Plan('small', 'cuda', 'int8_float16')
    return Plan('small' if hw.cpu_threads >= 4 else 'base', 'cpu', 'int8')


def resolve_plan(model: str, device: str, hw: Optional[Hardware] = None) -> Plan:
    """Turn user choices ('auto'/'cuda'/'cpu' plus a model, or 'auto') into a concrete plan."""
    hw = hw or detect_hardware()
    model = (model or 'auto').lower()
    device = (device or 'auto').lower()
    best = recommend(hw)
    chosen_model = best.model if model == 'auto' else normalize_model_name(model)
    if device == 'cpu':
        return Plan(chosen_model, 'cpu', 'int8')
    if device in ('cuda', 'gpu') or (device == 'auto' and hw.cuda_available):
        return Plan(chosen_model, 'cuda', 'float16' if hw.vram_mb >= 8000 else 'int8_float16')
    return Plan(chosen_model, 'cpu', 'int8')


# --- model cache -------------------------------------------------------------
_cache: Dict[Tuple[str, str, str], object] = {}
_cache_lock = threading.Lock()


def is_downloaded(model: str) -> bool:
    """True when the model files are already in the local cache (so loading needs no download)."""
    try:
        for repo in models_dir().glob(f"models--*faster-whisper-{model}"):
            if any(repo.glob("snapshots/*/model.bin")):
                return True
    except OSError:
        pass
    return False


def preload(plan: Plan) -> None:
    """Load the model in the background so it is ready when the recording ends."""
    def run():
        try:
            load_model(plan)
        except Exception as e:
            logger.debug(f"Model preload failed: {e}")
    threading.Thread(target=run, daemon=True, name="stt-preload").start()


def load_model(plan: Plan, status: Optional[Callable[[str], None]] = None):
    """Load (and cache) a model. Downloads it on first use."""
    key = (plan.model, plan.device, plan.compute_type)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError("faster-whisper is not installed in this build.") from e
        if status:
            if is_downloaded(plan.model):
                status(f"Loading the {plan.model} model into memory (it is already downloaded; "
                       "this takes a while only the first time after starting the app)...")
            else:
                status(f"Downloading the {plan.model} model (one time only, up to a few GB)...")
        model = WhisperModel(plan.model, device=plan.device, compute_type=plan.compute_type,
                             download_root=str(models_dir()))
        _cache.clear()  # keep one model in memory
        _cache[key] = model
        return model


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- transcription -----------------------------------------------------------
@dataclass
class Segment:
    start: float
    end: float
    text: str


NO_SPEECH_LIMIT = 0.6      # Whisper's own estimate that a segment is not speech; above it the text is made up


def is_probably_noise(segment) -> bool:
    """On silence or background noise Whisper invents a phrase ("thank you very much"); it rates that text as
    probably-not-speech itself, so such segments are dropped."""
    return float(getattr(segment, 'no_speech_prob', 0.0) or 0.0) > NO_SPEECH_LIMIT


def _decode_audio_compat(path: str):
    """Decode to 16 kHz mono float32 without faster-whisper's decoder.

    faster-whisper 1.2.x calls av.open(..., metadata_errors=...), which PyAV 19+ rejects with a TypeError.
    """
    import av
    import numpy as np
    from av.audio.resampler import AudioResampler
    resampler = AudioResampler(format='s16', layout='mono', rate=16000)
    chunks = []
    with av.open(str(path)) as container:
        stream = next(s for s in container.streams if s.type == 'audio')
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe_file(path: str, plan: Plan, language: Optional[str] = 'hu', hint: str = '',
                    progress: Optional[Callable[[float], None]] = None,
                    status: Optional[Callable[[str], None]] = None,
                    should_stop: Optional[Callable[[], bool]] = None) -> Tuple[List[Segment], Plan]:
    """Transcribe one audio file. Returns (segments, plan actually used).

    A GPU that cannot be used (missing CUDA libraries, out of memory) silently becomes a CPU run;
    the returned plan tells the caller what happened.
    """
    global _cuda_broken
    language = normalize_language(language)
    cpu_plan = Plan(plan.model, 'cpu', 'int8')
    attempts = [plan] if plan.device == 'cpu' else [cpu_plan] if _cuda_broken else [plan, cpu_plan]
    last_error: Optional[Exception] = None
    for attempt in attempts:
        try:
            model = load_model(attempt, status)
            segments: List[Segment] = []

            audio = [str(path)]

            def start(vad: bool):
                def run():
                    return model.transcribe(
                        audio[0], language=language, beam_size=5, vad_filter=vad,
                        vad_parameters={'min_silence_duration_ms': 500} if vad else None,
                        condition_on_previous_text=False,  # avoids repeated-text loops in long recordings
                        initial_prompt=hint or None,
                    )
                try:
                    return run()
                except TypeError as e:
                    if 'metadata_errors' not in str(e) or not isinstance(audio[0], str):
                        raise
                    logger.warning("PyAV is too new for faster-whisper's decoder; decoding the audio directly")
                    audio[0] = _decode_audio_compat(path)
                    return run()
            try:
                iterator, info = start(True)
            except Exception as vad_error:
                # the silence filter needs onnxruntime + its bundled model; speech still works without it
                logger.warning(f"Voice-activity filter unavailable ({vad_error}); transcribing without it")
                iterator, info = start(False)
            duration = max(float(getattr(info, 'duration', 0) or 0), 1.0)
            for seg in iterator:
                if should_stop and should_stop():
                    raise TranscriptionCancelled()
                text = (seg.text or '').strip()
                if text and is_probably_noise(seg):
                    logger.info(f"Dropped a segment that is probably not speech: {text!r}")
                elif text:
                    segments.append(Segment(float(seg.start), float(seg.end), text))
                if progress:
                    progress(min(float(seg.end) / duration, 1.0))
            return segments, attempt
        except TranscriptionCancelled:
            raise
        except Exception as e:
            last_error = e
            if attempt.device == 'cuda':
                _cuda_broken = True
                logger.warning(f"GPU transcription failed ({e}); falling back to the CPU")
                clear_cache()
                if status:
                    status("The GPU could not be used (missing CUDA libraries?). Continuing on the CPU, "
                           "which is slower.")
                continue
            raise
    raise RuntimeError(f"Transcription failed: {last_error}")
