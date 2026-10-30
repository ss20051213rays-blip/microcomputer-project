"""跨层共享核心类型定义 (零硬件与第三方依赖)。"""
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class SystemState(str, Enum):
    """视听融合云台运行状态机枚举。"""
    IDLE = "IDLE"
    TURN_ONCE = "TURN_ONCE"
    FOLLOW = "FOLLOW"


@dataclass
class AudioEvent:
    """声学事件检测与测向估计数据包。"""
    timestamp_mono: float
    theta_audio_deg: float
    side: str          # "left", "right", "center"
    confidence: float
    method: str        # "gcc_phat" or "energy_diff"


@dataclass
class VisionObservation:
    """视觉帧检测与空间偏差观测数据包。"""
    timestamp_mono: float
    face_found: bool
    dx_px: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    confidence: float
    fps: float
    dy_px: float = 0.0               # 俯仰垂直偏差 (像素)
    target_id: int = -1              # 检出的目标 ID (如 ArUco 标记 ID)

    @property
    def target_found(self) -> bool:
        """目标存在别名（兼容 ArUco 靶标与人脸）。"""
        return self.face_found


__all__ = ["SystemState", "AudioEvent", "VisionObservation"]

