"""死区步进控制器单测与模拟验证。"""
import time
import pytest

from pantilt.domain.types import VisionObservation
from pantilt.domain.controller import DeadzoneStepController


@pytest.fixture
def controller():
    config_control = {"observation_timeout_s": 0.5}
    config_servo = {"deadzone_px": 30, "step_deg": 2.0}
    return DeadzoneStepController(config_control, config_servo)


def test_step_left_outside_deadzone(controller):
    """场景1: 偏差 -50 px (明显偏左) -> 输出 -2.0°。"""
    now = time.monotonic()
    obs = VisionObservation(now, True, -50.0, (10, 10, 50, 50), 0.9, 15.0)
    assert controller.compute_step(obs) == -2.0


def test_step_right_outside_deadzone(controller):
    """场景2: 偏差 +45 px (明显偏右) -> 输出 +2.0°。"""
    now = time.monotonic()
    obs = VisionObservation(now, True, 45.0, (10, 10, 50, 50), 0.9, 15.0)
    assert controller.compute_step(obs) == 2.0


def test_deadzone_filtering(controller):
    """场景3/4: 死区内偏差 (-10px, +20px) -> 输出 0.0°。"""
    now = time.monotonic()
    obs_left = VisionObservation(now, True, -10.0, (10, 10, 50, 50), 0.9, 15.0)
    obs_right = VisionObservation(now, True, 20.0, (10, 10, 50, 50), 0.9, 15.0)
    assert controller.compute_step(obs_left) == 0.0
    assert controller.compute_step(obs_right) == 0.0


def test_observation_timeout_filtering(controller):
    """场景5: 观测已过期 1 秒 (防抖) -> 输出 0.0°。"""
    now = time.monotonic()
    obs_old = VisionObservation(now - 1.0, True, -60.0, (10, 10, 50, 50), 0.9, 15.0)
    assert controller.compute_step(obs_old) == 0.0


def test_no_face_detected(controller):
    """场景6: 未检测到目标 -> 输出 0.0°。"""
    now = time.monotonic()
    obs_none = VisionObservation(now, False, 0.0, (0, 0, 0, 0), 0.0, 15.0)
    assert controller.compute_step(obs_none) == 0.0


def main():
    print("=== 死区步进控制器模拟测试 ===")
    config_control = {"observation_timeout_s": 0.5}
    config_servo = {"deadzone_px": 30, "step_deg": 2.0}
    controller_inst = DeadzoneStepController(config_control, config_servo)
    now = time.monotonic()

    test_cases = [
        ("场景1: 偏差 -50 px (明显偏左)", -50.0, 0.0),
        ("场景2: 偏差 +45 px (明显偏右)", 45.0, 0.0),
        ("场景3: 偏差 -10 px (死区内偏左)", -10.0, 0.0),
        ("场景4: 偏差 +20 px (死区内偏右)", 20.0, 0.0),
        ("场景5: 观测已过期 1 秒 (防抖)", -60.0, 1.0),
        ("场景6: 未检测到人脸", None, 0.0),
    ]

    for name, dx, age in test_cases:
        if dx is None:
            obs = VisionObservation(now - age, False, 0.0, (0, 0, 0, 0), 0.0, 15.0)
        else:
            obs = VisionObservation(now - age, True, dx, (10, 10, 50, 50), 0.9, 15.0)
        step = controller_inst.compute_step(obs)
        print(f"{name:30s} => 输出步进角: {step:>5.1f}°")


if __name__ == "__main__":
    main()
