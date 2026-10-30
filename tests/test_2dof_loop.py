"""二维总线云台与激光瞄准联动脱机确定性验收测试 (2-DOF)。"""
import time

from pantilt.application.tracker import PanTiltTrackerApp
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.logging_setup import setup_logger
from pantilt.infrastructure.paths import DEFAULT_CONFIG


def test_2dof_tracking_and_laser_interlock():
    """验证 2-DOF 双轴闭环与激光安全联锁完整链路。"""
    config = load_config(DEFAULT_CONFIG)
    app = PanTiltTrackerApp(config, dry_run=True)
    assert app.start()

    try:
        now = time.monotonic()

        # 1. 验证双轴初始状态
        assert app.state == SystemState.IDLE
        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 0.0) < 1e-3 and abs(pitch - 0.0) < 1e-3
        assert not app.laser_is_on

        # 2. 模拟声学开环转向 (右偏 30度)
        clap = AudioEvent(now, 30.0, "right", 0.9, "gcc_phat")
        app.audio.event_queue.put(clap)
        app.tick(now)
        assert app.state == SystemState.TURN_ONCE
        assert abs(app.servo.current_yaw - 30.0) < 1e-3

        # 3. 转向到位平息后切入 FOLLOW
        app.tick(now)
        now += app.turn_settle_s + 0.05
        app.tick(now)
        assert app.state == SystemState.FOLLOW

        # 4. 注入 2-DOF 视觉偏差 (dx=-50px 偏左, dy=-40px 偏上)
        obs_move = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=-50.0,
            bbox=(100, 80, 60, 60),
            confidence=1.0,
            fps=120.0,
            dy_px=-40.0,
            target_id=10,
        )
        app.vision.set_mock_observation(obs_move)
        app.tick(now)

        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 28.0) < 1e-3
        assert abs(pitch - 1.5) < 1e-3
        assert not app.laser_is_on

        # 5. 注入死区内观测 (dx=5px, dy=3px)，模拟连续 3 帧锁定
        obs_lock = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=5.0,
            bbox=(315, 195, 60, 60),
            confidence=1.0,
            fps=120.0,
            dy_px=3.0,
            target_id=10,
        )
        app.vision.set_mock_observation(obs_lock)
        for _ in range(3):
            now = time.monotonic()
            app.tick(now)

        assert app.laser_is_on

        # 6. 目标脱靶/丢失，模拟超时回中与激光熄灭
        obs_lost = VisionObservation(
            timestamp_mono=now,
            face_found=False,
            dx_px=0.0,
            bbox=(0, 0, 0, 0),
            confidence=0.0,
            fps=120.0,
        )
        app.vision.set_mock_observation(obs_lost)
        now += app.lost_timeout_s + 0.5
        app.tick(now)
        assert app.state == SystemState.IDLE
        assert not app.laser_is_on
        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 0.0) < 1e-3 and abs(pitch - 0.0) < 1e-3
    finally:
        app.stop()


def main():
    config = load_config(DEFAULT_CONFIG)
    setup_logger(config)

    print("\n==================================================")
    print("      二维总线云台与激光指示脱机闭环测试 (2-DOF)      ")
    print("==================================================")

    test_2dof_tracking_and_laser_interlock()

    print("\n----------------- 验收结果详情 -----------------")
    print("  ✅ 测试项 1: 双轴冷启动成功，Yaw/Pitch 归中 (0°, 0°)，激光关闭")
    print("  ✅ 测试项 2: 声学事件开环驱动偏航转向 +30.0°")
    print("  ✅ 测试项 3: 转向平息完成，切入 FOLLOW 状态")
    print("  ✅ 测试项 4: 2-DOF 视觉偏差联动步进成功 (Yaw: 30°->28°, Pitch: 0°->1.5°)")
    print("  ✅ 测试项 5: 目标连续稳定在两轴死区准星内，50mW 激光器成功触发点亮！")
    print("  ✅ 测试项 6: 目标丢失超时，激光安全熄灭且两轴安全归中 (0°, 0°)")
    print("--------------------------------------------------")
    print("🎉 恭喜！二维总线云台与激光指示 6 项脱机测试 100% 通过！\n")


if __name__ == "__main__":
    main()
