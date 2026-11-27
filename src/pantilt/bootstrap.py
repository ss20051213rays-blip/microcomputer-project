"""应用装配根 (Composition Root / Bootstrap)。

负责解析配置并实例化感知、执行、控制、Web 运行时与状态机组件，构造完整的 PanTiltTrackerApp 实例。
"""
from typing import Any, Dict, Optional

from pantilt.adapters.actuation.servo import ServoController
from pantilt.adapters.perception.audio import AudioPipeline
from pantilt.adapters.perception.vision import VisionPipeline
from pantilt.adapters.runtime.console import ConsoleListener
from pantilt.adapters.runtime.web import WebRuntimeServer
from pantilt.application.tracker import PanTiltTrackerApp
from pantilt.domain.controller import DeadzoneStepController
from pantilt.domain.state_machine import TrackerStateMachine


def create_app(
    config: Dict[str, Any],
    dry_run: bool = False,
    web: Optional[bool] = None,
    web_port: Optional[int] = None,
) -> PanTiltTrackerApp:
    """根据配置字典装配各具体组件并构建 PanTiltTrackerApp 实例。

    :param config: 全量配置字典
    :param dry_run: 是否处于无硬件脱机模拟模式
    :param web: 显式指定是否启动 Web 运行时适配器 (None 则依据配置 web.enabled)
    :param web_port: 显式覆盖 Web 监听端口
    """
    cfg_ctrl = config.get("control", {})
    cfg_servo = config.get("servo", {})
    cfg_audio = dict(config.get("audio", {}))
    cfg_audio["wakeup"] = config.get("wakeup", {})
    cfg_audio["speaker"] = config.get("speaker", {})
    cfg_camera = config.get("camera", {})
    cfg_web = dict(config.get("web", {}))

    servo = ServoController(cfg_servo, dry_run=dry_run)
    audio = AudioPipeline(cfg_audio, dry_run=dry_run)
    vision = VisionPipeline(cfg_camera, dry_run=dry_run, start_active=False)
    tracking_config = {"observation_timeout_s": cfg_camera.get("observation_timeout_s", 0.3), **cfg_ctrl}
    controller = DeadzoneStepController(tracking_config, cfg_servo)
    state_machine = TrackerStateMachine(cfg_ctrl, cfg_servo, cfg_camera)

    main_loop_hz = cfg_ctrl.get("main_loop_hz", 30)

    # 确定是否挂载 Web 运行时适配器
    if web is not None:
        is_web_enabled = bool(web)
    else:
        is_web_enabled = bool(cfg_web.get("enabled", False))

    if web_port is not None:
        cfg_web["port"] = int(web_port)

    app = PanTiltTrackerApp(
        servo=servo,
        audio=audio,
        vision=vision,
        controller=controller,
        state_machine=state_machine,
        console=None,
        web=None,
        main_loop_hz=main_loop_hz,
        dry_run=dry_run,
    )
    app.console = ConsoleListener(on_center=app._handle_console_center, on_quit=app.stop)

    if is_web_enabled:
        app.web = WebRuntimeServer(app=app, config=cfg_web)

    return app


__all__ = ["create_app"]
