import logging
import time

logger = logging.getLogger("App")

class DeadzoneStepController:
    """
    两轴死区步进控制器 (2-DOF Pan-Tilt Deadzone Step Controller)
    目标：根据新鲜的 (dx_px, dy_px) 像素偏差，决定偏航 (Yaw) 与俯仰 (Pitch) 的步进命令。
    不使用高阶 PID，避免开环调试振荡；同时支持单轴 compute_step() 与双轴 compute_steps()。
    """
    def __init__(self, config_control, config_servo):
        # 水平 (Yaw) 死区与步进
        self.deadzone_x = config_servo.get("deadzone_px_x", config_servo.get("deadzone_px", 30))
        self.step_deg_yaw = config_servo.get("step_deg_yaw", config_servo.get("step_deg", 2.0))

        # 俯仰 (Pitch) 死区与步进
        self.deadzone_y = config_servo.get("deadzone_px_y", 25)
        self.step_deg_pitch = config_servo.get("step_deg_pitch", 1.5)

        # 保持旧属性兼容
        self.deadzone = self.deadzone_x
        self.step_deg = self.step_deg_yaw

        self.observation_timeout = config_control.get("observation_timeout_s", 0.3)
        self.last_observation_time = 0.0

    def compute_step(self, vision_obs):
        """
        计算下一帧的偏航步进角 delta_yaw (保持阶段四/五接口 100% 兼容)
        :param vision_obs: VisionObservation 对象
        :return: delta_yaw (float)，不需要移动则返回 0.0
        """
        step_yaw, _ = self.compute_steps(vision_obs)
        return step_yaw

    def compute_steps(self, vision_obs):
        """
        同时计算水平偏航 (Yaw) 与垂直俯仰 (Pitch) 步进角
        :param vision_obs: VisionObservation 对象
        :return: (delta_yaw, delta_pitch)
        """
        if not vision_obs or not vision_obs.face_found:
            return 0.0, 0.0

        # 检查观测是否过期（防旧帧控制甩头）
        now = time.monotonic()
        age = now - vision_obs.timestamp_mono
        if age > self.observation_timeout:
            logger.debug(f"Vision observation too old ({age:.2f}s). Ignoring.")
            return 0.0, 0.0

        dx = vision_obs.dx_px
        dy = getattr(vision_obs, "dy_px", 0.0)

        # 水平 (Yaw) 死区判断
        delta_yaw = 0.0
        if abs(dx) >= self.deadzone_x:
            # 偏差向左 (dx < 0) -> 云台需向左转 -> 角度减少
            # 偏差向右 (dx > 0) -> 云台需向右转 -> 角度增加
            delta_yaw = -self.step_deg_yaw if dx < 0 else self.step_deg_yaw

        # 垂直 (Pitch) 死区判断
        delta_pitch = 0.0
        if abs(dy) >= self.deadzone_y:
            # 图像坐标系 y 向下增大：
            # 若目标在上方 (dy < 0) -> 镜头需向上抬头 -> 俯仰角增加
            # 若目标在下方 (dy > 0) -> 镜头需向下低头 -> 俯仰角减少
            delta_pitch = self.step_deg_pitch if dy < 0 else -self.step_deg_pitch

        return delta_yaw, delta_pitch
