from spette import local_stt
from spette.local_stt import Hardware, Plan


def test_normalizers():
    assert local_stt.normalize_model_name("large") == "large-v3"
    assert local_stt.normalize_model_name("nonsense") == "small"
    assert local_stt.normalize_language("hu-HU") == "hu"
    assert local_stt.normalize_language("auto") is None and local_stt.normalize_language("") is None


def test_recommend_and_resolve_plans():
    cpu = Hardware(cpu_threads=8)
    big = Hardware(gpu_name="X", vram_mb=8192, cuda_available=True, cpu_threads=8)
    assert local_stt.recommend(cpu) == Plan("small", "cpu", "int8")
    assert local_stt.recommend(Hardware(cpu_threads=2)) == Plan("base", "cpu", "int8")
    assert local_stt.recommend(big) == Plan("large-v3", "cuda", "float16")
    assert local_stt.resolve_plan("auto", "auto", big).model == "large-v3"
    assert local_stt.resolve_plan("medium", "cpu", big) == Plan("medium", "cpu", "int8")
    assert local_stt.resolve_plan("medium", "auto", cpu) == Plan("medium", "cpu", "int8")   # no usable GPU


def test_is_downloaded_looks_for_model_bin(data_dir):
    assert not local_stt.is_downloaded("small")
    snapshot = local_stt.models_dir() / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"x")
    assert local_stt.is_downloaded("small") and not local_stt.is_downloaded("medium")
    assert str(local_stt.models_dir()).startswith(str(data_dir))   # SpeTte keeps its own models


def test_segments_that_whisper_rates_as_not_speech_are_dropped():
    from types import SimpleNamespace as Seg
    assert local_stt.is_probably_noise(Seg(no_speech_prob=0.9))             # "köszönöm szépen" on a noisy silence
    assert not local_stt.is_probably_noise(Seg(no_speech_prob=0.1))         # real speech
    assert not local_stt.is_probably_noise(Seg(text="x"))                   # no estimate: keep the text
