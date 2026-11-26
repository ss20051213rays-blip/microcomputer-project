"""双轴云台跟踪速度控制。"""
import math
import time


class DeadzoneStepController:
    """把像素偏差变成目标角速度，并按控制时钟积分为小步。"""

    def __init__(self, config_control, config_servo):
        cfg_control = config_control or {}
        cfg_servo = config_servo or {}
        self.deadzone_x = float(cfg_servo.get("deadzone_px_x", cfg_servo.get("deadzone_px", 30)))
        self.deadzone_y = float(cfg_servo.get("deadzone_px_y", 25))
        # 旧配置的增益和限幅按实测基线 12.5 个视觉观测/秒换算。
        legacy_fps = 12.5
        yaw_gain = float(cfg_servo.get("kp_yaw", 0.50 / legacy_fps)) * legacy_fps
        pitch_gain = float(cfg_servo.get("kp_pitch", 0.40 / legacy_fps)) * legacy_fps
        yaw_limit = float(cfg_servo["max_step_yaw"]) * legacy_fps if "max_step_yaw" in cfg_servo else 42.0
        pitch_limit = float(cfg_servo["max_step_pitch"]) * legacy_fps if "max_step_pitch" in cfg_servo else 28.0
        self.yaw_gain = float(cfg_servo.get("tracking_yaw_gain", yaw_gain))
        self.pitch_gain = float(cfg_servo.get("tracking_pitch_gain", pitch_gain))
        self.max_yaw_speed = abs(float(cfg_servo.get("max_yaw_speed_deg_s", yaw_limit)))
        self.max_pitch_speed = abs(float(cfg_servo.get("max_pitch_speed_deg_s", pitch_limit)))
        self.yaw_accel = abs(float(cfg_servo.get("yaw_accel_deg_s2", 210.0)))
        self.pitch_accel = abs(float(cfg_servo.get("pitch_accel_deg_s2", 150.0)))
        self.observation_timeout = float(cfg_control.get("observation_timeout_s", 0.3))
        self.period_s = 1.0 / float(cfg_control.get("main_loop_hz", 30))

        self.deadzone = self.deadzone_x
        self.step_deg = float(cfg_servo.get("step_deg_yaw", cfg_servo.get("step_deg", 2.0)))
        self.step_deg_yaw = self.step_deg
        self.step_deg_pitch = float(cfg_servo.get("step_deg_pitch", 1.5))
        self.reset()

    def reset(self):
        """清零速度，下一次跟踪从静止开始。"""
        self._last_tick = None
        self._yaw_speed = 0.0
        self._pitch_speed = 0.0

    def is_fresh(self, vision_obs, now):
        return vision_obs is not None and now - vision_obs.timestamp_mono <= self.observation_timeout

    def is_fresh_face(self, vision_obs, now):
        return self.is_fresh(vision_obs, now) and vision_obs.face_found

    def compute_step(self, vision_obs):
        """兼容旧单轴调用，返回 Yaw 步进。"""
        return self.compute_steps(vision_obs)[0]

    def compute_steps(self, vision_obs, now=None):
        """每个控制周期更新速度，可在下一帧到来前沿用最新有效观测。"""
        now = time.monotonic() if now is None else now
        if not self.is_fresh_face(vision_obs, now):
            self.reset()
            return 0.0, 0.0

        yaw_target = self._target_speed(vision_obs.dx_px, self.deadzone_x, self.yaw_gain, self.max_yaw_speed)
        # 图像 y 轴向下，目标在上方需抬头。
        pitch_target = self._target_speed(-getattr(vision_obs, "dy_px", 0.0), self.deadzone_y,
                                          self.pitch_gain, self.max_pitch_speed)
        return self._advance(now, yaw_target, pitch_target)

    def recovery_steps(self, now, yaw_remaining, pitch_remaining):
        """以较低的角速度向最近出画方向移动，接近搜索终点时减速。"""
        yaw_target = self._target_speed(yaw_remaining, 0.1, 5.0, min(24.0, self.max_yaw_speed))
        pitch_target = self._target_speed(pitch_remaining, 0.1, 5.0, min(16.0, self.max_pitch_speed))
        yaw, pitch = self._advance(now, yaw_target, pitch_target)
        return self._toward_target(yaw, yaw_remaining), self._toward_target(pitch, pitch_remaining)

    def _advance(self, now, yaw_target, pitch_target):
        elapsed = self.period_s if self._last_tick is None else now - self._last_tick
        if elapsed <= 0.0:
            return 0.0, 0.0
        self._last_tick = now
        # 错过周期后只走一步，避免补发累积位移。
        dt = min(elapsed, self.period_s)
        old_yaw, old_pitch = self._yaw_speed, self._pitch_speed
        self._yaw_speed = self._ramp_speed(old_yaw, yaw_target, self.yaw_accel * dt)
        self._pitch_speed = self._ramp_speed(old_pitch, pitch_target, self.pitch_accel * dt)
        return (old_yaw + self._yaw_speed) * dt / 2.0, (old_pitch + self._pitch_speed) * dt / 2.0

    @staticmethod
    def _toward_target(step, remaining):
        if step * remaining <= 0.0 or abs(remaining) <= 0.1:
            return 0.0
        return math.copysign(min(abs(step), abs(remaining)), remaining)

    @staticmethod
    def _target_speed(error, deadzone, gain, max_speed):
        speed = min(max_speed, gain * max(0.0, abs(error) - deadzone))
        return math.copysign(speed, error)

    @staticmethod
    def _ramp_speed(current, target, max_change):
        return min(current + max_change, max(current - max_change, target))


__all__ = ["DeadzoneStepController"]
