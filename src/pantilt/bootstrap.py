"""应用装配根 (Composition Root / Bootstrap)。

负责解析配置并实例化感知、执行、控制与状态机组件，构造完整的 PanTiltTrackerApp 实例。
"""
from typing import Any, Dict

from pantilt.adapters.actuation.laser import LaserIndicator
from pantilt.adapters.actuation.servo import ServoController
from pantilt.adapters.perception.audio import AudioPipeline
from pantilt.adapters.perception.vision import VisionPipeline
from pantilt.adapters.runtime.console import ConsoleListener
from pantilt.application.tracker import PanTiltTrackerApp
from pantilt.domain.controller import DeadzoneStepController
from pantilt.domain.state_machine import TrackerStateMachine


def create_app(config: Dict[str, Any], dry_run: bool = False) -> PanTiltTrackerApp:
    """根据配置字典装配各具体组件并构建 PanTiltTrackerApp 实例。"""
    cfg_ctrl = config.get("control", {})
    cfg_servo = config.get("servo", {})
    cfg_audio = config.get("audio", {})
    cfg_camera = config.get("camera", {})
    cfg_laser = config.get("laser", {})

    servo = ServoController(cfg_servo, dry_run=dry_run)
    audio = AudioPipeline(cfg_audio, dry_run=dry_run)
    vision = VisionPipeline(cfg_camera, dry_run=dry_run)
    controller = DeadzoneStepController(cfg_ctrl, cfg_servo)
    laser = LaserIndicator(cfg_laser, dry_run=dry_run)
    state_machine = TrackerStateMachine(cfg_ctrl, cfg_laser)

    main_loop_hz = cfg_ctrl.get("main_loop_hz", 30)

    app = PanTiltTrackerApp(
        servo=servo,
        audio=audio,
        vision=vision,
        controller=controller,
        laser=laser,
        state_machine=state_machine,
        console=None,
        main_loop_hz=main_loop_hz,
    )
    app.console = ConsoleListener(on_center=app._handle_console_center, on_quit=app.stop)
    return app


__all__ = ["create_app"]
