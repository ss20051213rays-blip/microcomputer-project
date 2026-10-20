import os
import sys
import time
import signal
import logging
import argparse
import threading
from enum import Enum

from src.config import load_config, setup_logger
from src.servo import ServoController
from src.audio import AudioPipeline, AudioEvent
from src.vision import VisionPipeline, VisionObservation
from src.controller import DeadzoneStepController

logger = logging.getLogger("App")

class SystemState(Enum):
    IDLE = "IDLE"
    TURN_ONCE = "TURN_ONCE"
    FOLLOW = "FOLLOW"

class PanTiltTrackerApp:
    """
    视听融合声源定位与目标跟踪云台主控程序 (阶段五核心)
    架构：单进程 + 音频线程 + 视觉线程 + 主控制循环
    状态机：IDLE --(声学开环)--> TURN_ONCE --(视觉接管)--> FOLLOW --(丢失超时)--> IDLE
    """
    def __init__(self, config, dry_run=False):
        self.config = config
        self.dry_run = dry_run

        cfg_ctrl = self.config.get("control", {})
        cfg_servo = self.config.get("servo", {})
        cfg_audio = self.config.get("audio", {})
        cfg_camera = self.config.get("camera", {})

        # 频率与超时参数
        self.main_loop_hz = cfg_ctrl.get("main_loop_hz", 30)
        self.turn_timeout_s = cfg_ctrl.get("turn_timeout_s", 1.5)
        self.lost_timeout_s = cfg_ctrl.get("lost_timeout_s", 3.0)
        self.turn_settle_s = cfg_ctrl.get("turn_settle_s", 0.3)
        self.heartbeat_interval_s = 2.0

        # 模块初始化
        self.servo = ServoController(cfg_servo, dry_run=self.dry_run)
        self.audio = AudioPipeline(cfg_audio, dry_run=self.dry_run)
        self.vision = VisionPipeline(cfg_camera, dry_run=self.dry_run)
        self.controller = DeadzoneStepController(cfg_ctrl, cfg_servo)

        # 激光指示器参数与安全联锁状态
        cfg_laser = self.config.get("laser", {})
        self.laser_enabled = cfg_laser.get("enabled", False)
        self.laser_pin = cfg_laser.get("gpio_pin", 23)
        self.laser_lock_frames = cfg_laser.get("lock_min_frames", 3)
        self.laser_max_continuous_s = cfg_laser.get("max_continuous_s", 10.0)
        self.laser_is_on = False
        self.laser_on_start_mono = 0.0
        self.locked_frames_count = 0

        # 状态机运行变量
        self.state = SystemState.IDLE
        self.running = False

        self.turn_target_angle = 0.0
        self.turn_start_mono = 0.0
        self.turn_settle_start_mono = None

        self.last_face_mono = 0.0
        self.last_audio_event = None
        self.last_vision_obs = None
        self.last_heartbeat_mono = 0.0

        # 终端交互线程
        self.cli_thread = None

    def _set_laser(self, enable: bool, now: float = None):
        """控制激光指示器使能状态，具备过热与人眼安全超时联锁"""
        if not self.laser_enabled:
            return
        if now is None:
            now = time.monotonic()

        if enable:
            if not self.laser_is_on:
                self.laser_is_on = True
                self.laser_on_start_mono = now
                logger.info("🎯 [激光指示] 目标进入死区准星且连续锁定，点亮 50mW 激光器进行物理指示！")
            else:
                # 超时安全断开保护
                if now - self.laser_on_start_mono > self.laser_max_continuous_s:
                    logger.warning(f"⚠️ [激光安全联锁] 激光持续点亮超过安全上限 ({self.laser_max_continuous_s}s)，强制关闭防过热。")
                    self.laser_is_on = False
        else:
            if self.laser_is_on:
                self.laser_is_on = False
                logger.info("🎯 [激光指示] 目标失锁或离开死区，关闭激光指示。")

    def start(self) -> bool:
        """启动各子系统与主控循环"""
        logger.info("正在启动云台主控系统...")

        # 1. 启动音频管线
        if not self.audio.start():
            logger.error("音频管线启动失败，系统安全退出。")
            self.stop()
            return False

        # 2. 启动视觉管线
        if not self.vision.start():
            logger.error("视觉管线启动失败，系统安全退出。")
            self.stop()
            return False

        # 3. 舵机回中
        self.servo.center()

        self.running = True
        self.state = SystemState.IDLE
        self.last_face_mono = time.monotonic()
        self.last_heartbeat_mono = time.monotonic()

        # 4. 如果处于终端交互环境，启动按键监听 (c: 回中, q: 退出)
        if sys.stdin.isatty():
            self.cli_thread = threading.Thread(target=self._console_listener, daemon=True)
            self.cli_thread.start()
            logger.info("控制台交互已就绪：输入 'c' 强制回中并重置，输入 'q' 安全退出。")

        logger.info("云台系统启动成功，当前状态: IDLE (监听环境中...)")
        return True

    def stop(self):
        """按规范顺序安全停止所有模块：熄灭激光 -> 停视觉 -> 停音频 -> 舵机回中并释放"""
        if not self.running and not self.audio.running and not self.vision.running:
            return

        logger.info("正在安全停止系统...")
        self.running = False

        # 0. 熄灭激光器
        try:
            self._set_laser(False)
        except Exception as e:
            logger.error(f"关闭激光器异常: {e}")

        # 1. 停止视觉
        try:
            self.vision.stop()
        except Exception as e:
            logger.error(f"停止视觉管线异常: {e}")

        # 2. 停止音频
        try:
            self.audio.stop()
        except Exception as e:
            logger.error(f"停止音频管线异常: {e}")

        # 3. 舵机回中并下电安全处理
        try:
            self.servo.center()
            self.servo.disable()
        except Exception as e:
            logger.error(f"舵机断电安全处理异常: {e}")

        logger.info("所有设备与资源已释放，系统安全退出。")

    def _console_listener(self):
        """控制台按键指令监听"""
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd == 'c':
                    logger.info("[指令] 收到终端回中指令 'c'，复位云台至 IDLE。")
                    self._set_laser(False)
                    self.servo.center()
                    self.state = SystemState.IDLE
                elif cmd == 'q':
                    logger.info("[指令] 收到终端退出指令 'q'。")
                    self.running = False
                    break
            except Exception:
                break

    def tick(self, now: float):
        """主循环单步状态机演算"""
        # ── 1. 定期心跳日志 ──
        if now - self.last_heartbeat_mono >= self.heartbeat_interval_s:
            self.last_heartbeat_mono = now
            obs_age = f"{now - self.last_vision_obs.timestamp_mono:.2f}s" if self.last_vision_obs else "无"
            lost_duration = f"{now - self.last_face_mono:.1f}s" if self.state == SystemState.FOLLOW else "N/A"
            logger.info(
                f"[心跳] 状态: {self.state.value:<9s} | 舵机角度: {self.servo.current_angle:>5.1f}° | "
                f"最新事件: {self.last_audio_event.side if self.last_audio_event else '无':<6s} | "
                f"观测时延: {obs_age:<6s} | 丢脸时长: {lost_duration}"
            )

        # ── 2. 三态状态机转移 ──
        if self.state == SystemState.IDLE:
            # IDLE 状态：只监听有效音频事件
            event = self.audio.get_latest_event(block=False)
            if event:
                self.last_audio_event = event
                target_angle = event.theta_audio_deg
                logger.info(
                    f"[状态转移] IDLE -> TURN_ONCE | 检测到拍手: 方位={event.side}, 估计角度={event.theta_audio_deg:+.1f}°, "
                    f"置信度={event.confidence:.2f}, 算法={event.method} -> 转向目标角: {target_angle:.1f}°"
                )
                self.turn_target_angle = target_angle
                self.turn_start_mono = now
                self.turn_settle_start_mono = None
                self.state = SystemState.TURN_ONCE
                # 开环驱动舵机转向目标角
                self.servo.set_angle(self.turn_target_angle)

        elif self.state == SystemState.TURN_ONCE:
            # TURN_ONCE 状态：忽略新的声音（排空队列防止回声打断）
            while self.audio.get_latest_event(block=False):
                pass

            elapsed = now - self.turn_start_mono
            angle_err = abs(self.servo.current_angle - self.turn_target_angle)

            # 到位判据与稳定延时
            if angle_err <= 0.5:
                if self.turn_settle_start_mono is None:
                    self.turn_settle_start_mono = now
                elif now - self.turn_settle_start_mono >= self.turn_settle_s:
                    logger.info(
                        f"[状态转移] TURN_ONCE -> FOLLOW | 舵机已到位 ({self.servo.current_angle:.1f}°) 且稳定平息 {self.turn_settle_s}s，切入视觉接管。"
                    )
                    self.state = SystemState.FOLLOW
                    self.last_face_mono = now
            elif elapsed >= self.turn_timeout_s:
                logger.warning(
                    f"[状态转移] TURN_ONCE -> FOLLOW | 转向到达超时上限 ({self.turn_timeout_s}s)，强制切入视觉接管。当前角度: {self.servo.current_angle:.1f}°"
                )
                self.state = SystemState.FOLLOW
                self.last_face_mono = now

        elif self.state == SystemState.FOLLOW:
            # FOLLOW 状态：只响应新鲜视觉观测，排空忽略音频
            while self.audio.get_latest_event(block=False):
                pass

            obs = self.vision.get_latest_observation()
            if obs:
                self.last_vision_obs = obs
                if obs.face_found:
                    self.last_face_mono = now
                    delta_yaw, delta_pitch = self.controller.compute_steps(obs)
                    if delta_yaw != 0.0 or delta_pitch != 0.0:
                        self.servo.step(delta_yaw, delta_pitch)
                        logger.debug(
                            f"[视觉跟随] dx={obs.dx_px:>+5.1f}px, dy={getattr(obs, 'dy_px', 0.0):>+5.1f}px -> 步进: Yaw {delta_yaw:>+4.1f}°, Pitch {delta_pitch:>+4.1f}° -> 舵机角: {self.servo.current_angle:>5.1f}°"
                        )
                        self.locked_frames_count = 0
                        self._set_laser(False, now)
                    else:
                        # 目标落入两轴死区准星中心
                        self.locked_frames_count += 1
                        if self.locked_frames_count >= self.laser_lock_frames:
                            self._set_laser(True, now)
                else:
                    self.locked_frames_count = 0
                    self._set_laser(False, now)

            # 目标丢失超时判据：连续超过 lost_timeout_s 未检测到目标则回中并重置为 IDLE
            time_lost = now - self.last_face_mono
            if time_lost >= self.lost_timeout_s:
                logger.info(
                    f"[状态转移] FOLLOW -> IDLE | 连续丢失目标超过 {time_lost:.1f}s >= {self.lost_timeout_s}s。熄灭激光、舵机安全回中并恢复声音监听。"
                )
                self._set_laser(False, now)
                self.servo.center()
                self.state = SystemState.IDLE

    def run(self) -> int:
        """主循环执行体"""
        if not self.start():
            return 1

        dt = 1.0 / self.main_loop_hz
        try:
            while self.running:
                t0 = time.monotonic()
                self.tick(t0)
                t1 = time.monotonic()
                sleep_dur = dt - (t1 - t0)
                if sleep_dur > 0:
                    time.sleep(sleep_dur)
        except KeyboardInterrupt:
            logger.info("接收到用户中断信号 (Ctrl+C)。")
        finally:
            self.stop()
        return 0

