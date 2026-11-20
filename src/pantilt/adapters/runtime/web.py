"""轻量 Web 运行时服务适配器 (src/pantilt/adapters/runtime/web.py)。

负责 Web 监控中心与实况 HUD 运行时的生命周期管理与线程调度。
提供系统实时状态查询、MJPEG/Canvas 视频流、双轴云台控制、声学事件、激光开关、模式配置更新及实时日志流接口。
"""
import logging
from typing import Any, Dict, Optional

from pantilt.adapters.web.server import (
    MockVideoGenerator,
    RingBufferLogHandler,
    ThreadedHTTPServer,
    WebRequestHandler,
    WebRuntimeAdapter,
)

logger = logging.getLogger("App")


class WebRuntimeServer(WebRuntimeAdapter):
    """Web 运行时服务（支持无缝集成至应用主生命周期）。"""

    def __init__(self, app: Optional[Any] = None, config: Optional[Dict[str, Any]] = None):
        super().__init__(app=app, config=config)


# 别名兼容
WebAdapter = WebRuntimeServer

__all__ = [
    "WebRuntimeServer",
    "WebAdapter",
    "RingBufferLogHandler",
    "MockVideoGenerator",
    "ThreadedHTTPServer",
    "WebRequestHandler",
]
