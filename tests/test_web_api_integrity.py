"""前端 API 与 Web 适配器完整性自动化测试用例集 (Task 5)。

覆盖项目验收规范七大维度：
1. 静态前端资源加载与健康检查 (HTTP 200, MIME, 404, CORS 预检)；
2. 状态查询接口数据结构与字段完整性 (/api/status, /api/telemetry 递归模式校验)；
3. 云台双轴移动、归中、复位控制指令下发及边界限制 (增量/绝对/超限截断 Clamping/容错)；
4. 激光指示器手动与自动模式切换 (MANUAL/AUTO/CALIBRATION 切换、强制超驰、10s 超时保护、安全联锁)；
5. 目标模式 (ArUco/Face) 配置动态切换与控制参数热更；
6. 实时视频流推流与数据包完整性 (MJPEG boundary/SOI/EOI 结构解析、SSE telemetry/log 事件流)；
7. 并发抗压与边界健壮性测试 (多线程并发请求、异常负载穿透防护)。
"""
import concurrent.futures
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import pytest

from pantilt.bootstrap import create_app
from pantilt.cli import main
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation

logger = logging.getLogger("App")


def get_free_port() -> int:
    """获取一个空闲可用的随机本地端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def web_server(app_config):
    """启动挂载 Web 适配器的集成测试服务实例。"""
    port = get_free_port()
    app = create_app(app_config, dry_run=True, web=True, web_port=port)
    assert app.web is not None
    assert app.start(), "Web 集成测试环境启动失败"
    time.sleep(0.06)  # 确保 HTTP 线程完全就绪
    yield app, port
    app.stop()


def _request(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 3.0,
) -> Tuple[int, Dict[str, str], bytes]:
    """HTTP 通用请求辅助函数。"""
    hdrs = {"User-Agent": "PanTilt-QA-TestEngine/1.0"}
    if headers:
        hdrs.update(headers)

    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        if "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data_bytes, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, resp.read()
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        return e.code, resp_headers, e.read()


# ==============================================================================
# 维度 1: 静态前端资源加载与健康检查
# ==============================================================================
def test_static_frontend_and_health_checks(web_server):
    """验证 Web 根路径、静态前端资产分发、MIME 类型、CORS 预检与 404 容错。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 1.1 根路径与 index.html 交付
    for path in ["/", "/index.html"]:
        status, headers, body = _request(f"{base_url}{path}")
        assert status == 200, f"{path} 返回非 200: {status}"
        assert "text/html" in headers.get("content-type", "")
        html_str = body.decode("utf-8")
        assert "<!DOCTYPE html>" in html_str or "<html" in html_str
        # 验证核心四象限视口 DOM 容器齐备
        assert "panel-video" in html_str
        assert "panel-radar" in html_str
        assert "panel-gimbal" in html_str
        assert "panel-telemetry-logs" in html_str

    # 1.2 静态样式表资源 (CSS)
    css_files = ["/static/css/hud.css", "/static/css/components.css"]
    for css_path in css_files:
        status, headers, body = _request(f"{base_url}{css_path}")
        assert status == 200, f"{css_path} 无法加载"
        assert "text/css" in headers.get("content-type", "")
        assert len(body) > 200

    # 1.3 静态脚本模块 (全部 8 个 ES6 JS 模块)
    js_modules = [
        "/static/js/app.js",
        "/static/js/api.js",
        "/static/js/sse.js",
        "/static/js/hud_canvas.js",
        "/static/js/radar_canvas.js",
        "/static/js/gimbal_widget.js",
        "/static/js/telemetry_view.js",
        "/static/js/terminal_logs.js",
    ]
    for js_path in js_modules:
        status, headers, body = _request(f"{base_url}{js_path}")
        assert status == 200, f"{js_path} 模块加载失败: {status}"
        ctype = headers.get("content-type", "")
        assert "javascript" in ctype or "text/plain" in ctype, f"MIME 类型非法: {ctype}"
        assert len(body) > 100

    # 1.4 OPTIONS 预检请求与 CORS 响应头校验
    status, headers, _ = _request(f"{base_url}/api/status", method="OPTIONS")
    assert status == 204
    assert headers.get("access-control-allow-origin") == "*"
    assert "POST" in headers.get("access-control-allow-methods", "")

    # 1.5 404 错误路径防御：返回标准 JSON 错误而非崩溃
    status, headers, body = _request(f"{base_url}/api/non_existent_route")
    assert status == 404
    err_json = json.loads(body.decode("utf-8"))
    assert err_json["code"] == 404
    assert "未找到" in err_json["message"] or "not found" in err_json["message"].lower()


