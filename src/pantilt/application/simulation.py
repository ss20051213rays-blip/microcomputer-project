"""阶段 4 四态云台跟踪离线模拟验收。"""
import time
from typing import Any, Dict, Optional

from pantilt.bootstrap import create_app
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.paths import DEFAULT_CONFIG


def run_simulation_test(config: Optional[Dict[str, Any]] = None) -> bool:
    """验证触发转向、寻脸、双轴跟随、遮挡保持与资源安全释放。"""
    config = config or load_config(DEFAULT_CONFIG)
    print("\n==================================================")
    print("      阶段 4 四态云台跟踪离线模拟测试")
    print("==================================================")
    app = create_app(config, dry_run=True, web=False)
    if not app.start():
        print("[FAIL] app.start() 失败")
        return False

    checks = []
    try:
        now = time.monotonic()
        assert app.state == SystemState.IDLE
        checks.append("初始待机与双轴归中")

        app.audio.event_queue.put(AudioEvent(now, -25.0, "left", 0.9, "test"))
        app.tick(now)
        assert app.state == SystemState.TURN_AND_RESPOND
        assert app.servo.current_yaw == -25.0
        assert app.servo.current_pitch == 30.0
        checks.append("音频触发方位转向并预抬俯仰")

        app.tick(now + 0.01)
        now += app.turn_settle_s + 0.02
        app.tick(now)
        assert app.state == SystemState.SEARCH_FACE
        checks.append("转向平息后进入寻脸")

        app.vision.set_mock_observation(VisionObservation(
            now, True, 60.0, (340, 150, 60, 60), 0.95, 20.0, dy_px=-45.0
        ))
        app.tick(now)
        assert app.state == SystemState.TRACK_FACE
        assert app.servo.current_yaw > -25.0 and app.servo.current_pitch > 0.0
        checks.append("人脸入画后立即进入双轴比例跟踪")

        held = app.servo.get_angles()
        app.vision.set_mock_observation(VisionObservation(
            time.monotonic(), False, 0.0, (0, 0, 0, 0), 0.0, 20.0
        ))
        app.tick(time.monotonic() + 5.0)
        assert app.state == SystemState.TRACK_FACE
        assert app.servo.get_angles() == held
        checks.append("短暂遮挡保持姿态等待续跟")

        app.stop()
        assert not app.running
        checks.append("安全停止释放管线与舵机")
    except AssertionError as exc:
        print(f"\n[FAIL] 模拟验收未通过：{exc}")
        app.stop()
        return False

    for check in checks:
        print(f"  ✅ {check}")
    print("阶段 4 离线模拟通过。\n")
    return True


__all__ = ["run_simulation_test"]