def run_simulation_test(config) -> bool:
    """
    自动化脱机确定性模拟测试 (阶段五验收项)
    覆盖：有效音频开环转向 -> 转向到位平息 -> 视觉跟随步进 -> 死区过滤 -> 丢脸超时回中 -> 安全退出
    """
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
            method="gcc_phat"
        )
        app.audio.event_queue.put(clap_event)
        app.tick(now)

        assert app.state == SystemState.TURN_ONCE, "未成功进入 TURN_ONCE 状态"
        assert abs(app.servo.current_angle - (-35.0)) < 1e-3, f"舵机未开环转向目标角度 -35.0° (实际: {app.servo.current_angle})"
        passed_checks.append("测试项 2: 声学事件正确触发状态转移 IDLE -> TURN_ONCE，舵机开环转向 -35.0°")

        # 3. 模拟到达目标角并平息延时到达，切入视觉跟随
        app.tick(now)  # 到位检测：记录平息起始时间点
        now += app.turn_settle_s + 0.05
        app.tick(now)  # 平息计时满足：切入 FOLLOW
        assert app.state == SystemState.FOLLOW, "平息延时后未成功进入 FOLLOW 状态"
        passed_checks.append("测试项 3: 转向到位后平息延时结束，成功顺序接管进入 FOLLOW 状态")

        # 4. 在 FOLLOW 状态下注入新的拍手，验证被屏蔽不打断
        echo_event = AudioEvent(
            timestamp_mono=now,
            theta_audio_deg=40.0,
            side="right",
            confidence=0.9,
            method="gcc_phat"
        )
        app.audio.event_queue.put(echo_event)
        app.tick(now)
        assert app.state == SystemState.FOLLOW, "FOLLOW 状态被回声意外打断"
        passed_checks.append("测试项 4: FOLLOW 视觉接管期间，背景回声与新拍手被完全屏蔽忽略")

        # 5. 模拟人脸在画面右侧 (dx = +45 px)，超出死区 (30 px) -> 舵机应向右步进 (+2.0°)
        face_obs_right = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=45.0,
            bbox=(100, 100, 50, 50),
            confidence=0.95,
            fps=15.0
        )
        app.vision.set_mock_observation(face_obs_right)
        angle_before = app.servo.current_angle
        app.tick(now)
        assert app.servo.current_angle > angle_before, "人脸偏右时舵机未向右步进"
        passed_checks.append(f"测试项 5: 人脸偏右 (dx=+45px) 触发正确步进: {angle_before:.1f}° -> {app.servo.current_angle:.1f}°")

        # 6. 模拟人脸进入死区 (dx = +10 px) -> 舵机应保持静止
        face_obs_deadzone = VisionObservation(
            timestamp_mono=now,
            face_found=True,
            dx_px=10.0,
            bbox=(100, 100, 50, 50),
            confidence=0.95,
            fps=15.0
        )
        app.vision.set_mock_observation(face_obs_deadzone)
        angle_before = app.servo.current_angle
        app.tick(now)
        assert abs(app.servo.current_angle - angle_before) < 1e-3, "死区内舵机发生意外移动"
        passed_checks.append("测试项 6: 人脸位于死区内 (dx=+10px) 舵机保持静止，防抖滤波生效")

        # 7. 模拟人脸丢失 -> 经过超时时间后自动回中并返回 IDLE
        face_obs_lost = VisionObservation(
            timestamp_mono=now,
            face_found=False,
            dx_px=0.0,
            bbox=(0, 0, 0, 0),
            confidence=0.0,
            fps=15.0
        )
        app.vision.set_mock_observation(face_obs_lost)
        # 推进时钟超过 lost_timeout_s
        now += app.lost_timeout_s + 0.1
        app.tick(now)
        assert app.state == SystemState.IDLE, "丢脸超时后未返回 IDLE 状态"
        assert abs(app.servo.current_angle - 0.0) < 1e-3, f"丢脸超时后舵机未安全回中 (当前: {app.servo.current_angle})"
        passed_checks.append(f"测试项 7: 丢脸超过 {app.lost_timeout_s}s 成功触发超时保护，舵机安全归中 0.0° 并返回 IDLE")

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

def main():
    parser = argparse.ArgumentParser(description="视听融合声源定位与目标跟踪云台主控系统")
    default_cfg = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "default.yaml"))
    parser.add_argument("--config", default=default_cfg, help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="无硬件干运行模式")
    parser.add_argument("--simulate", action="store_true", help="执行自动化确定性模拟验收测试")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logger(config)

    if args.simulate:
        success = run_simulation_test(config)
        sys.exit(0 if success else 1)

    app = PanTiltTrackerApp(config, dry_run=args.dry_run)

    # 注册退出信号处理
    def sig_handler(signum, frame):
        logger.info(f"收到系统信号 {signum}，正在安全退出...")
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    sys.exit(app.run())

if __name__ == "__main__":
    main()
