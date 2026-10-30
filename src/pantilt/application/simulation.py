"""视听融合状态机脱机模拟验收逻辑。"""
import time
from typing import Any, Dict, Optional

from pantilt.application.tracker import PanTiltTrackerApp
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.paths import DEFAULT_CONFIG


def run_simulation_test(config: Optional[Dict[str, Any]] = None) -> bool:
    """
    自动化脱机确定性模拟测试 (阶段五验收项，兼容 CLI 与旧脚本)。
    覆盖：有效音频开环转向 -> 转向到位平息 -> 视觉跟随步进 -> 死区过滤 -> 丢脸超时回中 -> 安全退出
    """
    if config is None:
        config = load_config(DEFAULT_CONFIG)

    print("\n==================================================")
    print("      视听融合状态机脱机确定性模拟验收测试 (Phase 5)      ")
    print("==================================================")

    app = PanTiltTrackerApp(config, dry_run=True)
    if not app.start():
        print("[FAIL] app.start() 失败！")
        return False

    passed_checks = []

    try:
        now = time.monotonic()

        # 1. 验证初始状态
        assert app.state == SystemState.IDLE, "初始状态不为 IDLE"
        assert abs(app.servo.current_angle - 0.0) < 1e-3, "初始舵机角度未回中"
        passed_checks.append("测试项 1: 系统冷启动成功，初始状态为 IDLE，舵机归中 0.0°")

        # 2. 模拟声学事件触发转向 (左侧 -35度)
        clap_event = AudioEvent(
            timestamp_mono=now,
            theta_audio_deg=-35.0,
            side="left",
            confidence=0.85,
            method="gcc_phat",
        )
        app.audio.event_queue.put(clap_event)
        app.tick(now)

        assert app.state == SystemState.TURN_ONCE, "未成功进入 TURN_ONCE 状态"
        assert abs(app.servo.current_angle - (-35.0)) < 1e-3, (
            f"舵机未开环转向目标角度 -35.0° (实际: {app.servo.current_angle})"
        )
        passed_checks.append("测试项 2: 声学事件正确触发状态转移 IDLE -> TURN_ONCE，舵机开环转向 -35.0°")

        # 3. 模拟到达目标角并平息延时到达，切入视觉跟随
        app.tick(now)
        now += app.turn_settle_s + 0.05
        app.tick(now)
        assert app.state == SystemState.FOLLOW, "平息延时后未成功进入 FOLLOW 状态"
        passed_checks.append("测试项 3: 转向到位后平息延时结束，成功顺序接管进入 FOLLOW 状态")

        # 4. 在 FOLLOW 状态下注入新的拍手，验证被屏蔽不打断
        echo_event = AudioEvent(
            timestamp_mono=now,
            theta_audio_deg=40.0,
            side="right",
            confidence=0.9,
            method="gcc_phat",
        )
        app.audio.event_queue.put(echo_event)
        app.tick(now)
        assert app.state == SystemState.FOLLOW, "FOLLOW 状态被回声意外打断"
        passed_checks.append("测试项 4: FOLLOW 视觉接管期间，背景回声与新拍手被完全屏蔽忽略")

        # 5. 模拟人脸在画面右侧 (dx = +45 px) -> 步进
        face_obs_right = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=45.0,
            bbox=(100, 100, 50, 50),
            confidence=0.95,
            fps=15.0,
        )
        app.vision.set_mock_observation(face_obs_right)
        angle_before = app.servo.current_angle
        app.tick(now)
        assert app.servo.current_angle > angle_before, "人脸偏右时舵机未向右步进"
        passed_checks.append(
            f"测试项 5: 人脸偏右 (dx=+45px) 触发正确步进: {angle_before:.1f}° -> {app.servo.current_angle:.1f}°"
        )

        # 6. 模拟人脸进入死区 (dx = +10 px) -> 静止
        face_obs_deadzone = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=10.0,
            bbox=(100, 100, 50, 50),
            confidence=0.95,
            fps=15.0,
        )
        app.vision.set_mock_observation(face_obs_deadzone)
        angle_before = app.servo.current_angle
        app.tick(now)
        assert abs(app.servo.current_angle - angle_before) < 1e-3, "死区内舵机发生意外移动"
        passed_checks.append("测试项 6: 人脸位于死区内 (dx=+10px) 舵机保持静止，防抖滤波生效")

        # 7. 模拟人脸丢失 -> 超时回中
        face_obs_lost = VisionObservation(
            timestamp_mono=now,
            face_found=False,
            dx_px=0.0,
            bbox=(0, 0, 0, 0),
            confidence=0.0,
            fps=15.0,
        )
        app.vision.set_mock_observation(face_obs_lost)
        now += app.lost_timeout_s + 0.1
        app.tick(now)
        assert app.state == SystemState.IDLE, "丢脸超时后未返回 IDLE 状态"
        assert abs(app.servo.current_angle - 0.0) < 1e-3, (
            f"丢脸超时后舵机未安全回中 (当前: {app.servo.current_angle})"
        )
        passed_checks.append(
            f"测试项 7: 丢脸超过 {app.lost_timeout_s}s 成功触发超时保护，舵机安全归中 0.0° 并返回 IDLE"
        )

        # 8. 验证安全停止退出
        app.stop()
        assert not app.running, "系统未正常停止"
        passed_checks.append("测试项 8: 系统资源与管线按序释放，舵机 PWM 成功关闭")

    except AssertionError as e:
        print(f"\n❌ [验收未通过]: {e}")
        app.stop()
        return False

    print("\n----------------- 验收结果详情 -----------------")
    for item in passed_checks:
        print(f"  ✅ {item}")
    print("--------------------------------------------------")
    print("🎉 恭喜！阶段五状态机全部 8 项确定性场景测试 100% 通过！\n")
    return True


__all__ = ["run_simulation_test"]
