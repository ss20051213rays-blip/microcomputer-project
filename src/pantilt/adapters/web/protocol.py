"""Web 前端与主控系统通信协议规范与数据传输对象 (DTO)。

纯领域数据传输对象与常量定义，具备零外部重型依赖，完全跨平台与自包含。
支持 REST API、Server-Sent Events (SSE) 及 WebSocket 序列化。
"""
from dataclasses import asdict, dataclass, field
from enum import Enum
import math
import json
import time
from typing import Any, Dict, List, Optional, Tuple


class WebRoutes:
    """REST 与流式通信路由常量表。"""

    # 静态前端资源
    STATIC_INDEX = "/"
    STATIC_FILES = "/static/"

    # 系统状态与全量遥测快照
    STATUS = "/api/status"
    TELEMETRY = "/api/telemetry"

    # 实时数据流 (SSE & MJPEG)
    STREAM_EVENTS = "/api/stream/events"
    STREAM_VIDEO = "/api/stream/video"

    # 云台与执行器控制
    CONTROL_SERVO = "/api/control/servo"
    CONTROL_CENTER = "/api/control/center"
    CONTROL_LASER = "/api/control/laser"
    CONTROL_MODE = "/api/control/mode"
    CONTROL_RESET = "/api/control/reset"

    # 配置管理与日志查询
    CONFIG = "/api/config"
    LOGS = "/api/logs"

    # 双向实时长连接备选
    WS = "/ws"


class ControlMode(str, Enum):
    """前端系统运行模式枚举。"""

    AUTO = "AUTO"                # 视听融合自主状态机跟踪
    MANUAL = "MANUAL"            # Web 操控台人工接管 (手柄/键盘)
    CALIBRATION = "CALIBRATION"  # 零点与限位标定模式


class EventStreamType(str, Enum):
    """SSE 事件推送分类枚举。"""

    TELEMETRY = "telemetry"      # 高频全量遥测快照 (20~30 Hz)
    ACOUSTIC = "acoustic"        # 突发声学检测事件
    STATE_CHANGE = "state_change"# 状态机转移事件
    ALERT = "alert"              # 安全联锁与异常告警
    LOG = "log"                  # 实时日志广播


@dataclass
class ServoTelemetryDTO:
    """舵机双轴状态遥测数据传输对象。"""

    yaw: float = 0.0             # 当前偏航角 (°，-90.0 ~ +90.0)
    pitch: float = 0.0           # 当前俯仰角 (°，-30.0 ~ +45.0)
    target_yaw: float = 0.0      # 目标偏航角 (°)
    target_pitch: float = 0.0    # 目标俯仰角 (°)
    min_yaw: float = -90.0
    max_yaw: float = 90.0
    min_pitch: float = -30.0
    max_pitch: float = 45.0
    driver_type: str = "bus"     # "bus" (串行总线) | "pwm" (硬件 PWM)
    torque_enabled: bool = True


@dataclass
class VisionTelemetryDTO:
    """视觉感知状态遥测数据传输对象。"""

    target_found: bool = False
    target_type: str = "none"    # "aruco" | "face" | "none"
    target_id: int = -1          # ArUco ID 或 -1
    dx_px: float = 0.0           # 水平像素中心偏差 (px)
    dy_px: float = 0.0           # 垂直像素中心偏差 (px)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0) # [x, y, w, h]
    confidence: float = 0.0
    fps: float = 0.0
    in_deadzone: bool = False
    age_s: float = 0.0           # 观测帧距今时延 (秒)


@dataclass
class AudioTelemetryDTO:
    """声学事件与监视状态遥测数据传输对象。"""

    event_detected: bool = False # 是否有最近声源事件
    theta_deg: float = 0.0       # 估计声源水平角 (°，负左正右)
    side: str = "none"           # "left" | "right" | "center" | "none"
    confidence: float = 0.0      # GCC-PHAT 互相关峰值置信度
    method: str = "none"         # "gcc_phat" | "energy_diff" | "none"
    energy_rms: float = 0.0      # 当前音频能量均方根值 (归一化 0~1)
    age_s: float = 999.0         # 距离上次事件时间差 (秒)


@dataclass
class LaserTelemetryDTO:
    """激光指示器状态遥测数据传输对象。"""

    is_on: bool = False          # 物理点亮状态
    continuous_s: float = 0.0    # 当前持续点亮时间 (秒)
    max_continuous_s: float = 10.0 # 安全过热超时保护阈值
    locked_frames: int = 0       # 准星死区连续锁定帧数
    lock_min_frames: int = 3     # 点亮所需最小锁定帧
    hardware_enabled: bool = True# 配置是否开启激光器