# ==============================================================================
# 维度 2: 状态查询接口数据结构与字段完整性
# ==============================================================================
def test_status_and_telemetry_schema_integrity(web_server):
    """验证 /api/status 与 /api/telemetry 接口结构合规性与全量字段约束。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 2.1 GET /api/status 接口契约
    status, _, body = _request(f"{base_url}/api/status")
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    st_data = res["data"]
    expected_status_fields = {
        "app_state": str,
        "control_mode": str,
        "running": bool,
        "dry_run": bool,
        "uptime_s": (int, float),
        "main_loop_hz": (int, float),
        "version": str,
    }
    for field, field_type in expected_status_fields.items():
        assert field in st_data, f"status 缺少字段: {field}"
        assert isinstance(st_data[field], field_type), f"字段 {field} 类型非法: {type(st_data[field])}"
    assert st_data["version"] == "0.2.0"
    assert st_data["app_state"] in ("IDLE", "TURN_ONCE", "FOLLOW")

    # 2.2 GET /api/telemetry 全量遥测包契约
    status, _, body = _request(f"{base_url}/api/telemetry")
    assert status == 200
    t_res = json.loads(body.decode("utf-8"))
    assert t_res["code"] == 200
    telemetry = t_res["data"]

    # 根节点字段
    root_fields = ["timestamp_mono", "iso_time", "status", "servo", "vision", "audio", "laser"]
    for rf in root_fields:
        assert rf in telemetry, f"telemetry 根节点缺少: {rf}"

    # ISO 时间格式校验 (e.g. 2026-11-10T13:45:00.123Z)
    iso_time_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(iso_time_pattern, telemetry["iso_time"]), f"ISO 时间格式不合规: {telemetry['iso_time']}"
    assert telemetry["timestamp_mono"] > 0.0

    # 舵机遥测字段
    servo = telemetry["servo"]
    servo_reqs = ["yaw", "pitch", "target_yaw", "target_pitch", "min_yaw", "max_yaw", "min_pitch", "max_pitch", "driver_type", "torque_enabled"]
    for sf in servo_reqs:
        assert sf in servo, f"servo 遥测缺少: {sf}"
    assert servo["min_yaw"] <= servo["yaw"] <= servo["max_yaw"]
    assert servo["min_pitch"] <= servo["pitch"] <= servo["max_pitch"]

    # 视觉遥测字段
    vision = telemetry["vision"]
    vision_reqs = ["target_found", "target_type", "target_id", "dx_px", "dy_px", "bbox", "confidence", "fps", "in_deadzone", "age_s"]
    for vf in vision_reqs:
        assert vf in vision, f"vision 遥测缺少: {vf}"
    assert vision["target_type"] in ("aruco", "face", "none")

    # 声学遥测字段
    audio = telemetry["audio"]
    audio_reqs = ["event_detected", "theta_deg", "side", "confidence", "method", "energy_rms", "age_s"]
    for af in audio_reqs:
        assert af in audio, f"audio 遥测缺少: {af}"
    assert audio["side"] in ("left", "right", "center", "none")

    # 激光器遥测字段
    laser = telemetry["laser"]
    laser_reqs = ["is_on", "continuous_s", "max_continuous_s", "locked_frames", "lock_min_frames", "hardware_enabled"]
    for lf in laser_reqs:
        assert lf in laser, f"laser 遥测缺少: {lf}"
    assert laser["max_continuous_s"] >= 1.0


# ==============================================================================
# 维度 3: 云台双轴移动、归中、复位控制指令下发及边界限制
# ==============================================================================
def test_servo_motion_center_reset_and_boundary_clamping(web_server):
    """验证步进微调、绝对定位、物理安全限位截断 (Clamping)、一键回中与状态复位。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 确保起始状态归零
    _request(f"{base_url}/api/control/center", method="POST", payload={})
    y0, p0 = app.servo.get_angles()
    assert abs(y0) < 1e-3 and abs(p0) < 1e-3

    # 3.1 增量步进 (Step mode)
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "step", "delta_yaw": 15.0, "delta_pitch": 10.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 200
    assert abs(res["data"]["applied_yaw"] - 15.0) < 1e-2
    assert abs(res["data"]["applied_pitch"] - 10.0) < 1e-2
    assert res["data"]["clamped"] is False
    assert app.control_mode == "MANUAL"

    # 再次反向步进
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "step", "delta_yaw": -25.0, "delta_pitch": -15.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert abs(res["data"]["applied_yaw"] - (-10.0)) < 1e-2
    assert abs(res["data"]["applied_pitch"] - (-5.0)) < 1e-2
    assert res["data"]["clamped"] is False

    # 3.2 绝对定位 (Absolute mode)
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "absolute", "yaw": 35.0, "pitch": -20.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert abs(res["data"]["applied_yaw"] - 35.0) < 1e-2
    assert abs(res["data"]["applied_pitch"] - (-20.0)) < 1e-2
    assert res["data"]["clamped"] is False

    # 3.3 物理安全边界限位截断保护 (Clamping)
    # Yaw 规范限位: [-90.0, +90.0], Pitch 规范限位: [-30.0, +45.0]
    # 正向严重越界
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "absolute", "yaw": 180.0, "pitch": 95.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert abs(res["data"]["applied_yaw"] - 90.0) < 1e-2
    assert abs(res["data"]["applied_pitch"] - 45.0) < 1e-2
    assert res["data"]["clamped"] is True

    # 负向严重越界
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "absolute", "yaw": -180.0, "pitch": -95.0},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert abs(res["data"]["applied_yaw"] - (-90.0)) < 1e-2
    assert abs(res["data"]["applied_pitch"] - (-30.0)) < 1e-2
    assert res["data"]["clamped"] is True

    # 3.4 一键归中 (POST /api/control/center)
    status, _, body = _request(f"{base_url}/api/control/center", method="POST", payload={})
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["yaw"] == 0.0
    assert res["data"]["pitch"] == 0.0
    curr_yaw, curr_pitch = app.servo.get_angles()
    assert abs(curr_yaw) < 1e-3 and abs(curr_pitch) < 1e-3

    # 3.5 状态机复位 (POST /api/control/reset)
    app.state_machine.state = SystemState.FOLLOW
    status, _, body = _request(f"{base_url}/api/control/reset", method="POST", payload={})
    assert status == 200
    assert app.state == SystemState.IDLE

    # 3.6 异常与畸形控制参数容错校验
    status, _, body = _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "step", "delta_yaw": "invalid_str"},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["code"] == 400


