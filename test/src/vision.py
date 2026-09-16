from __future__ import annotations

from typing import List, Optional, Sequence

from .config import AppConfig
from .interfaces import VisionEvent


class FaceTracker:
    """Convert a face center x into dx relative to image center."""

    def __init__(self, config: AppConfig):
        self.config = config

    def process(self, face_center_x: Optional[float]) -> VisionEvent:
        if face_center_x is None:
            return VisionEvent(face_found=False, dx_px=None, face_center_x=None)
        dx = float(face_center_x) - self.config.image_center_x
        return VisionEvent(face_found=True, dx_px=dx, face_center_x=float(face_center_x))


class MockVisionSource:
    """Offline vision source driven by a scripted face trajectory."""

    def __init__(self, config: AppConfig, script: Optional[Sequence[dict]] = None):
        self.config = config
        self.tracker = FaceTracker(config)
        self.script: List[dict] = list(script or [])
        self.t = 0.0
        self.dt = 1.0 / max(1, config.control_hz)
        self._cursor = 0
        self._current_x: Optional[float] = None

    def read(self) -> VisionEvent:
        self.t += self.dt
        while self._cursor < len(self.script) and self.t >= float(self.script[self._cursor]["t"]):
            self._current_x = self.script[self._cursor].get("face_x")
            self._cursor += 1
        return self.tracker.process(self._current_x)
