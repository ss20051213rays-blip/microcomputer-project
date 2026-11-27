"""Thin adapter for the optional sherpa-onnx keyword spotter."""
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from pantilt.infrastructure.paths import resolve_path


class WakeWordRecognizer:
    """Feed synchronized stereo PCM to a sherpa-onnx keyword spotter."""

    def __init__(self, config: Dict[str, Any], sample_rate: int):
        if sample_rate != 16000:
            raise ValueError("Wake-word recognition currently requires 16 kHz audio")

        model_dir = self._resolve(config.get("model_dir", ""))
        keywords_file = self._resolve(config.get("keywords_file", "configs/kws_wenetspeech.txt"))
        model_paths = {
            "encoder": model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
            "decoder": model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
            "joiner": model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
            "tokens": model_dir / "tokens.txt",
            "keywords_file": keywords_file,
        }
        missing = [path for path in model_paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Wake-word model files missing: {', '.join(map(str, missing))}")

        import sherpa_onnx

        self.sample_rate = sample_rate
        self.input_gain = float(config.get("input_gain", 4.0))
        self.spotter = sherpa_onnx.KeywordSpotter(
            **{name: str(path) for name, path in model_paths.items()},
            sample_rate=sample_rate,
            num_threads=int(config.get("num_threads", 1)),
            max_active_paths=int(config.get("max_active_paths", 4)),
            keywords_threshold=float(config.get("threshold", 0.15)),
            keywords_score=float(config.get("score", 1.5)),
            provider=str(config.get("provider", "cpu")),
        )
        self.stream = self.spotter.create_stream()

    @staticmethod
    def _resolve(value: Any) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else resolve_path(path)

    def accept(self, stereo_pcm: np.ndarray) -> Optional[str]:
        """Return the matched keyword, if any, for one int16 stereo block."""
        if stereo_pcm.ndim != 2 or stereo_pcm.shape[1] != 2:
            raise ValueError("Wake-word input must be stereo PCM")
        mono = stereo_pcm.mean(axis=1, dtype=np.float32) / 32768.0
        if self.input_gain != 1.0:
            mono *= self.input_gain
            np.clip(mono, -1.0, 1.0, out=mono)
        self.stream.accept_waveform(self.sample_rate, mono)
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            if keyword := self.spotter.get_result(self.stream):
                self.reset()
                return keyword
        return None

    def reset(self) -> None:
        self.spotter.reset_stream(self.stream)


__all__ = ["WakeWordRecognizer"]
