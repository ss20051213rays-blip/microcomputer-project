import logging
import time

try:
    import pigpio
except ImportError:
    pigpio = None

logger = logging.getLogger("App")

class ServoController:
    def __init__(self, config_servo, dry_run=False):
        self.config = config_servo
        self.dry_run = dry_run
        
        self.gpio = self.config.get("servo_gpio", 18)
        self.pulse_min = self.config.get("pulse_min_us", 500)
        self.pulse_max = self.config.get("pulse_max_us", 2500)
        self.servo_mid = self.config.get("servo_mid", 1500)
        self.min_angle = self.config.get("min_angle", -90.0)
        self.max_angle = self.config.get("max_angle", 90.0)
        self.sign = self.config.get("servo_sign", 1)
        
        self.current_angle = 0.0
        
        if self.dry_run or not pigpio:
            logger.warning("Servo running in DRY-RUN mode or pigpio not installed.")
            self.pi = None
        else:
            self.pi = pigpio.pi()
            if not self.pi.connected:
                logger.error("pigpio daemon not connected! Please run 'sudo pigpiod'.")
                raise RuntimeError("pigpio daemon not connected")
            logger.info(f"Servo initialized on GPIO {self.gpio}.")
            
    def _angle_to_pulse(self, angle):
        """将物理角度映射到 PWM 脉宽，带方向符号处理"""
        # 应用方向符号
        physical_angle = angle * self.sign
        
        angle_range = self.max_angle - self.min_angle
        pulse_range = self.pulse_max - self.pulse_min
        
        ratio = (physical_angle - self.min_angle) / angle_range
        pulse = self.pulse_min + ratio * pulse_range
        
        # 绝对安全限位裁剪
        pulse = max(self.pulse_min, min(self.pulse_max, pulse))
        return int(pulse)

    def set_angle(self, angle):
        """设置舵机角度并限制在安全范围内"""
        # 软件限位拦截
        if angle < self.min_angle:
            logger.warning(f"Target angle {angle} clipped to min {self.min_angle}")
            angle = self.min_angle
        elif angle > self.max_angle:
            logger.warning(f"Target angle {angle} clipped to max {self.max_angle}")
            angle = self.max_angle
            
        self.current_angle = angle
        pulse = self._angle_to_pulse(angle)
        
        if not self.dry_run and self.pi:
            self.pi.set_servo_pulsewidth(self.gpio, pulse)
            
        logger.debug(f"Servo set to {angle}° (Pulse: {pulse}µs)")
        
    def step(self, delta):
        """步进控制"""
        self.set_angle(self.current_angle + delta)
        
    def center(self):
        """回中"""
        logger.info("Centering servo.")
        self.set_angle(0.0)
        
    def disable(self):
        """停止输出 PWM 信号"""
        logger.info("Disabling servo PWM.")
        if not self.dry_run and self.pi:
            self.pi.set_servo_pulsewidth(self.gpio, 0)
            self.pi.stop()
            self.pi = None

