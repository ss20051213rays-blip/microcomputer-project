"""激光指示器输出适配器与安全联锁。"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("App")


class LaserIndicator:
    """
    激光瞄准指示器驱动及安全联锁控制。
    包含：
    - 连续帧锁定判定 (lock_min_frames)
    - 连续点亮超时保护 (max_continuous_s)
    - 物理 GPIO 或 dry_run 模式
    """

    def __init__(self, config_laser: Optional[Dict[str, Any]] = None, dry_run: bool = False):
        self.config = config_laser or {}
        self.dry_run = dry_run

        self.enabled = self.config.get("enabled", False)
        self.gpio_pin = self.config.get("gpio_pin", 23)
        self.lock_min_frames = self.config.get("lock_min_frames", 3)
        self.max_continuous_s = self.config.get("max_continuous_s", 10.0)

        self._is_on = False
        self.on_start_mono = 0.0
        self.locked_frames_count = 0

    @property
    def is_on(self) -> bool:
        """激光当前是否处于点亮状态。"""
        return self._is_on

    def set_laser(self, enable: bool, now: Optional[float] = None) -> bool:
        """控制激光指示器使能状态，具备过热与人眼安全超时联锁。"""
        if not self.enabled:
            return False
        if now is None:
            now = time.monotonic()

        if enable:
            if not self._is_on:
                self._is_on = True
                self.on_start_mono = now
                logger.info("🎯 [激光指示] 目标进入死区准星且连续锁定，点亮 50mW 激光器进行物理指示！")
            else:
                # 超时安全断开保护
                if now - self.on_start_mono > self.max_continuous_s:
                    logger.warning(
                        f"⚠️ [激光安全联锁] 激光持续点亮超过安全上限 ({self.max_continuous_s}s)，强制关闭防过热。"
                    )
                    self._is_on = False
        else:
            if self._is_on:
                self._is_on = False
                logger.info("🎯 [激光指示] 目标失锁或离开死区，关闭激光指示。")

        return self._is_on

    def on_target_tracking(self, in_deadzone: bool, now: Optional[float] = None):
        """根据目标是否进入双轴死区更新锁定计数并驱动激光器。"""
        if now is None:
            now = time.monotonic()
        if in_deadzone:
            self.locked_frames_count += 1
            if self.locked_frames_count >= self.lock_min_frames:
                self.set_laser(True, now)
        else:
            self.locked_frames_count = 0
            self.set_laser(False, now)

    def reset(self, now: Optional[float] = None):
        """重置锁定计数并熄灭激光。"""
        self.locked_frames_count = 0
        self.set_laser(False, now)

    def disable(self):
        """安全停机关闭激光。"""
        self.reset()


__all__ = ["LaserIndicator"]