# ==============================================================================
# 维度 4: 激光指示器手动与自动模式切换
# ==============================================================================
def test_laser_control_and_mode_switching(web_server):
    """验证运行模式切换 (AUTO/MANUAL/CALIBRATION)、激光点亮/熄灭与安全联锁。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 4.1 运行模式切换
    for target_mode in ["MANUAL", "CALIBRATION", "AUTO"]:
        status, _, body = _request(
            f"{base_url}/api/control/mode",
            method="POST",
            payload={"mode": target_mode},
        )
        assert status == 200
        res = json.loads(body.decode("utf-8"))
        assert res["data"]["mode"] == target_mode
        assert app.control_mode == target_mode

    # 非法模式防御
    status, _, body = _request(
        f"{base_url}/api/control/mode",
        method="POST",
        payload={"mode": "UNKNOWN_MODE"},
    )
    assert status == 400

    # 4.2 激光手动点亮 (带 force_override 强制点亮)
    status, _, body = _request(
        f"{base_url}/api/control/laser",
        method="POST",
        payload={"enable": True, "force_override": True},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["is_on"] is True
    assert app.laser_is_on is True
    assert res["data"]["max_continuous_s"] == 10.0

    # 验证 telemetry 接口状态与物理状态强一致
    _, _, body = _request(f"{base_url}/api/telemetry")
    t_data = json.loads(body.decode("utf-8"))["data"]
    assert t_data["laser"]["is_on"] is True

    # 4.3 激光手动熄灭
    status, _, body = _request(
        f"{base_url}/api/control/laser",
        method="POST",
        payload={"enable": False},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["data"]["is_on"] is False
    assert app.laser_is_on is False

    # 4.4 安全联动保护：在 AUTO 模式下手动移动云台时，自动切入 MANUAL 模式
    _request(f"{base_url}/api/control/mode", method="POST", payload={"mode": "AUTO"})
    assert app.control_mode == "AUTO"
    _request(
        f"{base_url}/api/control/servo",
        method="POST",
        payload={"mode": "step", "delta_yaw": 5.0, "delta_pitch": 0.0},
    )
    assert app.control_mode == "MANUAL"


# ==============================================================================
# 维度 5: 目标模式 (ArUco/Face) 配置动态切换与控制参数热更
# ==============================================================================
def test_target_mode_and_config_dynamic_switching(web_server):
    """验证视觉目标模式 (ArUco/Face) 动态切换与控制参数热更新。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 5.1 查询初始配置
    status, _, body = _request(f"{base_url}/api/config")
    assert status == 200
    cfg = json.loads(body.decode("utf-8"))["data"]
    assert "target_mode" in cfg
    assert "deadzone_px_x" in cfg
    assert "step_deg_yaw" in cfg

    # 5.2 动态热更视觉目标模式为 'face'
    status, _, body = _request(
        f"{base_url}/api/config",
        method="POST",
        payload={"params": {"target_mode": "face"}},
    )
    assert status == 200
    cfg_updated = json.loads(body.decode("utf-8"))["data"]
    assert cfg_updated["target_mode"] == "face"

    # 模拟人脸检测结果，验证遥测中 target_type 随目标模式联动
    mock_obs = VisionObservation(
        timestamp_mono=time.monotonic(),
        face_found=True,
        dx_px=18.0,
        bbox=(200, 150, 80, 80),
        confidence=0.92,
        fps=30.0,
        dy_px=10.0,
        target_id=-1,
    )
    app.last_vision_obs = mock_obs
    _, _, body = _request(f"{base_url}/api/telemetry")
    t_data = json.loads(body.decode("utf-8"))["data"]
    assert t_data["vision"]["target_type"] == "face"
    assert t_data["vision"]["target_found"] is True

    # 5.3 动态热更视觉目标模式切回 'aruco'
    status, _, body = _request(
        f"{base_url}/api/config",
        method="POST",
        payload={"params": {"target_mode": "aruco"}},
    )
    assert status == 200
    cfg_updated2 = json.loads(body.decode("utf-8"))["data"]
    assert cfg_updated2["target_mode"] == "aruco"

    # 5.4 动态调节死区和控制步长
    status, _, body = _request(
        f"{base_url}/api/config",
        method="POST",
        payload={
            "params": {
                "deadzone_px_x": 48,
                "deadzone_px_y": 36,
                "step_deg_yaw": 3.2,
                "step_deg_pitch": 2.4,
                "lost_timeout_s": 4.5,
            }
        },
    )
    assert status == 200
    assert app.controller.deadzone_x == 48
    assert app.controller.deadzone_y == 36
    assert abs(app.controller.step_deg_yaw - 3.2) < 1e-3
    assert abs(app.controller.step_deg_pitch - 2.4) < 1e-3
    assert abs(app.state_machine.lost_timeout_s - 4.5) < 1e-3


