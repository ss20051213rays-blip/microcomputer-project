"""测试 Web 运行时适配器与通信接口 (src/pantilt/adapters/runtime/web.py)。"""
import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from pantilt.adapters.runtime.web import WebAdapter, WebRuntimeServer
from pantilt.bootstrap import create_app
from pantilt.cli import parse_args
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation

logger = logging.getLogger("App")


def get_free_port() -> int:
    """获取一个空闲可用的随机端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def web_app(app_config):
    """启动挂载了 Web 运行时的脱机测试 App。"""
    port = get_free_port()
    app = create_app(app_config, dry_run=True, web=True, web_port=port)
    assert app.web is not None
    assert app.web.port == port
    assert app.start()
    time.sleep(0.05)  # 等待后台 HTTP 线程监听完成
    yield app, port
    app.stop()


def _http_get(url: str, timeout: float = 2.0) :
    req = urllib.request.Request(url, headers={"User-Agent": "TestClient/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()


def _http_post_json(url: str, payload: dict, timeout: float = 2.0) :
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TestClient/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()



def test_web_alias_and_classes():
    """验证 WebRuntimeServer 与 WebAdapter 类导出与别名。"""
    assert issubclass(WebRuntimeServer, object)
    assert WebAdapter is WebRuntimeServer


def test_static_index(web_app):
    """验证 GET / 能够返回 200 及 HTML 页面。"""
    app, port = web_app
    status, headers, body = _http_get(f"http://127.0.0.1:{port}/")
    assert status == 200
    assert "text/html" in headers.get("Content-Type", "")
    assert b"<!DOCTYPE html>" in body or b"<html" in body


def test_rest_api_status_and_telemetry(web_app):
    """验证 GET /api/status 与 GET /api/telemetry REST 接口。"""
    app, port = web_app

    # 1. 状态查询
    status, _, body = _http_get(f"http://127.0.0.1:{port}/api/status")
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    data = res["data"]
    assert data["app_state"] == "IDLE"
    assert data["control_mode"] == "AUTO"
    assert data["running"] is True
    assert data["dry_run"] is True
    assert data["version"] == "0.2.0"

    # 2. 全量遥测快照
    status, _, body = _http_get(f"http://127.0.0.1:{port}/api/telemetry")
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    telemetry = res["data"]
    assert "timestamp_mono" in telemetry
    assert "status" in telemetry
    assert "servo" in telemetry
    assert "vision" in telemetry
    assert "audio" in telemetry
    assert "laser" in telemetry
    assert telemetry["servo"]["yaw"] == 0.0
    assert telemetry["servo"]["pitch"] == 0.0


def test_rest_api_servo_control_and_clamping(web_app):
    """验证 POST /api/control/servo 增量步进、绝对定位与限位截断保护。"""
    app, port = web_app

    # 1. 增量步进
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/servo",
        {"mode": "step", "delta_yaw": 12.0, "delta_pitch": -8.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    assert abs(res["data"]["applied_yaw"] - 12.0) < 1e-3
    assert abs(res["data"]["applied_pitch"] - (-8.0)) < 1e-3
    assert res["data"]["clamped"] is False
    assert app.control_mode == "MANUAL"

    # 2. 绝对定位与超限截断 (yaw 最大 90°, pitch 最小 -30°)
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/servo",
        {"mode": "absolute", "yaw": 150.0, "pitch": -80.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    assert abs(res["data"]["applied_yaw"] - 90.0) < 1e-3
    assert abs(res["data"]["applied_pitch"] - (-30.0)) < 1e-3
    assert res["data"]["clamped"] is True


def test_rest_api_center_laser_mode_reset(web_app):
    """验证一键回中、激光控制、模式切换与状态机复位接口。"""
    app, port = web_app

    # 1. 一键归中
    status, _, body = _http_post_json(f"http://127.0.0.1:{port}/api/control/center", {})
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["yaw"] == 0.0
    assert res["data"]["pitch"] == 0.0
    yaw, pitch = app.servo.get_angles()
    assert abs(yaw) < 1e-3 and abs(pitch) < 1e-3

    # 2. 激光控制点亮
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/laser",
        {"enable": True, "force_override": True},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["is_on"] is True
    assert app.laser_is_on is True

    # 3. 激光控制熄灭
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/laser",
        {"enable": False},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["is_on"] is False
    assert app.laser_is_on is False

    # 4. 模式切换
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/mode",
        {"mode": "MANUAL"},
    )
    assert status == 200
    assert app.control_mode == "MANUAL"

    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/control/mode",
        {"mode": "AUTO"},
    )
    assert status == 200
    assert app.control_mode == "AUTO"

    # 5. 状态机复位
    status, _, body = _http_post_json(f"http://127.0.0.1:{port}/api/control/reset", {})
    assert status == 200
    assert app.state == SystemState.IDLE


def test_rest_api_config_query_and_update(web_app):
    """验证 GET /api/config 与 POST /api/config 动态热更。"""
    app, port = web_app

    # 查询
    status, _, body = _http_get(f"http://127.0.0.1:{port}/api/config")
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    data = res["data"]
    assert "deadzone_px_x" in data
    assert "step_deg_yaw" in data

    # 更新
    status, _, body = _http_post_json(
        f"http://127.0.0.1:{port}/api/config",
        {"params": {"deadzone_px_x": 42, "step_deg_yaw": 3.5}},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["deadzone_px_x"] == 42
    assert res["data"]["step_deg_yaw"] == 3.5
    assert app.controller.deadzone_x == 42
    assert app.controller.step_deg_yaw == 3.5


def test_rest_api_logs(web_app):
    """验证 GET /api/logs 环形缓冲日志查询。"""
    app, port = web_app
    test_msg = f"WebLog-Unit-Test-{time.time()}"
    logger.info(test_msg)

    status, _, body = _http_get(f"http://127.0.0.1:{port}/api/logs?limit=20")
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    entries = res["data"]
    assert isinstance(entries, list)
    assert any(test_msg in e.get("message", "") for e in entries)


def test_sse_stream_events(web_app):
    """验证 GET /api/stream/events SSE 事件流正确推送 telemetry。"""
    app, port = web_app
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/stream/events")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/event-stream" in content_type

        # 读取若干行以验证 SSE 结构 (event: telemetry \n data: {...})
        received_event = None
        received_data = None
        for _ in range(20):
            line = resp.readline().decode("utf-8").strip()
            if line.startswith("event:"):
                received_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and received_event == "telemetry":
                received_data = line.split(":", 1)[1].strip()
                break

        assert received_event == "telemetry"
        assert received_data is not None
        payload = json.loads(received_data)
        assert "status" in payload
        assert "servo" in payload


def test_mjpeg_stream_video(web_app):
    """验证 GET /api/stream/video MJPEG 视频流包含有效 JPEG 帧。"""
    app, port = web_app
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/stream/video?hud=1")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "multipart/x-mixed-replace" in content_type

        # 读取前 4KB 数据，应包含 --frame 及 JPEG SOI 标头 \xff\xd8
        chunk = resp.read(4096)
        assert b"--frame" in chunk
        assert b"image/jpeg" in chunk
        assert b"\xff\xd8" in chunk  # JPEG 魔数 SOI


def test_cli_web_options():
    """验证 CLI 命令行参数中 --web、--no-web 与 --web-port 解析正确。"""
    args1 = parse_args(["--web", "--web-port", "8888"])
    assert args1.web is True
    assert args1.web_port == 8888

    args2 = parse_args(["--no-web"])
    assert args2.web is False

    args3 = parse_args([])
    assert args3.web is None
    assert args3.web_port is None
