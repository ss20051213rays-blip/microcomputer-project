"""核心基础设施子包（配置、日志、路径、共享类型）。"""
from pantilt.core.config import load_config
from pantilt.core.logging_setup import setup_logger
from pantilt.core.paths import DEFAULT_CONFIG, PROJECT_ROOT, resolve_path
from pantilt.core.types import AudioEvent, SystemState, VisionObservation

__all__ = [
    "load_config",
    "setup_logger",
    "PROJECT_ROOT",
    "DEFAULT_CONFIG",
    "resolve_path",
    "SystemState",
    "AudioEvent",
    "VisionObservation",
]