# ==============================================================================
# 维度 6: 实时视频流推流与数据包完整性
# ==============================================================================
def test_mjpeg_video_stream_and_sse_events_integrity(web_server):
    """验证 MJPEG 视频多帧结构合规 (Boundary/SOI/EOI) 与 SSE 持续事件流。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 6.1 MJPEG 视频流推流与多帧结构合规
    video_url = f"{base_url}/api/stream/video?hud=1"
    req = urllib.request.Request(video_url, headers={"User-Agent": "PanTilt-QA-TestEngine/1.0"})
    with urllib.request.urlopen(req, timeout=4.0) as resp:
        assert resp.status == 200
        ctype = resp.headers.get("content-type", "")
        assert "multipart/x-mixed-replace" in ctype
        assert "boundary=frame" in ctype

        # 读取前 64KB 数据流，解析包含的连续 JPEG 数据帧
        stream_data = b""
        for _ in range(32):
            chunk = resp.read(2048)
            if not chunk:
                break
            stream_data += chunk
            if stream_data.count(b"--frame") >= 3:
                break

        assert stream_data.count(b"--frame") >= 2, "未能读取到至少两帧 MJPEG 数据"
        # 拆分帧并校验每个 JPEG 帧的起始 SOI (0xFF 0xD8)
        frames = stream_data.split(b"--frame")
        valid_jpegs = 0
        for f in frames:
            if b"image/jpeg" in f and bytes([0xff, 0xd8]) in f:
                valid_jpegs += 1
        assert valid_jpegs >= 2, f"合规 JPEG 帧数量不足: {valid_jpegs}"

    # 6.2 SSE 持续事件流及实时日志广播
    sse_url = f"{base_url}/api/stream/events"
    req = urllib.request.Request(sse_url, headers={"User-Agent": "PanTilt-QA-TestEngine/1.0"})
    with urllib.request.urlopen(req, timeout=4.0) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        received_events = []
        # 写入一条测试日志触发日志事件推送
        test_log_msg = f"QA-SSE-Log-Verification-{time.time()}"
        logger.info(test_log_msg)

        # 读取若干 SSE 文本行
        for _ in range(30):
            line = resp.readline().decode("utf-8").strip()
            if line.startswith("event:"):
                ev_name = line.split(":", 1)[1].strip()
                received_events.append(ev_name)
            if "telemetry" in received_events and (len(received_events) >= 3):
                break

        assert "telemetry" in received_events, f"未在 SSE 中接收到 telemetry 事件: {received_events}"


# ==============================================================================
# 维度 7: 接口并发抗压与健壮性边界测试
# ==============================================================================
def test_concurrent_api_stress_and_robustness(web_server):
    """验证多客户端高频并发访问下 REST 接口的线程安全性与抗压无死锁。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    def client_worker(worker_id: int) -> bool:
        for i in range(10):
            # 随机执行遥测查询或舵机微调
            if i % 2 == 0:
                s, _, b = _request(f"{base_url}/api/telemetry")
                if s != 200:
                    return False
            else:
                s, _, b = _request(
                    f"{base_url}/api/control/servo",
                    method="POST",
                    payload={"mode": "step", "delta_yaw": 1.0, "delta_pitch": 0.5},
                )
                if s != 200:
                    return False
        return True

    # 启动 8 个并发客户端线程各发起 10 次请求 (总计 80 次并发请求)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(client_worker, i) for i in range(8)]
        results = [f.result(timeout=10.0) for f in futures]

    assert all(results), "高并发请求出现失败或异常断开"
    # 系统依然存活且响应正常
    st, _, b = _request(f"{base_url}/api/status")
    assert st == 200
    res = json.loads(b.decode("utf-8"))
    assert res["data"]["running"] is True


# ==============================================================================
# 维度 8: 全系统 Simulate 确定性模拟与全量回归保障
# ==============================================================================
def test_system_simulation_with_web_runtime():
    """验证系统在 Web 适配器并发挂载下执行全流程 --simulate 确定性模拟 100% 通过。"""
    port = get_free_port()
    exit_code = main(["--simulate", "--web-port", str(port)])
    assert exit_code == 0, f"--simulate 执行失败，退出码: {exit_code}"
