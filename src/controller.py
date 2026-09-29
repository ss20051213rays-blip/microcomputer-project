import logging
import time

logger = logging.getLogger("App")

class DeadzoneStepController:
    """
    极简死区步进控制器 (阶段四核心)
    目标：根据新鲜的 dx_px（像素偏差），决定向左还是向右发送定长的步进命令。
    不使用 PID，避免调试振荡。
    """
    def __init__(self, config_control, config_servo):
        self.deadzone = config_servo.get("deadzone_px", 30)
        self.step_deg = config_servo.get("step_deg", 2.0)
        self.observation_timeout = config_control.get("observation_timeout_s", 0.3)
        
        self.last_observation_time = 0.0
        
    def compute_step(self, vision_obs):
        """
        计算下一帧的步进角 delta_angle
        :param vision_obs: VisionObservation 对象
        :return: delta_angle (float)，如果不需要移动则返回 0.0
        """
        if not vision_obs or not vision_obs.face_found:
            return 0.0
            
        # 检查观测是否过期（防旧帧控制甩头）
        now = time.monotonic()
        age = now - vision_obs.timestamp_mono
        if age > self.observation_timeout:
            logger.debug(f"Vision observation too old ({age:.2f}s). Ignoring.")
            return 0.0
            
        dx = vision_obs.dx_px
        
        # 死区判断
        if abs(dx) < self.deadzone:
            return 0.0
            
        # 偏差向左 (dx < 0) -> 云台需向左转 -> 角度减少
        # 偏差向右 (dx > 0) -> 云台需向右转 -> 角度增加
        if dx < 0:
            return -self.step_deg
        else:
            return self.step_deg

