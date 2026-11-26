"""跨层共享核心类型定义 (零硬件与第三方依赖)。"""
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class SystemState(str, Enum):
    """阶段 4 的四态视听跟踪流程。"""
    IDLE = "IDLE"
    TURN_AND_RESPOND = "TURN_AND_RESPOND"
    SEARCH_FACE = "SEARCH_FACE"
    TRACK_FACE = "TRACK_FACE"

    # 旧名称保留为 Enum alias，便于尚未迁移的外围调用代码平滑过渡。
    TURN_ONCE = "TURN_AND_RESPOND"
    FOLLOW = "TRACK_FACE"


@dataclass
class AudioEvent:
    """声学触发事件与测向估计数据包。"""
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
    dy_px: float = 0.0
    target_id: int = -1

    @property
    def target_found(self) -> bool:
        """目标存在别名。"""
        return self.face_found


__all__ = ["SystemState", "AudioEvent", "VisionObservation"]
