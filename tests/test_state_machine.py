"""状态机脱机模拟验收测试与 pytest 用例集。"""
import time

from pantilt.application.simulation import run_simulation_test
from pantilt.bootstrap import create_app
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation


def test_01_initial_idle_and_centered(running_app):
    """测试项 1: 系统冷启动成功，初始状态为 IDLE，舵机归中 0.0°。"""
    assert running_app.state == SystemState.IDLE
    assert abs(running_app.servo.current_angle - 0.0) < 1e-3


def test_02_audio_trigger_turn_once(running_app):
    """测试项 2: 声学事件正确触发状态转移 IDLE -> TURN_ONCE，舵机开环转向 -35.0°。"""
    now = time.monotonic()
    clap_event = AudioEvent(
        timestamp_mono=now,
        theta_audio_deg=-35.0,
        side="left",
        confidence=0.85,
        method="gcc_phat",
    )
    running_app.audio.event_queue.put(clap_event)
    running_app.tick(now)

    assert running_app.state == SystemState.TURN_ONCE
    assert abs(running_app.servo.current_angle - (-35.0)) < 1e-3


def test_03_turn_settle_follow_transition(running_app):
    """测试项 3: 转向到位后平息延时结束，成功顺序接管进入 FOLLOW 状态。"""
    now = time.monotonic()
    clap = AudioEvent(now, -35.0, "left", 0.85, "gcc_phat")
    running_app.audio.event_queue.put(clap)
    running_app.tick(now)

    # 记录平息起点
    running_app.tick(now)
    now += running_app.turn_settle_s + 0.05
    running_app.tick(now)

    assert running_app.state == SystemState.FOLLOW


def test_04_echo_rejection_in_follow(running_app):
    """测试项 4: FOLLOW 视觉接管期间，背景回声与新拍手被完全屏蔽忽略。"""
    now = time.monotonic()
    clap = AudioEvent(now, -35.0, "left", 0.85, "gcc_phat")
    running_app.audio.event_queue.put(clap)
    running_app.tick(now)
    running_app.tick(now)
    now += running_app.turn_settle_s + 0.05
    running_app.tick(now)
    assert running_app.state == SystemState.FOLLOW

    # 注入回声
    echo = AudioEvent(now, 40.0, "right", 0.9, "gcc_phat")
    running_app.audio.event_queue.put(echo)
    running_app.tick(now)
    assert running_app.state == SystemState.FOLLOW


def test_05_vision_step_response(running_app):
    """测试项 5: 人脸偏右 (dx=+45px) 触发正确步进。"""
    now = time.monotonic()
    clap = AudioEvent(now, -35.0, "left", 0.85, "gcc_phat")
    running_app.audio.event_queue.put(clap)
    running_app.tick(now)
    running_app.tick(now)
    now += running_app.turn_settle_s + 0.05
    running_app.tick(now)

    face_obs_right = VisionObservation(
        timestamp_mono=now,
        face_found=True,
        dx_px=45.0,
        bbox=(100, 100, 50, 50),
        confidence=0.95,
        fps=15.0,
    )
    running_app.vision.set_mock_observation(face_obs_right)
    angle_before = running_app.servo.current_angle
    running_app.tick(now)
    assert running_app.servo.current_angle > angle_before


def test_06_deadzone_filtering(running_app):
    """测试项 6: 人脸位于死区内 (dx=+10px) 舵机保持静止，防抖滤波生效。"""
    now = time.monotonic()
    clap = AudioEvent(now, -35.0, "left", 0.85, "gcc_phat")
    running_app.audio.event_queue.put(clap)
    running_app.tick(now)
    running_app.tick(now)
    now += running_app.turn_settle_s + 0.05
    running_app.tick(now)

    face_obs_deadzone = VisionObservation(
        timestamp_mono=now,
        face_found=True,
        dx_px=10.0,
        bbox=(100, 100, 50, 50),
        confidence=0.95,
        fps=15.0,
    )
    running_app.vision.set_mock_observation(face_obs_deadzone)
    angle_before = running_app.servo.current_angle
    running_app.tick(now)
    assert abs(running_app.servo.current_angle - angle_before) < 1e-3


def test_07_lost_target_timeout_recenter(running_app):
    """测试项 7: 丢脸超过 lost_timeout_s 成功触发超时保护，舵机安全归中 0.0° 并返回 IDLE。"""
    now = time.monotonic()
    clap = AudioEvent(now, -35.0, "left", 0.85, "gcc_phat")
    running_app.audio.event_queue.put(clap)
    running_app.tick(now)
    running_app.tick(now)
    now += running_app.turn_settle_s + 0.05
    running_app.tick(now)

    face_obs_lost = VisionObservation(
        timestamp_mono=now,
        face_found=False,
        dx_px=0.0,
        bbox=(0, 0, 0, 0),
        confidence=0.0,
        fps=15.0,
    )
    running_app.vision.set_mock_observation(face_obs_lost)
    now += running_app.lost_timeout_s + 0.1
    running_app.tick(now)

    assert running_app.state == SystemState.IDLE
    assert abs(running_app.servo.current_angle - 0.0) < 1e-3


def test_08_safe_shutdown(app_config):
    """测试项 8: 系统资源与管线按序释放，舵机 PWM 成功关闭。"""
    app = create_app(app_config, dry_run=True)
    assert app.start()
    app.stop()
    assert not app.running


if __name__ == "__main__":
    import sys
    success = run_simulation_test()
    sys.exit(0 if success else 1)
