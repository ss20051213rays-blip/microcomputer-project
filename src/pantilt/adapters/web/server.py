"""轻量高性能 Web 运行时服务与通信适配器。

采用 Python 标准库 ThreadingHTTPServer 实现零外部依赖 Web 适配器：
1. 静态前端资源分发 (/) 与 (/static/*)
2. 完整 REST API (/api/status, /api/telemetry, /api/control/*, /api/config, /api/logs)
3. 20~30Hz Server-Sent Events (SSE) 持续事件推流 (/api/stream/events)
4. MJPEG Multipart 实时视频流与脱机高拟真战术合成画面 (/api/stream/video)
5. 环形缓冲日志记录器 (RingBufferLogHandler) 与实时日志广播
"""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import http.server
import json
import logging
import math
import mimetypes
import os
import socket
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.parse

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

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

logger = logging.getLogger("App")


class RingBufferLogHandler(logging.Handler):
    """线程安全的内存环形缓冲日志 Handler，支持历史查询与实时 SSE 广播订阅。"""

    def __init__(self, max_records: int = 200):
        super().__init__()
        self.max_records = max_records
        self.buffer: deque = deque(maxlen=max_records)
        self._buf_lock = threading.RLock()
        self.listeners: Set[Callable[[LogEntryDTO], None]] = set()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = LogEntryDTO(
                timestamp=record.created,
                iso_time=datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                level=record.levelname,
                logger=record.name,
                message=msg,
            )
            with self._buf_lock:
                self.buffer.append(entry)
                current_listeners = list(self.listeners)

            for cb in current_listeners:
                try:
                    cb(entry)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

    def get_entries(self, limit: int = 50) -> List[LogEntryDTO]:
        with self._buf_lock:
            items = list(self.buffer)
        if limit > 0 and len(items) > limit:
            return items[-limit:]
        return items

    def subscribe(self, callback: Callable[[LogEntryDTO], None]):
        with self._buf_lock:
            self.listeners.add(callback)

    def unsubscribe(self, callback: Callable[[LogEntryDTO], None]):
        with self._buf_lock:
            self.listeners.discard(callback)


