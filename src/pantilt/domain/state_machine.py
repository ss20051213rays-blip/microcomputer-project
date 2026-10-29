"""三态状态机转移与决策领域逻辑 (零 IO、纯业务逻辑)。"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pantilt.core.types import AudioEvent, SystemState, VisionObservation
from pantilt.domain.controller import DeadzoneStepController

logger = logging.getLogger("App")


@dataclass
class StateMachineResult:
    """状态机单步演进输出决策。"""

    state: SystemState
    servo_action: Optional[str] = None  # "set_angle", "step", "center", None
    target_angle: float = 0.0
    delta_yaw: float = 0.0
    delta_pitch: float = 0.0
    laser_enable: Optional[bool] = None
    drain_audio: bool = False
    in_deadzone: bool = False


class TrackerStateMachine:
    """
    视听融合三态状态机转移表：
    IDLE --(声学开环)--> TURN_ONCE --(视觉接管)--> FOLLOW --(丢失超时)--> IDLE
    纯领域逻辑：零硬件依赖、零 IO、输入数据出决策。
    """

    def __init__(
        self,
        config_control: Optional[Dict[str, Any]] = None,
        config_laser: Optional[Dict[str, Any]] = None,
    ):
        cfg_ctrl = config_control or {}
        cfg_laser = config_laser or {}

        self.turn_timeout_s = float(cfg_ctrl.get("turn_timeout_s", 1.5))
        self.lost_timeout_s = float(cfg_ctrl.get("lost_timeout_s", 3.0))
        self.turn_settle_s = float(cfg_ctrl.get("turn_settle_s", 0.3))

        self.laser_enabled = bool(cfg_laser.get("enabled", False))
        self.laser_lock_frames = int(cfg_laser.get("lock_min_frames", 3))

        # 状态机内部时序与转移变量
        self.state = SystemState.IDLE
        self.turn_target_angle = 0.0
        self.turn_start_mono = 0.0
        self.turn_settle_start_mono: Optional[float] = None
        self.last_face_mono = 0.0
        self.locked_frames_count = 0

    def reset(self, now: float = 0.0):
        """复位状态机到 IDLE 初始态。"""
        self.state = SystemState.IDLE
        self.turn_target_angle = 0.0
        self.turn_start_mono = 0.0
        self.turn_settle_start_mono = None
        self.last_face_mono = now
        self.locked_frames_count = 0

    def step(
        self,
        now: float,
        audio_event: Optional[AudioEvent],
        vision_obs: Optional[VisionObservation],
        current_angle: float,
        controller: DeadzoneStepController,
    ) -> StateMachineResult:
        """根据当前状态与输入数据演进状态机。"""
        res = StateMachineResult(state=self.state)

        if self.state == SystemState.IDLE:
            if audio_event:
                target_angle = audio_event.theta_audio_deg
                logger.info(
                    f"[状态转移] IDLE -> TURN_ONCE | 检测到拍手: 方位={audio_event.side}, "
                    f"估计角度={audio_event.theta_audio_deg:+.1f}°, 置信度={audio_event.confidence:.2f}, "
                    f"算法={audio_event.method} -> 转向目标角: {target_angle:.1f}°"
                )
                self.turn_target_angle = target_angle
                self.turn_start_mono = now
                self.turn_settle_start_mono = None
                self.state = SystemState.TURN_ONCE

                res.state = self.state
                res.servo_action = "set_angle"
                res.target_angle = self.turn_target_angle

        elif self.state == SystemState.TURN_ONCE:
            res.drain_audio = True
            elapsed = now - self.turn_start_mono
            angle_err = abs(current_angle - self.turn_target_angle)

            if angle_err <= 0.5:
                if self.turn_settle_start_mono is None:
                    self.turn_settle_start_mono = now
                elif now - self.turn_settle_start_mono >= self.turn_settle_s:
                    logger.info(
                        f"[状态转移] TURN_ONCE -> FOLLOW | 舵机已到位 ({current_angle:.1f}°) "
                        f"且稳定平息 {self.turn_settle_s}s，切入视觉接管。"
                    )
                    self.state = SystemState.FOLLOW
                    self.last_face_mono = now
                    res.state = self.state
            elif elapsed >= self.turn_timeout_s:
                logger.warning(
                    f"[状态转移] TURN_ONCE -> FOLLOW | 转向到达超时上限 ({self.turn_timeout_s}s)，"
                    f"强制切入视觉接管。当前角度: {current_angle:.1f}°"
                )
                self.state = SystemState.FOLLOW
                self.last_face_mono = now
                res.state = self.state

        elif self.state == SystemState.FOLLOW:
            res.drain_audio = True

            if vision_obs:
                if vision_obs.face_found:
                    self.last_face_mono = now
                    delta_yaw, delta_pitch = controller.compute_steps(vision_obs)
                    if delta_yaw != 0.0 or delta_pitch != 0.0:
                        res.servo_action = "step"
                        res.delta_yaw = delta_yaw
                        res.delta_pitch = delta_pitch
                        self.locked_frames_count = 0
                        res.laser_enable = False
                        res.in_deadzone = False
                        logger.debug(
                            f"[视觉跟随] dx={vision_obs.dx_px:>+5.1f}px, "
                            f"dy={getattr(vision_obs, 'dy_px', 0.0):>+5.1f}px -> "
                            f"步进: Yaw {delta_yaw:>+4.1f}°, Pitch {delta_pitch:>+4.1f}°"
                        )
                    else:
                        # 目标落入两轴死区准星中心
                        self.locked_frames_count += 1
                        res.in_deadzone = True
                        if self.locked_frames_count >= self.laser_lock_frames:
                            res.laser_enable = True
                else:
                    self.locked_frames_count = 0
                    res.laser_enable = False
                    res.in_deadzone = False

            time_lost = now - self.last_face_mono
            if time_lost >= self.lost_timeout_s:
                logger.info(
                    f"[状态转移] FOLLOW -> IDLE | 连续丢失目标超过 {time_lost:.1f}s >= {self.lost_timeout_s}s。"
                    f"熄灭激光、舵机安全回中并恢复声音监听。"
                )
                self.state = SystemState.IDLE
                self.locked_frames_count = 0
                res.state = self.state
                res.laser_enable = False
                res.servo_action = "center"

        return res


__all__ = ["TrackerStateMachine", "StateMachineResult"]

