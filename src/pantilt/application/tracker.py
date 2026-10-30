"""视听融合声源定位与目标跟踪应用控制流程。"""
import logging
import time
from typing import Any, Dict, Optional

from pantilt.adapters.actuation.laser import LaserIndicator
from pantilt.adapters.actuation.servo import ServoController
from pantilt.adapters.perception.audio import AudioPipeline
from pantilt.adapters.perception.vision import VisionPipeline
from pantilt.adapters.runtime.console import ConsoleListener
from pantilt.domain.controller import DeadzoneStepController
from pantilt.domain.state_machine import TrackerStateMachine
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation

logger = logging.getLogger("App")


class PanTiltTrackerApp:
    """
    云台主控程序：组合根。
    组装感知（音频/视觉）、决策（死区控制器/三态状态机）、执行（总线舵机/激光联锁）与终端交互。
    """

    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

        cfg_ctrl = self.config.get("control", {})
        cfg_servo = self.config.get("servo", {})
        cfg_audio = self.config.get("audio", {})
        cfg_camera = self.config.get("camera", {})
        cfg_laser = self.config.get("laser", {})

        self.main_loop_hz = cfg_ctrl.get("main_loop_hz", 30)
        self.heartbeat_interval_s = 2.0

        # 组件装配
        self.servo = ServoController(cfg_servo, dry_run=self.dry_run)
        self.audio = AudioPipeline(cfg_audio, dry_run=self.dry_run)
        self.vision = VisionPipeline(cfg_camera, dry_run=self.dry_run)
        self.controller = DeadzoneStepController(cfg_ctrl, cfg_servo)
        self.laser = LaserIndicator(cfg_laser, dry_run=self.dry_run)
        self.state_machine = TrackerStateMachine(cfg_ctrl, cfg_laser)

        self.console = ConsoleListener(on_center=self._handle_console_center, on_quit=self.stop)

        self.running = False
        self.last_heartbeat_mono = 0.0
        self.last_audio_event: Optional[AudioEvent] = None
        self.last_vision_obs: Optional[VisionObservation] = None

    # 兼容性属性代理
    @property
    def state(self) -> SystemState:
        return self.state_machine.state

    @state.setter
    def state(self, value: SystemState):
        self.state_machine.state = value

    @property
    def laser_enabled(self) -> bool:
        return self.laser.enabled

    @property
    def laser_is_on(self) -> bool:
        return self.laser.is_on

    @property
    def turn_settle_s(self) -> float:
        return self.state_machine.turn_settle_s

    @property
    def turn_timeout_s(self) -> float:
        return self.state_machine.turn_timeout_s

    @property
    def lost_timeout_s(self) -> float:
        return self.state_machine.lost_timeout_s

    @property
    def turn_target_angle(self) -> float:
        return self.state_machine.turn_target_angle

    @property
    def last_face_mono(self) -> float:
        return self.state_machine.last_face_mono

    @last_face_mono.setter
    def last_face_mono(self, val: float):
        self.state_machine.last_face_mono = val

    def _set_laser(self, enable: bool, now: Optional[float] = None):
        """兼容旧接口的激光控制调用。"""
        self.laser.set_laser(enable, now)

    def _handle_console_center(self):
        self.laser.reset()
        self.servo.center()
        self.state_machine.reset(time.monotonic())

    def start(self) -> bool:
        """启动各子系统并准备进入主控循环。"""
        logger.info("正在启动云台主控系统...")
        if not self.audio.start():
            logger.error("音频管线启动失败，系统安全退出。")
            self.stop()
            return False

        if not self.vision.start():
            logger.error("视觉管线启动失败，系统安全退出。")
            self.stop()
            return False

        self.servo.center()
        self.running = True
        now = time.monotonic()
        self.state_machine.reset(now)
        self.last_heartbeat_mono = now
        self.console.start()
        logger.info("云台系统启动成功，当前状态: IDLE (监听环境中...)")
        return True

    def stop(self):
        """按规范顺序安全停机：熄灭激光 -> 停视觉 -> 停音频 -> 舵机回中释放。"""
        if not self.running and not self.audio.running and not self.vision.running:
            return
        logger.info("正在安全停止系统...")
        self.running = False
        self.console.stop()

        try:
            self.laser.disable()
        except Exception as e:
            logger.error(f"关闭激光器异常: {e}")

        try:
            self.vision.stop()
        except Exception as e:
            logger.error(f"停止视觉管线异常: {e}")

        try:
            self.audio.stop()
        except Exception as e:
            logger.error(f"停止音频管线异常: {e}")

        try:
            self.servo.center()
            self.servo.disable()
        except Exception as e:
            logger.error(f"舵机断电安全处理异常: {e}")

        logger.info("所有设备与资源已释放，系统安全退出。")

    def tick(self, now: float):
        """主循环单步演进：拉取感知 -> 状态机演进 -> 执行机构下发。"""
        # 1. 周期心跳日志
        if now - self.last_heartbeat_mono >= self.heartbeat_interval_s:
            self.last_heartbeat_mono = now
            obs_age = (
                f"{now - self.last_vision_obs.timestamp_mono:.2f}s"
                if self.last_vision_obs
                else "无"
            )
            lost_dur = (
                f"{now - self.last_face_mono:.1f}s"
                if self.state == SystemState.FOLLOW
                else "N/A"
            )
            logger.info(
                f"[心跳] 状态: {self.state.value:<9s} | 舵机角度: {self.servo.current_angle:>5.1f}° | "
                f"最新事件: {self.last_audio_event.side if self.last_audio_event else '无':<6s} | "
                f"观测时延: {obs_age:<6s} | 丢脸时长: {lost_dur}"
            )

        # 2. 采样输入
        audio_ev = self.audio.get_latest_event(block=False)
        if audio_ev:
            self.last_audio_event = audio_ev

        obs = self.vision.get_latest_observation()
        if obs:
            self.last_vision_obs = obs

        # 3. 状态机演进
        res = self.state_machine.step(
            now=now,
            audio_event=audio_ev,
            vision_obs=obs,
            current_angle=self.servo.current_angle,
            controller=self.controller,
        )

        # 4. 执行决策
        if res.drain_audio:
            while self.audio.get_latest_event(block=False):
                pass

        if res.servo_action == "set_angle":
            self.servo.set_angle(res.target_angle)
        elif res.servo_action == "step":
            self.servo.step(res.delta_yaw, res.delta_pitch)
        elif res.servo_action == "center":
            self.servo.center()

        if res.laser_enable is not None:
            self.laser.set_laser(res.laser_enable, now)

    def run(self) -> int:
        """主循环执行体。"""
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


__all__ = ["PanTiltTrackerApp"]
