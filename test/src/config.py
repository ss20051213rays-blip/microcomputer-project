from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import json


@dataclass
class AppConfig:
    sample_rate: int = 16000
    frame_ms: int = 64
    clap_energy_threshold: float = 0.35
    clap_cooldown_s: float = 1.0
    mic_distance_m: float = 0.06
    speed_of_sound: float = 343.0

    camera_width: int = 640
    camera_height: int = 480
    face_lost_timeout_s: float = 2.0
    follow_deadzone_px: int = 40
    follow_step_deg: float = 2.0

    servo_min_deg: float = -60.0
    servo_max_deg: float = 60.0
    servo_center_deg: float = 0.0
    turn_tolerance_deg: float = 2.0
    turn_timeout_s: float = 2.0
    control_hz: int = 30

    mode: str = "mock"

    @property
    def frame_samples(self) -> int:
        return max(1, int(self.sample_rate * self.frame_ms / 1000))

    @property
    def image_center_x(self) -> float:
        return self.camera_width / 2.0


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Minimal YAML subset parser: key: value lines only."""
    data: Dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
            continue
        try:
            if "." in value or "e" in value.lower():
                data[key] = float(value)
            else:
                data[key] = int(value)
            continue
        except ValueError:
            data[key] = value
    return data


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        path = Path(__file__).resolve().parents[1] / "configs" / "default.yaml"
    path = Path(path)
    if not path.exists():
        return cfg

    raw = _parse_simple_yaml(path.read_text(encoding="utf-8"))
    for key, value in raw.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def dumps_config(cfg: AppConfig) -> str:
    return json.dumps(cfg.__dict__, ensure_ascii=False, indent=2)