class MockVideoGenerator:
    """脱机高拟真战术 HUD 图像生成器。

    当 OV9281 相机不可用或在 dry_run 模式下时，生成带有动态正弦移动 ArUco 靶标、
    十字瞄准准星、偏差向量与战术网格背景的 640x400 合成图像，零硬件依赖可直接验证。
    """

    def __init__(self, width: int = 640, height: int = 400):
        self.width = width
        self.height = height

    def generate_frame(
        self,
        app: Optional[Any] = None,
        draw_hud: bool = False,
        quality: int = 75,
    ) -> bytes:
        if cv2 is None or np is None:
            # 极简保底无 OpenCV 环境占位单帧 (最小有效 JPEG)
            return (
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
                b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
                b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
                b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
                b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
            )

        t = time.monotonic()
        w, h = self.width, self.height

        # 战术暗黑底色 (深灰青: B=20, G=16, R=12)
        frame = np.full((h, w, 3), (20, 16, 12), dtype=np.uint8)

        # 战术网格线 (每 40px 一道细线)
        grid_color = (35, 28, 22)
        for x in range(0, w, 40):
            cv2.line(frame, (x, 0), (x, h), grid_color, 1)
        for y in range(0, h, 40):
            cv2.line(frame, (0, y), (w, y), grid_color, 1)

        # 动态正弦波运动的模拟目标中心 (tx, ty)
        cx, cy = w // 2, h // 2
        obs = getattr(app, "last_vision_obs", None) if app else None

        if obs and obs.face_found:
            tx = int(cx + obs.dx_px)
            ty = int(cy + getattr(obs, "dy_px", 0.0))
            target_id = getattr(obs, "target_id", 12)
        else:
            tx = int(cx + 140 * math.sin(t * 0.8))
            ty = int(cy + 60 * math.cos(t * 1.1))
            target_id = 12

        # 绘制目标识别框 (荧光绿 #00ff9d -> BGR: 157, 255, 0)
        bw, bh = 54, 54
        x1, y1 = max(4, tx - bw // 2), max(4, ty - bh // 2)
        x2, y2 = min(w - 4, tx + bw // 2), min(h - 4, ty + bh // 2)
        color_box = (157, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color_box, 2)

        # 目标四个角点战术括号标记
        bracket_len = 10
        cv2.line(frame, (x1, y1), (x1 + bracket_len, y1), (0, 255, 255), 2)
        cv2.line(frame, (x1, y1), (x1, y1 + bracket_len), (0, 255, 255), 2)
        cv2.line(frame, (x2, y1), (x2 - bracket_len, y1), (0, 255, 255), 2)
        cv2.line(frame, (x2, y1), (x2, y1 + bracket_len), (0, 255, 255), 2)
        cv2.line(frame, (x1, y2), (x1 + bracket_len, y2), (0, 255, 255), 2)
        cv2.line(frame, (x1, y2), (x1, y2 - bracket_len), (0, 255, 255), 2)
        cv2.line(frame, (x2, y2), (x2 - bracket_len, y2), (0, 255, 255), 2)
        cv2.line(frame, (x2, y2), (x2, y2 - bracket_len), (0, 255, 255), 2)

        label = f"ArUco #{target_id} [SIM]"
        cv2.putText(
            frame,
            label,
            (x1, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color_box,
            1,
            cv2.LINE_AA,
        )

        # 绘制中心十字瞄准准星
        cv2.circle(frame, (cx, cy), 20, (75, 75, 75), 1, cv2.LINE_AA)
        cv2.line(frame, (cx - 30, cy), (cx - 6, cy), (100, 100, 100), 1)
        cv2.line(frame, (cx + 6, cy), (cx + 30, cy), (100, 100, 100), 1)
        cv2.line(frame, (cx, cy - 30), (cx, cy - 6), (100, 100, 100), 1)
        cv2.line(frame, (cx, cy + 6), (cx, cy + 30), (100, 100, 100), 1)

        # 偏差引导向量 (靶心至目标中心, 战术琥珀橙 BGR: 0, 170, 255)
        cv2.line(frame, (cx, cy), (tx, ty), (0, 170, 255), 1, cv2.LINE_AA)

        # 顶部时间码与脱机水印
        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        laser_on = bool(app.laser_is_on) if (app and hasattr(app, "laser_is_on")) else False
        mode_str = getattr(app, "control_mode", "AUTO") if app else "AUTO"
        state_str = app.state.value if (app and hasattr(app, "state")) else "IDLE"

        info_header = f"TACTICAL MOCK 120FPS | {time_str} | MODE: {mode_str} | STATE: {state_str}"
        cv2.putText(
            frame,
            info_header,
            (16, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (140, 160, 170),
            1,
            cv2.LINE_AA,
        )

        # 激光激活指示
        if laser_on:
            cv2.putText(
                frame,
                "● LASER ARMED 50mW",
                (w - 200, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (60, 60, 255),
                2,
                cv2.LINE_AA,
            )

        if draw_hud:
            yaw = app.servo.current_yaw if (app and hasattr(app, "servo")) else 0.0
            pitch = app.servo.current_pitch if (app and hasattr(app, "servo")) else 0.0
            hud_telemetry = f"YAW: {yaw:+.1f} deg | PITCH: {pitch:+.1f} deg | DX: {tx - cx:+d}px DY: {ty - cy:+d}px"
            cv2.putText(
                frame,
                hud_telemetry,
                (16, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (0, 243, 255),
                1,
                cv2.LINE_AA,
            )

        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        if not ret:
            return b""
        return bytes(buf)


class WebRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP / SSE / MJPEG 统一请求分发处理器。"""

    server_version = "PanTiltWebHUD/1.0"

    def log_message(self, format: str, *args: Any):
        """将 HTTP 访问日志重定向至 logger.debug，避免干扰主控制台。"""
        logger.debug(f"[WebHTTP] {self.address_string()} - " + (format % args))

    @property
    def adapter(self) -> "WebRuntimeAdapter":
        return getattr(self.server, "adapter")

    def _send_cors_headers(self):
        if self.adapter.cors_enabled:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-Requested-With",
            )

    def do_OPTIONS(self):
        """处理跨域 CORS 预检请求。"""
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, code: int, data: Any, message: str = "success"):
        """统一 JSON 响应封装。"""
        payload = {"code": code, "data": data, "message": message}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, code: int, message: str):
        self._send_json(code=code, data=None, message=message)

    # ── GET 请求分发 ──────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. 静态资源路由 (/) 与 (/static/*)
        if path == WebRoutes.STATIC_INDEX or path == "/index.html":
            self._handle_static_index()
            return
        if path.startswith(WebRoutes.STATIC_FILES):
            self._handle_static_file(path[len(WebRoutes.STATIC_FILES):])
            return

        # 2. 系统宏观状态查询 (/api/status)
        if path == WebRoutes.STATUS:
            telemetry = self.adapter.build_telemetry()
            self._send_json(200, asdict(telemetry.status))
            return

        # 3. 全量遥测快照 (/api/telemetry)
        if path == WebRoutes.TELEMETRY:
            telemetry = self.adapter.build_telemetry()
            self._send_json(200, telemetry.to_dict())
            return

        # 4. 控制参数查询 (/api/config)
        if path == WebRoutes.CONFIG:
            cfg = self.adapter.get_config_dict()
            self._send_json(200, cfg)
            return

        # 5. 系统环形日志查询 (/api/logs)
        if path == WebRoutes.LOGS:
            limit = 50
            if "limit" in query:
                try:
                    limit = max(1, min(200, int(query["limit"][0])))
                except ValueError:
                    pass
            entries = self.adapter.log_handler.get_entries(limit=limit)
            self._send_json(200, [e.to_dict() for e in entries])
            return

        # 6. SSE 持续事件流 (/api/stream/events)
        if path == WebRoutes.STREAM_EVENTS:
            self._handle_sse_stream()
            return

        # 7. MJPEG 实时视频流 (/api/stream/video)
        if path == WebRoutes.STREAM_VIDEO:
            raw_mode = query.get("raw", ["0"])[0] == "1"
            hud_mode = query.get("hud", ["0"])[0] == "1"
            draw_hud = hud_mode or (not raw_mode and False)
            self._handle_mjpeg_stream(draw_hud=draw_hud)
            return

        self._send_error_json(404, f"API 路由未找到: {path}")

    # ── POST 请求分发 ─────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
        except Exception as e:
            self._send_error_json(400, f"无效的 JSON 请求体: {e}")
            return

        app = self.adapter.app

        # 1. 双轴舵机人工控制 (/api/control/servo)
        if path == WebRoutes.CONTROL_SERVO:
            try:
                def _parse_finite_float(val: Any, default: Optional[float] = None) -> Optional[float]:
                    if val is None:
                        return default
                    f_val = float(val)
                    if math.isnan(f_val) or math.isinf(f_val):
                        raise ValueError(f"数值非法或非有限数: {val}")
                    return f_val

                cmd = ServoControlCommand(
                    mode=body.get("mode", "step"),
                    delta_yaw=_parse_finite_float(body.get("delta_yaw"), 0.0),
                    delta_pitch=_parse_finite_float(body.get("delta_pitch"), 0.0),
                    yaw=_parse_finite_float(body.get("yaw")) if "yaw" in body else None,
                    pitch=_parse_finite_float(body.get("pitch")) if "pitch" in body else None,
                )
            except Exception as e:
                self._send_error_json(400, f"舵机控制参数非法: {e}")
                return

            applied_yaw, applied_pitch, clamped = self.adapter.control_servo(cmd)
            self._send_json(
                200,
                {
                    "applied_yaw": applied_yaw,
                    "applied_pitch": applied_pitch,
                    "clamped": clamped,
                },
                message="Servo angles updated successfully.",
            )
            return

        # 2. 一键安全归中 (/api/control/center)
        if path == WebRoutes.CONTROL_CENTER:
            self.adapter.center_gimbal()
            self._send_json(200, {"yaw": 0.0, "pitch": 0.0}, message="Gimbal centered.")
            return

        # 3. 激光指示器开关控制 (/api/control/laser)
        if path == WebRoutes.CONTROL_LASER:
            enable = bool(body.get("enable", False))
            override = bool(body.get("force_override", False))
            cmd = LaserControlCommand(enable=enable, force_override=override)
            is_on, max_cont = self.adapter.control_laser(cmd)
            self._send_json(
                200,
                {"is_on": is_on, "max_continuous_s": max_cont},
                message="Laser updated successfully.",
            )
            return

        # 4. 运行模式切换 (/api/control/mode)
        if path == WebRoutes.CONTROL_MODE:
            mode = str(body.get("mode", "AUTO")).upper()
            if mode not in (ControlMode.AUTO.value, ControlMode.MANUAL.value, ControlMode.CALIBRATION.value):
                self._send_error_json(400, f"未知运行模式: {mode}，支持 AUTO, MANUAL, CALIBRATION")
                return
            applied_mode = self.adapter.set_mode(mode)
            self._send_json(200, {"mode": applied_mode}, message="Mode switched successfully.")
            return

        # 5. 状态机重置 (/api/control/reset)
        if path == WebRoutes.CONTROL_RESET:
            self.adapter.reset_system()
            self._send_json(200, {"app_state": "IDLE"}, message="State machine reset to IDLE.")
            return

        # 6. 控制参数热更 (/api/config)
        if path == WebRoutes.CONFIG:
            params = body.get("params", body)
            if not isinstance(params, dict):
                self._send_error_json(400, "参数格式错误，需为字典对象。")
                return
            cmd = ConfigUpdateCommand(params=params)
            updated = self.adapter.update_config(cmd.params)
            self._send_json(200, updated, message="Config updated successfully.")
            return

        self._send_error_json(404, f"POST 路由未找到: {path}")

    # ── 静态文件处理 ──────────────────────────────────────────────────────────
    def _handle_static_index(self):
        index_file = os.path.join(self.adapter.static_dir, "index.html")
        if os.path.isfile(index_file):
            self._serve_file(index_file, "text/html; charset=utf-8")
            return

        # 占位默认页 (当前端 static/index.html 尚未创建时)
        placeholder_html = (
            "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>视听融合两轴云台监控系统</title>"
            "<style>body{background:#0a0e14;color:#00ff9d;font-family:sans-serif;padding:40px;line-height:1.6;}"
            "a{color:#00f3ff;text-decoration:none;}h1{color:#00f3ff;border-bottom:1px solid #334;}code{color:#ffaa00;}</style></head>"
            "<body><h1>🎯 视听融合智能跟踪云台系统 · Web 监控中心</h1>"
            "<p>Web 运行时服务正常运行中。REST API、SSE 与 MJPEG 流已就绪。</p>"
            "<ul>"
            "<li><a href='/api/status'>GET /api/status (系统宏观状态)</a></li>"
            "<li><a href='/api/telemetry'>GET /api/telemetry (全量传感器与执行器遥测)</a></li>"
            "<li><a href='/api/stream/video?hud=1'>GET /api/stream/video (MJPEG 视频流)</a></li>"
            "<li><a href='/api/logs'>GET /api/logs (环形运行日志)</a></li>"
            "<li><a href='/api/config'>GET /api/config (控制阈值查询)</a></li>"
            "</ul></body></html>"
        )
        body = placeholder_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_static_file(self, rel_path: str):
        # 防路径遍历
        clean_rel = os.path.normpath(rel_path).lstrip(os.path.sep)
        file_path = os.path.join(self.adapter.static_dir, clean_rel)
        if not os.path.isfile(file_path):
            self._send_error_json(404, f"静态文件不存在: {rel_path}")
            return
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self._serve_file(file_path, content_type)

    def _serve_file(self, file_path: str, content_type: str):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_error_json(500, f"读取静态文件失败: {e}")

    # ── SSE 实时推流处理 ──────────────────────────────────────────────────────
    def _handle_sse_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._send_cors_headers()
        self.end_headers()

        log_queue: deque = deque(maxlen=20)
        log_lock = threading.Lock()

        def on_log_entry(entry: LogEntryDTO):
            with log_lock:
                log_queue.append(entry)

        self.adapter.log_handler.subscribe(on_log_entry)

        period = 1.0 / max(1.0, float(self.adapter.telemetry_hz))
        last_state = None
        last_audio_mono = 0.0

        try:
            # 建立时立即推送首帧遥测
            telemetry = self.adapter.build_telemetry()
            frame = create_sse_frame(EventStreamType.TELEMETRY.value, telemetry.to_dict())
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

            while self.adapter.running:
                t0 = time.monotonic()

                # 1. 周期全量遥测推送
                telemetry = self.adapter.build_telemetry()
                frame = create_sse_frame(EventStreamType.TELEMETRY.value, telemetry.to_dict())
                self.wfile.write(frame.encode("utf-8"))

                # 2. 状态机转移瞬时事件
                curr_state = telemetry.status.app_state
                if last_state is not None and curr_state != last_state:
                    state_payload = {
                        "from_state": last_state,
                        "to_state": curr_state,
                        "target_yaw": telemetry.servo.yaw,
                        "reason": f"State transition to {curr_state}",
                    }
                    self.wfile.write(
                        create_sse_frame(EventStreamType.STATE_CHANGE.value, state_payload).encode("utf-8")
                    )
                last_state = curr_state

                # 3. 突发声学事件
                app = self.adapter.app
                if app and app.last_audio_event:
                    if app.last_audio_event.timestamp_mono > last_audio_mono:
                        last_audio_mono = app.last_audio_event.timestamp_mono
                        ev = app.last_audio_event
                        ac_payload = {
                            "theta_deg": round(ev.theta_audio_deg, 1),
                            "side": ev.side,
                            "confidence": round(ev.confidence, 2),
                            "method": ev.method,
                            "rms": telemetry.audio.energy_rms,
                        }
                        self.wfile.write(
                            create_sse_frame(EventStreamType.ACOUSTIC.value, ac_payload).encode("utf-8")
                        )

                # 4. 实时日志广播事件
                pending_logs = []
                with log_lock:
                    while log_queue:
                        pending_logs.append(log_queue.popleft())

                for log_entry in pending_logs:
                    log_payload = {
                        "time": log_entry.iso_time.split(" ")[-1],
                        "level": log_entry.level,
                        "logger": log_entry.logger,
                        "message": log_entry.message,
                    }
                    self.wfile.write(
                        create_sse_frame(EventStreamType.LOG.value, log_payload).encode("utf-8")
                    )

                self.wfile.flush()

                # 控制推流周期
                elapsed = time.monotonic() - t0
                sleep_dur = period - elapsed
                if sleep_dur > 0:
                    time.sleep(sleep_dur)
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass
        finally:
            self.adapter.log_handler.unsubscribe(on_log_entry)

    # ── MJPEG 视频流处理 ──────────────────────────────────────────────────────
    def _handle_mjpeg_stream(self, draw_hud: bool = False):
        self.send_response(200)
        boundary = "frame"
        self.send_header(
            "Content-Type",
            f"multipart/x-mixed-replace; boundary={boundary}",
        )
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Connection", "close")
        self._send_cors_headers()
        self.end_headers()

        period = 1.0 / max(1.0, float(self.adapter.mjpeg_fps))

        try:
            while self.adapter.running:
                t0 = time.monotonic()
                jpg_bytes = self.adapter.get_video_frame(draw_hud=draw_hud)

                if jpg_bytes:
                    header = (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpg_bytes)}\r\n\r\n"
                    ).encode("utf-8")
                    self.wfile.write(header)
                    self.wfile.write(jpg_bytes)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                elapsed = time.monotonic() - t0
                sleep_dur = period - elapsed
                if sleep_dur > 0:
                    time.sleep(sleep_dur)
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass


class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    """支持 SO_REUSEADDR 与守护线程的多线程 HTTP 服务器。"""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass, adapter: "WebRuntimeAdapter"):
        self.adapter = adapter
        super().__init__(server_address, RequestHandlerClass)


class WebRuntimeAdapter:
    """轻量 Web 运行时适配器 (M7 Presentation/Runtime Adapter)。

    生命周期与 PanTiltTrackerApp 双向对齐：
    - 提供 REST API 交互与限位截断保护；
    - 管理 20~30Hz SSE 遥测推流与 MJPEG 视频流；
    - 脱机/真机自愈，支持无硬件干运行；
    - 内存环形日志缓冲并广播给前端控制台。
    """

    def __init__(self, app: Optional[Any] = None, config: Optional[Dict[str, Any]] = None):
        self.app = app
        self.config = config or {}

        self.host = str(self.config.get("host", "0.0.0.0"))
        self.port = int(self.config.get("port", 8080))
        self.telemetry_hz = float(self.config.get("telemetry_hz", 20.0))
        self.mjpeg_fps = float(self.config.get("mjpeg_fps", 30.0))
        self.mjpeg_quality = int(self.config.get("mjpeg_quality", 75))
        self.cors_enabled = bool(self.config.get("cors_enabled", True))

        # 静态文件根目录
        self.static_dir = os.path.join(os.path.dirname(__file__), "static")

        # 环形日志与脱机视频生成器
        self.log_handler = RingBufferLogHandler(max_records=200)
        self.mock_video = MockVideoGenerator(width=640, height=400)
        self._video_lock = threading.Lock()
        self._encoded_video = {}

        # 挂载日志处理器到主 Logger
        self.log_handler.setLevel(logging.DEBUG)
        self.log_handler.setFormatter(logging.Formatter("%(message)s"))
        app_logger = logging.getLogger("App")
        if app_logger.level == logging.NOTSET:
            app_logger.setLevel(logging.INFO)
        app_logger.addHandler(self.log_handler)

        self.server: Optional[ThreadedHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        self._lock = threading.Lock()

    def start(self) -> bool:
        """启动 Web 运行时 HTTP/SSE/MJPEG 监听服务。"""
        with self._lock:
            if self.running:
                return True

            try:
                self.server = ThreadedHTTPServer(
                    (self.host, self.port),
                    WebRequestHandler,
                    adapter=self,
                )
                self.running = True
                self.server_thread = threading.Thread(
                    target=self.server.serve_forever,
                    daemon=True,
                    name="PanTiltWebServerThread",
                )
                self.server_thread.start()
                logger.info(
                    f"🚀 Web 监控中心与实况 HUD 服务已启动: http://{self.host}:{self.port} "
                    f"(SSE @ {self.telemetry_hz}Hz, MJPEG @ {self.mjpeg_fps}FPS)"
                )
                return True
            except Exception as e:
                logger.error(f"启动 Web 运行时服务失败 (port={self.port}): {e}")
                self.running = False
                return False

    def stop(self):
        """安全停止 Web 运行时服务并释放端口与日志监听。"""
        with self._lock:
            if not self.running:
                return
            logger.info("正在停止 Web 运行时服务...")
            self.running = False
            if self.server:
                try:
                    self.server.shutdown()
                    self.server.server_close()
                except Exception as e:
                    logger.warning(f"关闭 Web Server 端口异常: {e}")
                self.server = None

            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=1.0)
                self.server_thread = None

            try:
                logging.getLogger("App").removeHandler(self.log_handler)
            except Exception:
                pass
            logger.info("Web 运行时服务已安全停止。")

    # ── 遥测快照与视频流生成辅助 ──────────────────────────────────────────────
    def build_telemetry(self) -> TelemetryPacketDTO:
        """构建全量系统与传感器/执行器遥测快照。"""
        now_mono = time.monotonic()
        iso_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        app = self.app

        # 1. 宏观健康度
        app_state = app.state.value if (app and hasattr(app, "state")) else "IDLE"
        control_mode = getattr(app, "control_mode", "AUTO") if app else "AUTO"
        running = app.running if (app and hasattr(app, "running")) else False
        dry_run = getattr(app, "dry_run", False) if app else False
        uptime = round(now_mono - getattr(app, "start_mono", now_mono), 2) if (app and running) else 0.0
        loop_hz = float(getattr(app, "main_loop_hz", 30.0)) if app else 30.0

        # CPU 温度探测 (Raspberry Pi / Linux thermal zone)
        cpu_temp = None
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    cpu_temp = round(int(f.read().strip()) / 1000.0, 1)
            except Exception:
                pass

        status_dto = SystemStatusDTO(
            app_state=app_state,
            control_mode=control_mode,
            running=running,
            dry_run=dry_run,
            uptime_s=uptime,
            main_loop_hz=loop_hz,
            version="0.2.0",
            cpu_temp_c=cpu_temp,
        )

        # 2. 舵机双轴遥测
        if app and hasattr(app, "servo"):
            s = app.servo
            yaw = round(float(s.current_yaw), 2)
            pitch = round(float(s.current_pitch), 2)
            servo_dto = ServoTelemetryDTO(
                yaw=yaw,
                pitch=pitch,
                target_yaw=yaw,
                target_pitch=pitch,
                min_yaw=float(s.min_yaw),
                max_yaw=float(s.max_yaw),
                min_pitch=float(s.min_pitch),
                max_pitch=float(s.max_pitch),
                driver_type=str(getattr(s, "driver_type", "bus")),
                torque_enabled=bool(running),
            )
        else:
            servo_dto = ServoTelemetryDTO()

        # 3. 视觉感知遥测
        obs = getattr(app, "last_vision_obs", None) if app else None
        current_target_mode = getattr(self, "_target_mode", None)
        if not current_target_mode and app and hasattr(app, "vision") and hasattr(app.vision, "config"):
            current_target_mode = app.vision.config.get("target_mode", "aruco")
        if not current_target_mode:
            current_target_mode = "aruco"

        if obs:
            target_found = bool(obs.face_found)
            target_id = getattr(obs, "target_id", -1)
            if target_id != -1:
                target_type = "aruco"
            elif target_found:
                target_type = str(current_target_mode).lower()
            else:
                target_type = "none"
            dx = round(float(obs.dx_px), 1)
            dy = round(float(getattr(obs, "dy_px", 0.0)), 1)
            bbox = tuple(int(v) for v in obs.bbox)
            conf = round(float(obs.confidence), 2)
            fps = round(float(obs.fps), 1)
            deadzone_x = getattr(app.controller, "deadzone_x", 30) if (app and hasattr(app, "controller")) else 30
            deadzone_y = getattr(app.controller, "deadzone_y", 25) if (app and hasattr(app, "controller")) else 25
            in_deadzone = target_found and (abs(dx) < deadzone_x) and (abs(dy) < deadzone_y)
            age = round(now_mono - float(obs.timestamp_mono), 3)

            vision_dto = VisionTelemetryDTO(
                target_found=target_found,
                target_type=target_type,
                target_id=target_id,
                dx_px=dx,
                dy_px=dy,
                bbox=bbox,
                confidence=conf,
                fps=fps,
                in_deadzone=in_deadzone,
                age_s=age,
            )
        else:
            vision_dto = VisionTelemetryDTO()

        # 4. 声学遥测
        audio_ev = getattr(app, "last_audio_event", None) if app else None
        latest_rms = round(float(getattr(app.audio, "latest_rms", 0.0)), 4) if (app and hasattr(app, "audio")) else 0.0
        if audio_ev:
            audio_dto = AudioTelemetryDTO(
                event_detected=True,
                theta_deg=round(float(audio_ev.theta_audio_deg), 1),
                side=str(audio_ev.side),
                confidence=round(float(audio_ev.confidence), 2),
                method=str(audio_ev.method),
                energy_rms=latest_rms,
                age_s=round(now_mono - float(audio_ev.timestamp_mono), 3),
            )
        else:
            audio_dto = AudioTelemetryDTO(energy_rms=latest_rms)

        # 5. 激光器遥测
        if app and hasattr(app, "laser"):
            l = app.laser
            is_on = bool(l.is_on)
            # 安全联锁主动巡检：若持续开启超时则自动触发过热保护切断
            if is_on and (now_mono - getattr(l, "on_start_mono", now_mono) > float(l.max_continuous_s)):
                l.set_laser(True, now_mono)
                is_on = bool(l.is_on)
            continuous = round(now_mono - getattr(l, "on_start_mono", now_mono), 2) if is_on else 0.0
            laser_dto = LaserTelemetryDTO(
                is_on=is_on,
                continuous_s=continuous,
                max_continuous_s=float(l.max_continuous_s),
                locked_frames=int(getattr(l, "locked_frames_count", 0)),
                lock_min_frames=int(l.lock_min_frames),
                hardware_enabled=bool(l.enabled),
            )
        else:
            laser_dto = LaserTelemetryDTO()

        return TelemetryPacketDTO(
            timestamp_mono=round(now_mono, 3),
            iso_time=iso_time,
            status=status_dto,
            servo=servo_dto,
            vision=vision_dto,
            audio=audio_dto,
            laser=laser_dto,
        )

    def get_video_frame(self, draw_hud: bool = False) -> bytes:
        """获取视频流单帧 JPEG 字节流（优先读取真实硬件相机，若无则使用高拟真战术合成画面）。"""
        app = self.app
        vision = getattr(app, "vision", None)
        if vision is not None and cv2 is not None:
            with self._video_lock:
                try:
                    if hasattr(vision, "get_latest_frame_sample"):
                        frame, captured_at = vision.get_latest_frame_sample()
                    else:
                        frame, captured_at = vision.get_latest_frame(), None
                except Exception:
                    frame, captured_at = None, None

                if frame is not None:
                    quality = self.mjpeg_quality
                    cache_key = (captured_at, quality)
                    cached_key, jpg = self._encoded_video.get(draw_hud, (None, None))
                    if captured_at is not None and cached_key == cache_key:
                        return jpg

                    if draw_hud:
                        frame = frame.copy()
                        h, w = frame.shape[:2]
                        cx, cy = w // 2, h // 2
                        cv2.circle(frame, (cx, cy), 18, (0, 255, 157), 1)
                        cv2.line(frame, (cx - 24, cy), (cx + 24, cy), (0, 255, 157), 1)
                        cv2.line(frame, (cx, cy - 24), (cx, cy + 24), (0, 255, 157), 1)

                    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    if ret:
                        jpg = bytes(buf)
                        if captured_at is not None:
                            self._encoded_video[draw_hud] = (cache_key, jpg)
                        return jpg

        # 脱机模拟合成图像
        return self.mock_video.generate_frame(
            app=app,
            draw_hud=draw_hud,
            quality=self.mjpeg_quality,
        )

    # ── 执行器控制与业务操作 ──────────────────────────────────────────────────
    def control_servo(self, cmd: ServoControlCommand) -> Tuple[float, float, bool]:
        """执行双轴伺服控制并限位保护截断。"""
        app = self.app
        if not app or not hasattr(app, "servo"):
            return 0.0, 0.0, False

        s = app.servo
        curr_yaw = float(s.current_yaw)
        curr_pitch = float(s.current_pitch)

        clamped_yaw, clamped_pitch = cmd.validate_and_clamp(
            min_yaw=s.min_yaw,
            max_yaw=s.max_yaw,
            min_pitch=s.min_pitch,
            max_pitch=s.max_pitch,
            current_yaw=curr_yaw,
            current_pitch=curr_pitch,
        )

        clamped = (
            abs(clamped_yaw - (cmd.yaw if cmd.mode == "absolute" and cmd.yaw is not None else curr_yaw + cmd.delta_yaw)) > 1e-4
            or abs(clamped_pitch - (cmd.pitch if cmd.mode == "absolute" and cmd.pitch is not None else curr_pitch + cmd.delta_pitch)) > 1e-4
        )

        # 人工介入：自动切换至 MANUAL 模式以防自主状态机覆盖
        if getattr(app, "control_mode", "AUTO") == "AUTO":
            app.set_control_mode("MANUAL")

        s.set_angles(yaw=clamped_yaw, pitch=clamped_pitch)
        return clamped_yaw, clamped_pitch, clamped

    def center_gimbal(self):
        """一键安全归中并重置状态机。"""
        if self.app:
            self.app.center()

    def control_laser(self, cmd: LaserControlCommand) -> Tuple[bool, float]:
        """手动点亮/熄灭激光瞄准器。"""
        if not self.app or not hasattr(self.app, "laser"):
            return False, 10.0

        laser = self.app.laser
        now = time.monotonic()
        if cmd.enable:
            laser.set_laser(True, now)
        else:
            laser.set_laser(False, now)

        return laser.is_on, float(laser.max_continuous_s)

    def set_mode(self, mode: str) -> str:
        """切换系统控制模式。"""
        if self.app:
            self.app.set_control_mode(mode)
            return self.app.control_mode
        return mode

    def reset_system(self):
        """重置状态机与执行器到初始 IDLE 态。"""
        if self.app:
            self.app.center()

    def get_config_dict(self) -> Dict[str, Any]:
        """查询运行时参数配置。"""
        app = self.app
        ctrl = getattr(app, "controller", None) if app else None
        sm = getattr(app, "state_machine", None) if app else None
        audio = getattr(app, "audio", None) if app else None
        vision = getattr(app, "vision", None) if app else None

        target_mode = getattr(self, "_target_mode", None)
        if not target_mode:
            if vision and hasattr(vision, "config") and "target_mode" in vision.config:
                target_mode = vision.config.get("target_mode", "aruco")
            elif vision and hasattr(vision, "detector") and vision.detector:
                target_mode = getattr(vision.detector, "target_mode", "aruco")
            else:
                target_mode = "aruco"

        return {
            "target_mode": str(target_mode).lower(),
            "deadzone_px_x": getattr(ctrl, "deadzone_x", 30) if ctrl else 30,
            "deadzone_px_y": getattr(ctrl, "deadzone_y", 25) if ctrl else 25,
            "step_deg_yaw": getattr(ctrl, "step_deg_yaw", 2.0) if ctrl else 2.0,
            "step_deg_pitch": getattr(ctrl, "step_deg_pitch", 1.5) if ctrl else 1.5,
            "lost_timeout_s": getattr(sm, "lost_timeout_s", 3.0) if sm else 3.0,
            "turn_settle_s": getattr(sm, "turn_settle_s", 0.3) if sm else 0.3,
            "energy_threshold": getattr(audio, "energy_threshold", 0.05) if audio else 0.05,
        }

    def update_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """动态热更新运行时参数。"""
        app = self.app
        ctrl = getattr(app, "controller", None) if app else None
        sm = getattr(app, "state_machine", None) if app else None
        audio = getattr(app, "audio", None) if app else None
        vision = getattr(app, "vision", None) if app else None

        if "target_mode" in params:
            t_mode = str(params["target_mode"]).lower()
            if t_mode in ("aruco", "face"):
                self._target_mode = t_mode
                if vision:
                    if hasattr(vision, "config"):
                        vision.config["target_mode"] = t_mode
                    if hasattr(vision, "detector") and vision.detector:
                        vision.detector.target_mode = t_mode
                logger.info(f"动态切换视觉目标模式为: {t_mode}")

        if ctrl:
            if "deadzone_px_x" in params:
                ctrl.deadzone_x = int(params["deadzone_px_x"])
            if "deadzone_px_y" in params:
                ctrl.deadzone_y = int(params["deadzone_px_y"])
            if "step_deg_yaw" in params:
                ctrl.step_deg_yaw = float(params["step_deg_yaw"])
            if "step_deg_pitch" in params:
                ctrl.step_deg_pitch = float(params["step_deg_pitch"])

        if sm:
            if "lost_timeout_s" in params:
                sm.lost_timeout_s = float(params["lost_timeout_s"])
            if "turn_settle_s" in params:
                sm.turn_settle_s = float(params["turn_settle_s"])

        if audio:
            if "energy_threshold" in params:
                audio.energy_threshold = float(params["energy_threshold"])

        logger.info(f"动态热更运行时参数已应用: {params}")
        return self.get_config_dict()


__all__ = [
    "RingBufferLogHandler",
    "MockVideoGenerator",
    "WebRequestHandler",
    "ThreadedHTTPServer",
    "WebRuntimeAdapter",
]
