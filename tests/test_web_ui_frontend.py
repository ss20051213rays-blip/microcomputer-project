"""测试 Web 前端战术 HUD 界面结构与资源完整性 (Task 4 验证)。"""
import os
import re
import socket
import time
import urllib.request

import pytest

from pantilt.bootstrap import create_app

STATIC_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "src", "pantilt", "adapters", "web", "static"
)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_html_semantic_cockpit_structure():
    """验证 index.html 满足四象限战术 HUD 语义化 DOM 规范。"""
    index_path = os.path.join(STATIC_ROOT, "index.html")
    assert os.path.isfile(index_path), "index.html 未创建"

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. 验证包含四大视口容器与核心 Canvas / 元素
    assert 'id="panel-video"' in html
    assert 'id="hud-canvas"' in html
    assert 'id="video-stream-img"' in html

    assert 'id="panel-radar"' in html
    assert 'id="radar-canvas"' in html

    assert 'id="panel-gimbal"' in html
    assert 'id="viewport-gimbal"' in html

    assert 'id="panel-telemetry-logs"' in html
    assert 'id="viewport-telemetry"' in html
    assert 'id="viewport-terminal"' in html

    # 2. 验证样式与脚本模块引用
    assert 'rel="stylesheet" href="/static/css/hud.css"' in html
    assert 'rel="stylesheet" href="/static/css/components.css"' in html
    assert '<script type="module" src="/static/js/app.js"></script>' in html


def test_css_theme_variables_and_grid_layout():
    """验证 CSS 战术机甲主题变量 (Dark Theme) 与 CSS Grid 四象限布局。"""
    hud_css_path = os.path.join(STATIC_ROOT, "css", "hud.css")
    comp_css_path = os.path.join(STATIC_ROOT, "css", "components.css")

    assert os.path.isfile(hud_css_path)
    assert os.path.isfile(comp_css_path)

    with open(hud_css_path, "r", encoding="utf-8") as f:
        hud_css = f.read()

    assert "--bg-dark: #0a0e14" in hud_css
    assert "--hud-cyan: #00f3ff" in hud_css
    assert "--hud-green: #00ff9d" in hud_css
    assert "--hud-amber: #ffaa00" in hud_css
    assert "--hud-red: #ff3344" in hud_css
    assert ".cockpit-grid" in hud_css
    assert "grid-template-columns: 1fr 1fr" in hud_css

    with open(comp_css_path, "r", encoding="utf-8") as f:
        comp_css = f.read()

    assert ".gauge-arc-wrap" in comp_css
    assert ".joystick-pad" in comp_css
    assert ".dpad-grid" in comp_css
    assert ".metrics-grid" in comp_css
    assert ".terminal-card" in comp_css


def test_js_modules_code_quality_and_exports():
    """验证全部 8 个 ES 模块的代码完整性与关键类导出。"""
    js_dir = os.path.join(STATIC_ROOT, "js")
    expected_files = {
        "api.js": "export const Api =",
        "sse.js": "export class SSEClient",
        "hud_canvas.js": "export class HUDCanvasRenderer",
        "radar_canvas.js": "export class RadarCanvasRenderer",
        "gimbal_widget.js": "export class GimbalWidget",
        "telemetry_view.js": "export class TelemetryView",
        "terminal_logs.js": "export class TerminalLogs",
        "app.js": "class TacticalApp",
    }

    for filename, signature in expected_files.items():
        file_path = os.path.join(js_dir, filename)
        assert os.path.isfile(file_path), f"缺少 JS 模块: {filename}"
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        assert signature in code, f"{filename} 缺少关键导出或类定义: {signature}"


def test_all_frontend_assets_served_via_http(app_config):
    """验证全部前端静态资产均可通过 Web 运行时服务以正确 MIME 类型成功加载。"""
    port = get_free_port()
    app = create_app(app_config, dry_run=True, web=True, web_port=port)
    assert app.start()
    time.sleep(0.08)

    endpoints = [
        ("/", "text/html"),
        ("/index.html", "text/html"),
        ("/static/css/hud.css", "text/css"),
        ("/static/css/components.css", "text/css"),
        ("/static/js/app.js", "javascript"),
        ("/static/js/api.js", "javascript"),
        ("/static/js/sse.js", "javascript"),
        ("/static/js/hud_canvas.js", "javascript"),
        ("/static/js/radar_canvas.js", "javascript"),
        ("/static/js/gimbal_widget.js", "javascript"),
        ("/static/js/telemetry_view.js", "javascript"),
        ("/static/js/terminal_logs.js", "javascript"),
    ]

    try:
        for path, expected_mime in endpoints:
            url = f"http://127.0.0.1:{port}{path}"
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                assert resp.status == 200
                ctype = resp.headers.get("Content-Type", "")
                assert expected_mime in ctype, f"Bad MIME for {path}: {ctype}"
                data = resp.read()
                assert len(data) > 0, f"Empty response for {path}"
    finally:
        app.stop()
