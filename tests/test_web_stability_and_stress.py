"""前端与系统稳定性、边界异常及高并发抗压自动化测试用例集 (Task 6)。

覆盖验收规范核心维度：
1. 连续长时间持续轮询与视频推流测试 (内存占用平稳、无泄漏、连接池稳定)；
2. 极端边界与畸形参数 Fuzzing 输入容错 (超限/类型混淆/畸形 JSON 安全拦截不崩溃)；
3. 网络异常中断与断线重连恢复验证 (SSE/MJPEG 突发重置自愈，客户端降级轮询保障)；
4. 云台全象限极限角度软限位保护 (正负极值绝对定位、持续累加步进锁死与一键复位)；
5. 激光器连续开启超时安全保护与失锁瞬态切断 (10s 过热保护联锁)；
6. 多线程混合高并发压力测试 (连接池与线程资源安全回收)。
"""
import concurrent.futures
import json
import logging
import socket
import threading
import time
import tracemalloc
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import pytest

from pantilt.bootstrap import create_app
from pantilt.domain.types import SystemState

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
    assert app.start(), "Web 稳定性测试环境启动失败"
    time.sleep(0.06)
    yield app, port
    app.stop()


def _request(
    url: str,
    method: str = "GET",
    payload: Optional[Any] = None,
    raw_body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 3.0,
) -> Tuple[int, Dict[str, str], bytes]:
    """HTTP 请求辅助函数，支持原始字节注入以进行 Fuzzing 测试。"""
    hdrs = {"User-Agent": "PanTilt-QA-StressEngine/1.0"}
    if headers:
        hdrs.update(headers)

    data_bytes = None
    if raw_body is not None:
        data_bytes = raw_body
    elif payload is not None:
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
# 1. 连续长时间持续轮询与视频推流测试 (无内存泄漏，连接池稳定)
# ==============================================================================
def test_continuous_polling_and_streaming_memory_stability(web_server):
    """验证高频连续轮询 (200+次) 与 MJPEG 推流下内存稳态，无内存泄漏与孤儿线程。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    tracemalloc.start()
    initial_threads = threading.active_count()

    # 预热 20 次请求
    for _ in range(20):
        _request(f"{base_url}/api/telemetry")

    snapshot_before = tracemalloc.take_snapshot()

    # 执行 200 次连续高频轮询查询
    for i in range(200):
        url = f"{base_url}/api/telemetry" if i % 2 == 0 else f"{base_url}/api/status"
        status, _, body = _request(url)
        assert status == 200
        assert len(body) > 50

    # 同时发起 MJPEG 视频流取流并在读取 5 帧后主动断开
    video_url = f"{base_url}/api/stream/video?hud=1"
    req = urllib.request.Request(video_url, headers={"User-Agent": "PanTilt-QA/1.0"})
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        stream_data = b""
        for _ in range(30):
            chunk = resp.read(4096)
            if not chunk:
                break
            stream_data += chunk
            if stream_data.count(b"--frame") >= 3:
                break
        assert stream_data.count(b"--frame") >= 2, f"未能读取到足够的 MJPEG 数据帧: {stream_data.count(b'--frame')}"

    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in top_stats) / 1024.0

    tracemalloc.stop()

    # 验证内存增量处于极小的非泄漏合理区间 (< 3.0 MB)
    assert total_diff_kb < 3072.0, f"内存增长过大，可能存在潜在泄漏: {total_diff_kb:.2f} KB"

    # 等待后台关闭，验证活跃线程数安全回落
    time.sleep(0.1)
    final_threads = threading.active_count()
    assert final_threads <= initial_threads + 3, f"存在未释放的挂起线程: {final_threads} vs {initial_threads}"


# ==============================================================================
# 2. 极端边界与畸形参数 Fuzzing 输入容错
# ==============================================================================
def test_extreme_inputs_and_malformed_fuzzing(web_server):
    """验证畸形 JSON、类型混淆、越界超长负载、非法方法与路径遍历均被安全拦截。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 2.1 畸形语法 JSON 请求体 (未闭合、截断、非 JSON 字节) -> 必须返回 400
    malformed_bodies = [
        b"{broken_json: 123",
        b"{\"mode\": \"step\", \"delta_yaw\": ",
        b"[1, 2, 3,",
        b"\x00\x01\x02\xff\xfe",
    ]
    for bad_body in malformed_bodies:
        status, _, body = _request(
            f"{base_url}/api/control/servo",
            method="POST",
            raw_body=bad_body,
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"畸形请求应返回 400，实际返回: {status}"
        res = json.loads(body.decode("utf-8"))
        assert res["code"] == 400

    # 2.2 字段类型异常混淆 Fuzzing
    type_fuzz_payloads = [
        # 字符串替代数值
        {"mode": "step", "delta_yaw": "not_a_number"},
        # 嵌套字典替代数值
        {"mode": "step", "delta_yaw": {"nested": 123}},
        # NaN 注入尝试
        {"mode": "step", "delta_yaw": "NaN"},
    ]
    for p in type_fuzz_payloads:
        status, _, body = _request(
            f"{base_url}/api/control/servo",
            method="POST",
            payload=p,
        )
        assert status == 400

    # 2.3 运行模式非法入参防护
    status, _, body = _request(
        f"{base_url}/api/control/mode",
        method="POST",
        payload={"mode": "INVALID_EXPLODE_MODE"},
    )
    assert status == 400

    # 2.4 配置热更非字典防护
    status, _, body = _request(
        f"{base_url}/api/config",
        method="POST",
        payload={"params": "string_instead_of_dict"},
    )
    assert status == 400

    # 2.5 路径遍历与非法文件请求防御
    status, _, body = _request(f"{base_url}/static/../../../../etc/passwd")
    assert status == 404

    # 2.6 服务在经过一系列恶意输入轰炸后仍然健壮存活
    st, _, b = _request(f"{base_url}/api/status")
    assert st == 200
    assert json.loads(b.decode("utf-8"))["code"] == 200


# ==============================================================================
# 3. 前端与后端网络异常中断与断线重连恢复验证
# ==============================================================================
def test_network_disconnect_and_reconnection_resilience(web_server):
    """模拟网络链路突发重置 (Broken Pipe / Connection Reset) 与瞬态重连恢复。"""
    app, port = web_server

    # 3.1 模拟 SSE 客户端建立连接并在首包后强行断开套接字
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", port))
    req = b"GET /api/stream/events HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n"
    s.sendall(req)
    chunk = s.recv(1024)
    assert b"text/event-stream" in chunk
    # 强制关闭套接字 (发送 RST/FIN 触发后端 BrokenPipe)
    s.close()
    time.sleep(0.08)

    # 3.2 模拟 MJPEG 视频流突发重置断开
    s_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_video.connect(("127.0.0.1", port))
    req_v = b"GET /api/stream/video?hud=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
    s_video.sendall(req_v)
    chunk_v = s_video.recv(1024)
    assert b"multipart/x-mixed-replace" in chunk_v
    s_video.close()
    time.sleep(0.08)

    # 3.3 验证后端无崩溃，新客户端即刻建立重连与数据流接收
    s_new = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_new.connect(("127.0.0.1", port))
    s_new.sendall(req)
    chunk_new = s_new.recv(1024)
    assert b"text/event-stream" in chunk_new
    s_new.close()

    # 验证 REST API 请求响应时延在毫秒级正常运行
    t0 = time.monotonic()
    st, _, _ = _request(f"http://127.0.0.1:{port}/api/telemetry")
    latency_ms = (time.monotonic() - t0) * 1000.0
    assert st == 200
    assert latency_ms < 50.0, f"重连后接口响应迟钝: {latency_ms:.2f}ms"


# ==============================================================================
# 4. 云台极限角度软限位保护
# ==============================================================================
def test_gimbal_soft_limits_exhaustive_boundaries(web_server):
    """穷举验证 Yaw/Pitch 全象限绝对与增量越界截断 (Clamping) 及极限累加防溢出。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    # 限位定义: Yaw [-90.0, 90.0], Pitch [-30.0, 45.0]
    test_matrix = [
        # (输入yaw, 输入pitch, 期望applied_yaw, 期望applied_pitch, 期望clamped)
        (150.0, 80.0, 90.0, 45.0, True),       # 第一象限极端越界
        (-180.0, 60.0, -90.0, 45.0, True),     # 第二象限极端越界
        (-120.0, -90.0, -90.0, -30.0, True),   # 第三象限极端越界
        (100.0, -50.0, 90.0, -30.0, True),     # 第四象限极端越界
        (90.0, 45.0, 90.0, 45.0, False),       # 正边界临界极值点
        (-90.0, -30.0, -90.0, -30.0, False),   # 负边界临界极值点
        (0.0, 0.0, 0.0, 0.0, False),           # 零点中位
    ]

    for in_y, in_p, exp_y, exp_p, exp_clamped in test_matrix:
        st, _, body = _request(
            f"{base_url}/api/control/servo",
            method="POST",
            payload={"mode": "absolute", "yaw": in_y, "pitch": in_p},
        )
        assert st == 200
        res = json.loads(body.decode("utf-8"))["data"]
        assert abs(res["applied_yaw"] - exp_y) < 1e-2, f"Yaw 截断不合规: {res['applied_yaw']} vs {exp_y}"
        assert abs(res["applied_pitch"] - exp_p) < 1e-2, f"Pitch 截断不合规: {res['applied_pitch']} vs {exp_p}"
        assert res["clamped"] is exp_clamped

    # 极限位置持续同向累加步进防护 (稳态截断防发散)
    # 当前已在 (0.0, 0.0)，先打到 (+90.0, +45.0)
    _request(f"{base_url}/api/control/servo", method="POST", payload={"mode": "absolute", "yaw": 90.0, "pitch": 45.0})
    # 连续执行 5 次同向正步进
    for _ in range(5):
        st, _, body = _request(
            f"{base_url}/api/control/servo",
            method="POST",
            payload={"mode": "step", "delta_yaw": 10.0, "delta_pitch": 5.0},
        )
        assert st == 200
        res = json.loads(body.decode("utf-8"))["data"]
        assert abs(res["applied_yaw"] - 90.0) < 1e-2
        assert abs(res["applied_pitch"] - 45.0) < 1e-2
        assert res["clamped"] is True

    # 一键快速归中
    st, _, body = _request(f"{base_url}/api/control/center", method="POST", payload={})
    assert st == 200
    y_final, p_final = app.servo.get_angles()
    assert abs(y_final) < 1e-3 and abs(p_final) < 1e-3


# ==============================================================================
# 5. 激光连续开启超时安全保护
# ==============================================================================
def test_removed_laser_stays_fail_closed(web_server):
    """阶段 4 不装配激光器；遗留遥控端点必须 fail closed。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"
    status, _, body = _request(
        f"{base_url}/api/control/laser",
        method="POST",
        payload={"enable": True, "force_override": True},
    )
    assert status == 200
    assert json.loads(body.decode("utf-8"))["data"]["is_on"] is False
    assert not hasattr(app, "laser")
    status, _, body = _request(f"{base_url}/api/telemetry")
    assert status == 200
    assert json.loads(body.decode("utf-8"))["data"]["laser"]["is_on"] is False


# ==============================================================================
# 6. 多线程混合高并发压力测试
# ==============================================================================
def test_high_concurrency_stress_pool_stability(web_server):
    """验证 12 个线程高并发混合压力请求 (状态、遥测、舵机、日志、配置) 100% 成功无死锁。"""
    app, port = web_server
    base_url = f"http://127.0.0.1:{port}"

    def mixed_worker(thread_idx: int) -> Tuple[int, float]:
        success_count = 0
        t_start = time.monotonic()
        for i in range(15):
            op = (thread_idx + i) % 5
            if op == 0:
                s, _, _ = _request(f"{base_url}/api/status")
            elif op == 1:
                s, _, _ = _request(f"{base_url}/api/telemetry")
            elif op == 2:
                s, _, _ = _request(
                    f"{base_url}/api/control/servo",
                    method="POST",
                    payload={"mode": "step", "delta_yaw": 0.5, "delta_pitch": -0.5},
                )
            elif op == 3:
                s, _, _ = _request(f"{base_url}/api/logs?limit=10")
            else:
                s, _, _ = _request(f"{base_url}/api/config")

            if s == 200:
                success_count += 1
        elapsed = time.monotonic() - t_start
        return success_count, elapsed

    total_threads = 12
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_threads) as executor:
        futures = [executor.submit(mixed_worker, idx) for idx in range(total_threads)]
        results = [f.result(timeout=15.0) for f in futures]

    total_requests = total_threads * 15
    successful_requests = sum(r[0] for r in results)
    avg_duration = sum(r[1] for r in results) / len(results)

    assert successful_requests == total_requests, f"高并发测试出现失败: {successful_requests}/{total_requests}"
    # 平均每线程 15 次请求耗时应在合理性能区间 (< 2.5s)
    assert avg_duration < 2.5, f"高并发处理过慢: 平均耗时 {avg_duration:.2f}s"
