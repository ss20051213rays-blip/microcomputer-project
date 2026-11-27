from types import SimpleNamespace

import numpy as np

from pantilt.adapters.perception.audio import AudioPipeline, SpeechDirection
from pantilt.adapters.perception import wakeup as wakeup_module


class FakeRecognizer:
    def __init__(self, keyword="小爱同学"):
        self.keyword = keyword
        self.accepted = 0
        self.resets = 0

    def accept(self, block):
        self.accepted += 1
        return self.keyword

    def reset(self):
        self.resets += 1


def _pipeline():
    return AudioPipeline({
        "sample_rate": 16000,
        "channels": 2,
        "blocksize": 1024,
        "fallback_angle_deg": 30.0,
        "wakeup": {"enabled": True},
        "speaker": {"enabled": False},
    })


def test_wakeup_hit_queues_measured_direction(monkeypatch):
    audio = _pipeline()
    recognizer = FakeRecognizer()
    audio.wakeup_active = True
    audio.wakeup_recognizer = recognizer
    audio.estimate_speech_direction = lambda pcm: SpeechDirection(
        -28.5, -70e-6, "left", 0.82, "gcc_phat", 12, 10
    )
    block = np.full((1024, 2), 1000, dtype=np.int16)

    audio._process_wakeup_block(block, 123.0)

    event = audio.get_latest_event()
    assert event is not None
    assert event.timestamp_mono == 123.0
    assert event.theta_audio_deg == -28.5
    assert event.side == "left"
    assert event.method == "gcc_phat"
    assert recognizer.accepted == 1
    assert not audio._speech_history


def test_wakeup_hit_uses_fixed_side_fallback_when_doa_is_uncertain():
    audio = _pipeline()
    audio.wakeup_active = True
    audio.wakeup_recognizer = FakeRecognizer()
    audio.estimate_speech_direction = lambda pcm: SpeechDirection(
        None, None, "right", 0.2, "energy_diff", 12, 1
    )

    audio._process_wakeup_block(np.zeros((1024, 2), dtype=np.int16), 10.0)

    event = audio.get_latest_event()
    assert event is not None
    assert event.theta_audio_deg == 30.0
    assert event.side == "right"
    assert event.method == "energy_diff"


def test_wakeup_is_reset_and_suppressed_outside_idle():
    audio = _pipeline()
    recognizer = FakeRecognizer()
    audio.wakeup_active = True
    audio.wakeup_recognizer = recognizer
    audio.set_wakeup_listening(False)
    block = np.zeros((1024, 2), dtype=np.int16)

    audio._process_wakeup_block(block, 10.0)
    audio._process_wakeup_block(block, 10.1)

    assert recognizer.resets == 1
    assert recognizer.accepted == 0
    assert audio.get_latest_event() is None


def test_wakeup_initialization_failure_keeps_sed_fallback(monkeypatch):
    audio = _pipeline()

    def unavailable(*args, **kwargs):
        raise ImportError("sherpa-onnx unavailable")

    monkeypatch.setattr("pantilt.adapters.perception.audio.WakeWordRecognizer", unavailable)
    audio._initialize_wakeup()

    assert audio.wakeup_active is False
    assert audio.wakeup_recognizer is None


def test_wakeword_recognizer_feeds_mono_and_resets_after_hit(tmp_path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in (
        "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "tokens.txt",
    ):
        (model_dir / name).touch()
    keywords_file = tmp_path / "keywords.txt"
    keywords_file.write_text("x iǎo ài t óng x ué @小爱同学\n", encoding="utf-8")

    class FakeStream:
        ready = False
        samples = None

        def accept_waveform(self, sample_rate, samples):
            assert sample_rate == 16000
            self.samples = samples
            self.ready = True

    class FakeSpotter:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.stream = FakeStream()
            self.reset_count = 0

        def create_stream(self):
            return self.stream

        def is_ready(self, stream):
            return stream.ready

        def decode_stream(self, stream):
            stream.ready = False

        def get_result(self, stream):
            return "小爱同学"

        def reset_stream(self, stream):
            self.reset_count += 1

    fake_spotter = FakeSpotter()
    monkeypatch.setitem(
        __import__("sys").modules,
        "sherpa_onnx",
        SimpleNamespace(KeywordSpotter=lambda **kwargs: fake_spotter),
    )
    recognizer = wakeup_module.WakeWordRecognizer(
        {"model_dir": str(model_dir), "keywords_file": str(keywords_file), "input_gain": 4.0},
        16000,
    )

    assert recognizer.accept(np.full((1024, 2), 1000, dtype=np.int16)) == "小爱同学"
    assert fake_spotter.stream.samples.shape == (1024,)
    assert np.isclose(fake_spotter.stream.samples[0], 1000 / 32768 * 4)
    assert fake_spotter.reset_count == 1
