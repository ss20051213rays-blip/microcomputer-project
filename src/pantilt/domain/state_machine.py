"""四态人脸跟踪状态机（纯业务逻辑，无硬件与 IO 依赖）。"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pantilt.domain.controller import DeadzoneStepController
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation

logger = logging.getLogger("App")


@dataclass
class StateMachineResult:
    """状态机单步演进输出的执行决策。"""
    state: SystemState
    servo_action: Optional[str] = None  # "set_angle", "set_angles", "step", "center", None
    target_angle: float = 0.0
    target_pitch_angle: float = 0.0
    delta_yaw: float = 0.0
    delta_pitch: float = 0.0
    drain_audio: bool = False
    in_deadzone: bool = False


class TrackerStateMachine:
    """IDLE → TURN_AND_RESPOND → SEARCH_FACE → TRACK_FACE 四态流程。

    音频事件在此仅作为触发与粗测向输入；KWS、环形缓存及音箱播放仍由
    阶段 3 实现，本状态机不依赖其具体实现。
    """

    _SWEEP_PATTERN = (0.0, 10.0, 20.0, 10.0, 0.0, -10.0, -20.0, -10.0, 0.0)

    def __init__(self, config_control: Optional[Dict[str, Any]] = None,
                 config_servo: Optional[Dict[str, Any]] = None,
                 config_camera: Optional[Dict[str, Any]] = None):
        cfg = config_control or {}
        servo_cfg = config_servo or {}
        camera_cfg = config_camera or {}
        self.turn_timeout_s = float(cfg.get("turn_timeout_s", 1.5))
        self.turn_settle_s = float(cfg.get("turn_settle_s", 0.3))
        self.search_timeout_s = max(0.0, float(cfg.get("search_timeout_s", 4.5)))
        self.search_sweep_interval_s = max(0.05, float(cfg.get("search_sweep_interval_s", 0.5)))
        self.lost_timeout_s = float(cfg.get("lost_timeout_s", 0.0))  # TRACK_FACE 默认无限等待续跟
        self.min_yaw = float(servo_cfg.get("min_yaw_angle", -90.0))
        self.max_yaw = float(servo_cfg.get("max_yaw_angle", 90.0))
        self.min_pitch = float(servo_cfg.get("min_pitch_angle", -30.0))
        self.max_pitch = float(servo_cfg.get("max_pitch_angle", 45.0))
        requested_pitch = float(cfg.get("search_pitch_deg", 30.0))
        self.search_pitch_angle = max(self.min_pitch, min(self.max_pitch, requested_pitch))
        self.recovery_delay_s = max(0.0, float(cfg.get("recovery_delay_s", 0.12)))
        self.recovery_timeout_s = max(0.0, float(cfg.get("recovery_timeout_s", 1.4)))
        self.recovery_yaw_deg = max(0.0, float(cfg.get("recovery_yaw_deg", 22.0)))
        self.recovery_pitch_deg = max(0.0, float(cfg.get("recovery_pitch_deg", 12.0)))
        self.half_frame_width = float(camera_cfg.get("width", 640)) / 2.0
        self.half_frame_height = float(camera_cfg.get("height", 400)) / 2.0
        self.reset()

    def reset(self, now: float = 0.0):
        """回到待机态并清空阶段时序。"""
        self.state = SystemState.IDLE
        self.turn_target_angle = 0.0
        self.turn_start_mono = 0.0
        self.turn_settle_start_mono = None
        self.search_start_mono = None
        self.search_origin_angle = 0.0
        self.last_face_mono = now
        self._last_face = None
        self._exit_direction = (0, 0)
        self._loss_started = None
        self._recovery_target = None

    def _enter_search(self, now: float, current_angle: float):
        self.state = SystemState.SEARCH_FACE
        self.search_start_mono = now
        self.search_origin_angle = current_angle
        logger.info("[状态转移] -> SEARCH_FACE | 在当前方向检查人脸并执行有限范围微扫。")

    @staticmethod
    def _apply_steps(res, steps):
        delta_yaw, delta_pitch = steps
        res.in_deadzone = delta_yaw == 0.0 and delta_pitch == 0.0
        if not res.in_deadzone:
            res.servo_action = "step"
            res.delta_yaw = delta_yaw
            res.delta_pitch = delta_pitch

    @staticmethod
    def _exit_sign(previous, current, elapsed, half_size):
        if abs(current) >= 0.62 * half_size:
            return 1 if current > 0 else -1
        if 0.0 < elapsed <= 0.25 and abs(current) >= 0.17 * half_size:
            velocity = (current - previous) / elapsed
            if velocity * current > 0.0 and abs(current + 0.18 * velocity) >= 0.58 * half_size:
                return 1 if current > 0 else -1
        return 0

    def _track_observation(self, res, now, observation, controller):
        self.last_face_mono = now
        self._loss_started = None
        self._recovery_target = None
        previous = self._last_face
        if previous is None or observation.timestamp_mono > previous.timestamp_mono:
            elapsed = observation.timestamp_mono - previous.timestamp_mono if previous else 0.0
            self._exit_direction = (
                self._exit_sign(previous.dx_px if previous else 0.0, observation.dx_px, elapsed, self.half_frame_width),
                self._exit_sign(previous.dy_px if previous else 0.0, observation.dy_px, elapsed, self.half_frame_height),
            )
            self._last_face = observation
        self._apply_steps(res, controller.compute_steps(observation, now))

    def _recover_face(self, res, now, observation, current_angle, current_pitch, controller):
        if self._loss_started is None:
            self._loss_started = now
            controller.reset()
        elapsed = now - self._loss_started
        if (not controller.is_fresh(observation, now) or elapsed >= self.recovery_timeout_s
                or self._exit_direction == (0, 0)):
            controller.reset()
            return
        if elapsed < self.recovery_delay_s:
            return
        if self._recovery_target is None:
            horizontal, vertical = self._exit_direction
            yaw = max(self.min_yaw, min(self.max_yaw, current_angle + horizontal * self.recovery_yaw_deg))
            pitch = max(self.min_pitch, min(self.max_pitch, current_pitch - vertical * self.recovery_pitch_deg))
            self._recovery_target = yaw, pitch
            logger.info("[续跟] 沿出画方向短扫至 Yaw %.1f° / Pitch %.1f°。", yaw, pitch)
        yaw, pitch = self._recovery_target
        self._apply_steps(res, controller.recovery_steps(now, yaw - current_angle, pitch - current_pitch))

    def step(self, now: float, audio_event: Optional[AudioEvent],
             vision_obs: Optional[VisionObservation], current_angle: float,
             controller: DeadzoneStepController, current_pitch: float = 0.0) -> StateMachineResult:
        """消费当前观测并返回至多一个执行器动作。"""
        res = StateMachineResult(state=self.state)

        if self.state == SystemState.IDLE:
            if audio_event is not None:
                self.turn_target_angle = max(self.min_yaw, min(self.max_yaw, audio_event.theta_audio_deg))
                self.turn_start_mono = now
                self.turn_settle_start_mono = None
                self.state = SystemState.TURN_AND_RESPOND
                res.state = self.state
                res.servo_action = "set_angles"
                res.target_angle = self.turn_target_angle
                res.target_pitch_angle = self.search_pitch_angle
                logger.info("[状态转移] IDLE -> TURN_AND_RESPOND | 方位 %.1f°、俯仰 %.1f° (%s, conf=%.2f)",
                            self.turn_target_angle, self.search_pitch_angle,
                            audio_event.method, audio_event.confidence)

        elif self.state == SystemState.TURN_AND_RESPOND:
            res.drain_audio = True
            elapsed = max(0.0, now - self.turn_start_mono)
            at_yaw = abs(current_angle - self.turn_target_angle) <= 0.5
            at_pitch = abs(current_pitch - self.search_pitch_angle) <= 0.5
            if at_yaw and at_pitch:
                if self.turn_settle_start_mono is None:
                    self.turn_settle_start_mono = now
                elif now - self.turn_settle_start_mono >= self.turn_settle_s:
                    self._enter_search(now, current_angle)
                    res.state = self.state
            elif elapsed >= self.turn_timeout_s:
                logger.warning("[状态转移] TURN_AND_RESPOND 转向超时，按当前方向进入寻脸。")
                self._enter_search(now, current_angle)
                res.state = self.state

        elif self.state == SystemState.SEARCH_FACE:
            res.drain_audio = True
            if controller.is_fresh_face(vision_obs, now):
                self.state = SystemState.TRACK_FACE
                res.state = self.state
                logger.info("[状态转移] SEARCH_FACE -> TRACK_FACE | 检测到人脸。")
                self._track_observation(res, now, vision_obs, controller)
            else:
                started = self.search_start_mono if self.search_start_mono is not None else now
                elapsed = max(0.0, now - started)
                if elapsed >= self.search_timeout_s:
                    self.state = SystemState.IDLE
                    res.state = self.state
                    res.servo_action = "center"
                    logger.info("[状态转移] SEARCH_FACE -> IDLE | 微扫未发现人脸，云台回中。")
                elif self.search_timeout_s > 0.0:
                    step_index = int(elapsed / self.search_sweep_interval_s)
                    offset = self._SWEEP_PATTERN[min(step_index, len(self._SWEEP_PATTERN) - 1)]
                    target = max(self.min_yaw, min(self.max_yaw, self.search_origin_angle + offset))
                    if abs(target - current_angle) > 0.5:
                        res.servo_action = "set_angle"
                        res.target_angle = target

        elif self.state == SystemState.TRACK_FACE:
            res.drain_audio = True
            if controller.is_fresh_face(vision_obs, now):
                self._track_observation(res, now, vision_obs, controller)
            else:
                self._recover_face(res, now, vision_obs, current_angle, current_pitch, controller)

        return res


__all__ = ["TrackerStateMachine", "StateMachineResult"]
