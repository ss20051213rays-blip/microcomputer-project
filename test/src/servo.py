from __future__ import annotations

from .config import AppConfig


class MockServo:
    """Software-limited mock yaw servo."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.angle = config.servo_center_deg

    def clamp(self, angle_deg: float) -> float:
        return max(self.config.servo_min_deg, min(self.config.servo_max_deg, angle_deg))

    def get_angle(self) -> float:
        return self.angle

    def set_angle(self, angle_deg: float) -> float:
        self.angle = self.clamp(angle_deg)
        return self.angle

    def center(self) -> float:
        return self.set_angle(self.config.servo_center_deg)

    def step(self, delta_deg: float) -> float:
        return self.set_angle(self.angle + delta_deg)
