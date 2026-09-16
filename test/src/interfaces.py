from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple


@dataclass
class AudioEvent:
    clap_detected: bool
    azimuth_deg: Optional[float]
    energy: float


@dataclass
class VisionEvent:
    face_found: bool
    dx_px: Optional[float]
    face_center_x: Optional[float]


class AudioSource(Protocol):
    def read(self) -> AudioEvent:
        """Return one audio analysis result."""


class VisionSource(Protocol):
    def read(self) -> VisionEvent:
        """Return one vision analysis result."""


class ServoDriver(Protocol):
    def get_angle(self) -> float:
        ...

    def set_angle(self, angle_deg: float) -> float:
        ...

    def center(self) -> float:
        ...
