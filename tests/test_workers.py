import pytest

from spette import local_stt
from spette.workers import TranscriptionWorker, describe_error


class FakeAudio:
    def get_wav_data(self):
        return b"RIFF" + b"\0" * 64000


def _run(worker):
    results, errors = [], []
    worker.result_ready.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()                      # synchronously, without starting a thread
    return results, errors


def test_local_transcription_joins_segments(app, monkeypatch):
    plan = local_stt.Plan("small", "cpu", "int8")
    monkeypatch.setattr(local_stt, "resolve_plan", lambda model, device: plan)
    monkeypatch.setattr(local_stt, "transcribe_file", lambda path, p, language=None, status=None, **kw: (
        [local_stt.Segment(0, 1, "Hello"), local_stt.Segment(1, 2, "world")], p))
    results, errors = _run(TranscriptionWorker(FakeAudio(), "whisper", "en-US"))
    assert results == ["Hello world"] and errors == []


def test_local_runtime_errors_are_shown_as_they_are(app, monkeypatch):
    monkeypatch.setattr(local_stt, "resolve_plan", lambda model, device: local_stt.Plan("small", "cpu", "int8"))

    def boom(*args, **kwargs):
        raise RuntimeError("faster-whisper is not installed in this build.")
    monkeypatch.setattr(local_stt, "transcribe_file", boom)
    results, errors = _run(TranscriptionWorker(FakeAudio(), "whisper", "en-US"))
    assert results == [] and errors == ["faster-whisper is not installed in this build."]


def test_unexpected_errors_get_a_readable_reason(app, monkeypatch):
    monkeypatch.setattr(local_stt, "resolve_plan", lambda model, device: local_stt.Plan("small", "cpu", "int8"))
    monkeypatch.setattr(local_stt, "transcribe_file",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("connection reset by huggingface")))
    results, errors = _run(TranscriptionWorker(FakeAudio(), "whisper", "en-US"))
    assert "could not be downloaded" in errors[0]


@pytest.mark.parametrize("text,fragment", [("CUDA out of memory", "graphics card"), ("odd", "odd")])
def test_describe_error(text, fragment):
    assert fragment in describe_error(RuntimeError(text))
