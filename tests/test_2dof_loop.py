#!/usr/bin/env python3
"""
二维总线云台与激光瞄准联动脱机确定性验收测试
验证：
- 2-DOF (Yaw + Pitch) 双轴闭环步进响应
- 激光器安全联锁：死区稳定锁定触发点亮、脱靶/超时自动关闭
- ArUco / 人脸通用目标观测处理
"""

import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from pantilt.core.config import load_config, setup_logger
from pantilt.app import PanTiltTrackerApp, SystemState
from pantilt.perception.audio import AudioEvent
from pantilt.perception.vision import VisionObservation

def main():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "default.yaml"))
    config = load_config(config_path)
    logger = setup_logger(config)

    print("\n==================================================")
    print("      二维总线云台与激光指示脱机闭环测试 (2-DOF)      ")
    print("==================================================")

    app = PanTiltTrackerApp(config, dry_run=True)
    if not app.start():
        print("[FAIL] app.start() 失败！")
        sys.exit(1)

    checks = []
    try:
        now = time.monotonic()

        # 1. 验证双轴初始状态
        assert app.state == SystemState.IDLE
        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 0.0) < 1e-3 and abs(pitch - 0.0) < 1e-3
        assert not app.laser_is_on
        checks.append("测试项 1: 双轴冷启动成功，Yaw/Pitch 归中 (0°, 0°)，激光关闭")

        # 2. 模拟声学开环转向 (右偏 30度)
        clap = AudioEvent(now, 30.0, "right", 0.9, "gcc_phat")
        app.audio.event_queue.put(clap)
        app.tick(now)
        assert app.state == SystemState.TURN_ONCE
        assert abs(app.servo.current_yaw - 30.0) < 1e-3
        checks.append("测试项 2: 声学事件开环驱动偏航转向 +30.0°")

        # 3. 转向到位平息后切入 FOLLOW
        app.tick(now)
        time.sleep(0.35)
        now = time.monotonic()
        app.tick(now)
        assert app.state == SystemState.FOLLOW
        checks.append("测试项 3: 转向平息完成，切入 FOLLOW 状态")

        # 4. 注入 2-DOF 视觉偏差 (dx=-50px 偏左, dy=-40px 偏上)
        obs_move = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=-50.0,
            bbox=(100, 80, 60, 60),
            confidence=1.0,
            fps=120.0,
            dy_px=-40.0,
            target_id=10
        )
        app.vision.set_mock_observation(obs_move)
        app.tick(now)

        # 步进量：Yaw 应减少 2.0° (从 30° -> 28°)，Pitch 应增加 1.5° (从 0° -> 1.5°)
        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 28.0) < 1e-3, f"Yaw 未正确步进: {yaw}"
        assert abs(pitch - 1.5) < 1e-3, f"Pitch 未正确步进: {pitch}"
        assert not app.laser_is_on, "大偏差运动中激光器不应点亮"
        checks.append("测试项 4: 2-DOF 视觉偏差联动步进成功 (Yaw: 30°->28°, Pitch: 0°->1.5°)")

        # 5. 注入死区内观测 (dx=5px, dy=3px)，模拟连续 3 帧锁定
        obs_lock = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=5.0,
            bbox=(315, 195, 60, 60),
            confidence=1.0,
            fps=120.0,
            dy_px=3.0,
            target_id=10
        )
        app.vision.set_mock_observation(obs_lock)
        for _ in range(3):
            now = time.monotonic()
            app.tick(now)

        assert app.laser_is_on, "稳定在死区准星后激光器应当点亮！"
        checks.append("测试项 5: 目标连续稳定在两轴死区准星内，50mW 激光器成功触发点亮！")

        # 6. 目标脱靶/丢失，模拟超时回中与激光熄灭
        obs_lost = VisionObservation(
            timestamp_mono=now,
            face_found=False,
            dx_px=0.0,
            bbox=(0,0,0,0),
            confidence=0.0,
            fps=120.0
        )
        app.vision.set_mock_observation(obs_lost)
        # 推进时钟超过 lost_timeout_s (3.0s)
        now += 3.5
        app.tick(now)
        assert app.state == SystemState.IDLE
        assert not app.laser_is_on, "超时脱靶后激光器应当立刻熄灭！"
        yaw, pitch = app.servo.get_angles()
        assert abs(yaw - 0.0) < 1e-3 and abs(pitch - 0.0) < 1e-3, "丢靶后两轴应回中"
        checks.append("测试项 6: 目标丢失超时，激光安全熄灭且两轴安全归中 (0°, 0°)")

    finally:
        app.stop()

    print("\n----------------- 验收结果详情 -----------------")
    for check in checks:
        print(f"  ✅ {check}")
    print("--------------------------------------------------")
    print("🎉 恭喜！二维总线云台与激光指示 6 项脱机测试 100% 通过！\n")

if __name__ == "__main__":
    main()