@dataclass
class SystemStatusDTO:
    """系统宏观健康度与模式状态数据传输对象。"""

    app_state: str = "IDLE"      # 领域状态机: "IDLE" | "TURN_ONCE" | "FOLLOW"
    control_mode: str = "AUTO"   # Web 运行模式: "AUTO" | "MANUAL" | "CALIBRATION"
    running: bool = False
    dry_run: bool = False
    uptime_s: float = 0.0
    main_loop_hz: float = 30.0
    version: str = "0.2.0"
    cpu_temp_c: Optional[float] = None


@dataclass
class TelemetryPacketDTO:
    """前端全量快照与 SSE 广播高频遥测数据包。"""

    timestamp_mono: float
    iso_time: str
    status: SystemStatusDTO
    servo: ServoTelemetryDTO
    vision: VisionTelemetryDTO
    audio: AudioTelemetryDTO
    laser: LaserTelemetryDTO

    def to_dict(self) -> Dict[str, Any]:
        """将数据包序列化为纯字典结构。"""
        return asdict(self)

    def to_json(self) -> str:
        """将数据包序列化为紧凑 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ServoControlCommand:
    """舵机人工控制指令请求体。"""

    mode: str = "step"           # "step" (增量微调) | "absolute" (绝对定位)
    delta_yaw: float = 0.0       # 水平步进 (°，mode="step" 生效)
    delta_pitch: float = 0.0     # 俯仰步进 (°，mode="step" 生效)
    yaw: Optional[float] = None  # 目标绝对偏航角 (°，mode="absolute" 生效)
    pitch: Optional[float] = None# 目标绝对俯仰角 (°，mode="absolute" 生效)

    def validate_and_clamp(
        self,
        min_yaw: float = -90.0,
        max_yaw: float = 90.0,
        min_pitch: float = -30.0,
        max_pitch: float = 45.0,
        current_yaw: float = 0.0,
        current_pitch: float = 0.0,
    ) -> Tuple[float, float]:
        """校验并计算在物理安全限位内的目标两轴角度 (target_yaw, target_pitch)。"""
        if self.mode == "absolute":
            target_yaw = self.yaw if self.yaw is not None else current_yaw
            target_pitch = self.pitch if self.pitch is not None else current_pitch
        else:  # step
            target_yaw = current_yaw + self.delta_yaw
            target_pitch = current_pitch + self.delta_pitch

        # 针对 NaN / Inf 异常数值的安全免疫回退
        if target_yaw is None or math.isnan(target_yaw) or math.isinf(target_yaw):
            target_yaw = current_yaw
        if target_pitch is None or math.isnan(target_pitch) or math.isinf(target_pitch):
            target_pitch = current_pitch

        clamped_yaw = max(min_yaw, min(max_yaw, float(target_yaw)))
        clamped_pitch = max(min_pitch, min(max_pitch, float(target_pitch)))
        return clamped_yaw, clamped_pitch


@dataclass
class LaserControlCommand:
    """激光器人工控制指令请求体。"""

    enable: bool
    force_override: bool = False # 是否越过死区锁定计数强制点亮 (受限时保护)


@dataclass
class ModeSwitchCommand:
    """系统运行模式切换指令请求体。"""

    mode: str                    # "AUTO" | "MANUAL" | "CALIBRATION"


@dataclass
class ConfigUpdateCommand:
    """运行时参数动态更新指令请求体。"""

    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LogEntryDTO:
    """实时推送与查询的单条日志数据传输对象。"""

    timestamp: float
    iso_time: str
    level: str                   # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    logger: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def create_sse_frame(event: str, data: Any, event_id: Optional[int] = None) -> str:
    """构造标准 Server-Sent Events (SSE) 传输文本块。

    格式规范：
    id: <event_id>
    event: <event_name>
    data: <json_string>
    \\n\\n
    """
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


__all__ = [
    "WebRoutes",
    "ControlMode",
    "EventStreamType",
    "ServoTelemetryDTO",
    "VisionTelemetryDTO",
    "AudioTelemetryDTO",
    "LaserTelemetryDTO",
    "SystemStatusDTO",
    "TelemetryPacketDTO",
    "ServoControlCommand",
    "LaserControlCommand",
    "ModeSwitchCommand",
    "ConfigUpdateCommand",
    "LogEntryDTO",
    "create_sse_frame",
]
