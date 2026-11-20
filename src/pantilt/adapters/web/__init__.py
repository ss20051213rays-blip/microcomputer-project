"""Web 前端与通信适配器包。

提供轻量自包含 Web 运行时适配器、REST API 接口、SSE 遥测推流与 MJPEG 视频推流。
"""
from pantilt.adapters.web.protocol import (
    AudioTelemetryDTO,
    ConfigUpdateCommand,
    ControlMode,
    EventStreamType,
    LaserControlCommand,
    LaserTelemetryDTO,
    LogEntryDTO,
    ModeSwitchCommand,
    ServoControlCommand,
    ServoTelemetryDTO,
    SystemStatusDTO,
    TelemetryPacketDTO,
    VisionTelemetryDTO,
    WebRoutes,
    create_sse_frame,
)
from pantilt.adapters.web.server import (
    MockVideoGenerator,
    RingBufferLogHandler,
    WebRequestHandler,
    WebRuntimeAdapter,
)

__all__ = [
    "WebRoutes",
    "ControlMode",
    "EventStreamType",
    "ServoTelemetryDTO",
    "VisionTelemetryDTO",
    "AudioTelemetryDTO",
    "LaserTelemetryDTO",
    "TelemetryPacketDTO",
    "SystemStatusDTO",
    "ServoControlCommand",
    "LaserControlCommand",
    "ModeSwitchCommand",
    "ConfigUpdateCommand",
    "LogEntryDTO",
    "create_sse_frame",
    "RingBufferLogHandler",
    "MockVideoGenerator",
    "WebRequestHandler",
    "WebRuntimeAdapter",
]
