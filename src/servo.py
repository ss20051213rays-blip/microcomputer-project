import logging
import time

try:
    import pigpio
except ImportError:
    pigpio = None

try:
    import serial
except ImportError:
    serial = None

logger = logging.getLogger("App")

class ServoController:
    """
    通用两轴舵机控制器 (2-DOF Pan-Tilt Servo Controller)
    支持两种执行后端：
    1. 'bus': 微雪通用型 Bus Servo Adapter 串行总线舵机驱动 (支持 2-DOF 双轴: Yaw + Pitch, 协议闭环控制与状态回读)
    2. 'pwm': 旧版树莓派硬件引脚 GPIO 18 + pigpio PWM 兼容驱动 (单轴水平偏航)
    """
    def __init__(self, config_servo, dry_run=False):
        self.config = config_servo
        self.dry_run = dry_run

        self.driver_type = self.config.get("driver_type", "bus")

        # 偏航 (Yaw) 角度状态与别名兼容
        self.current_yaw = 0.0
        self.current_angle = 0.0  # 保持与旧接口及模拟验收测试 100% 兼容

        # 俯仰 (Pitch) 角度状态
        self.current_pitch = 0.0

        # 限位与方向参数
        self.min_yaw = float(self.config.get("min_yaw_angle", self.config.get("min_angle", -90.0)))
        self.max_yaw = float(self.config.get("max_yaw_angle", self.config.get("max_angle", 90.0)))
        self.yaw_sign = int(self.config.get("yaw_sign", self.config.get("servo_sign", 1)))

        self.min_pitch = float(self.config.get("min_pitch_angle", -30.0))
        self.max_pitch = float(self.config.get("max_pitch_angle", 45.0))
        self.pitch_sign = int(self.config.get("pitch_sign", 1))

        # 保持旧属性兼容
        self.min_angle = self.min_yaw
        self.max_angle = self.max_yaw
        self.sign = self.yaw_sign

        # PWM 参数（用于兼容 pwm 驱动模式）
        self.gpio = self.config.get("servo_gpio", 18)
        self.pulse_min = self.config.get("pulse_min_us", 500)
        self.pulse_max = self.config.get("pulse_max_us", 2500)
        self.servo_mid = self.config.get("servo_mid", 1500)

        # 串行总线参数（用于 bus 驱动模式）
        self.serial_port = self.config.get("serial_port", "/dev/ttyUSB0")
        self.baudrate = self.config.get("baudrate", 1000000)
        self.yaw_id = self.config.get("yaw_id", 1)
        self.pitch_id = self.config.get("pitch_id", 2)

        self.pi = None
        self.ser = None

        if self.dry_run:
            logger.info(f"Servo running in DRY-RUN mode (driver_type: {self.driver_type}).")
            return

        if self.driver_type == "bus":
            if not serial:
                logger.warning("pyserial 未安装，总线舵机转入模拟模式。请在真机环境安装 pyserial。")
            else:
                try:
                    self.ser = serial.Serial(self.serial_port, self.baudrate, timeout=0.05)
                    logger.info(f"微雪串行总线舵机驱动已连接: {self.serial_port} @ {self.baudrate}bps (Yaw ID={self.yaw_id}, Pitch ID={self.pitch_id})")
                except Exception as e:
                    logger.warning(f"无法打开总线舵机串口 {self.serial_port}: {e}，转入脱机模拟模式。")
                    self.ser = None
        else:
            # 旧版 PWM 驱动
            if not pigpio:
                logger.warning("Servo running in DRY-RUN mode or pigpio not installed.")
                self.pi = None
            else:
                self.pi = pigpio.pi()
                if not self.pi.connected:
                    logger.error("pigpio daemon not connected! Please run 'sudo pigpiod'.")
                    raise RuntimeError("pigpio daemon not connected")
                logger.info(f"Servo initialized on GPIO {self.gpio}.")

    # ── 总线舵机协议帧生成辅助方法 ───────────────────────────────────────────
    def _send_bus_pos(self, servo_id, angle_deg, time_ms=0, speed=0):
        """
        向微雪/ST/SC 系列串行总线舵机发送目标位置指令
        位置范围：0 ~ 4095，2048 对应中位 0°，每度约 11.378 个步进
        """
        if not self.ser:
            return

        # 角度映射到 0~4095 原始值
        raw_pos = int(2048 + angle_deg * (4096.0 / 360.0))
        raw_pos = max(0, min(4095, raw_pos))

        # 协议寄存器: 0x2A (GOAL_POSITION)
        # 包格式: 0xFF 0xFF ID LEN INST(0x03) REG(0x2A) POS_L POS_H TIME_L TIME_H SPD_L SPD_H CHKSUM
        pos_l = raw_pos & 0xFF
        pos_h = (raw_pos >> 8) & 0xFF
        time_l = time_ms & 0xFF
        time_h = (time_ms >> 8) & 0xFF
        spd_l = speed & 0xFF
        spd_h = (speed >> 8) & 0xFF

        length = 9  # INST + REG + 6 params + CHKSUM (length = params + 2)
        instruction = 0x03 # WRITE
        reg_addr = 0x2A

        packet = [0xFF, 0xFF, servo_id, length, instruction, reg_addr, pos_l, pos_h, time_l, time_h, spd_l, spd_h]
        checksum = (~(sum(packet[2:]) & 0xFF)) & 0xFF
        packet.append(checksum)

        try:
            self.ser.write(bytes(packet))
        except Exception as e:
            logger.error(f"总线舵机发送指令失败: {e}")

    def _send_bus_torque(self, servo_id, enable=True):
        """使能或关闭总线舵机扭矩"""
        if not self.ser:
            return
        length = 4
        instruction = 0x03
        reg_addr = 0x28 # TORQUE_ENABLE
        val = 1 if enable else 0
        packet = [0xFF, 0xFF, servo_id, length, instruction, reg_addr, val]
        checksum = (~(sum(packet[2:]) & 0xFF)) & 0xFF
        packet.append(checksum)
        try:
            self.ser.write(bytes(packet))
        except Exception as e:
            logger.error(f"总线舵机设置扭矩失败: {e}")

    # ── PWM 驱动分段映射辅助方法 ───────────────────────────────────────────
    def _angle_to_pulse(self, angle):
        """将物理角度映射到 PWM 脉宽，带方向符号处理，且 0° 严格锚定 servo_mid"""
        physical_angle = angle * self.yaw_sign
        if physical_angle >= 0:
            if self.max_yaw > 0:
                ratio = physical_angle / self.max_yaw
                pulse = self.servo_mid + ratio * (self.pulse_max - self.servo_mid)
            else:
                pulse = self.servo_mid
        else:
            if self.min_yaw < 0:
                ratio = physical_angle / self.min_yaw
                pulse = self.servo_mid + ratio * (self.pulse_min - self.servo_mid)
            else:
                pulse = self.servo_mid
        pulse = max(self.pulse_min, min(self.pulse_max, pulse))
        return int(pulse)

    # ── 通用公共控制接口 ───────────────────────────────────────────────────
    def set_angle(self, angle, pitch=None):
        """设置偏航角度 (水平 Yaw) 及可选的俯仰角度 (Pitch)"""
        self.set_angles(yaw=angle, pitch=pitch)

    def set_angles(self, yaw=None, pitch=None):
        """同时或单独设置偏航与俯仰角度并进行软件限位拦截"""
        if yaw is not None:
            if yaw < self.min_yaw:
                logger.warning(f"Target yaw {yaw}° clipped to min {self.min_yaw}°")
                yaw = self.min_yaw
            elif yaw > self.max_yaw:
                logger.warning(f"Target yaw {yaw}° clipped to max {self.max_yaw}°")
                yaw = self.max_yaw
            self.current_yaw = float(yaw)
            self.current_angle = self.current_yaw # 保持向后兼容

        if pitch is not None:
            if pitch < self.min_pitch:
                logger.warning(f"Target pitch {pitch}° clipped to min {self.min_pitch}°")
                pitch = self.min_pitch
            elif pitch > self.max_pitch:
                logger.warning(f"Target pitch {pitch}° clipped to max {self.max_pitch}°")
                pitch = self.max_pitch
            self.current_pitch = float(pitch)

        if not self.dry_run:
            if self.driver_type == "bus" and self.ser:
                if yaw is not None:
                    self._send_bus_pos(self.yaw_id, self.current_yaw * self.yaw_sign)
                if pitch is not None:
                    self._send_bus_pos(self.pitch_id, self.current_pitch * self.pitch_sign)
            elif self.driver_type == "pwm" and self.pi and yaw is not None:
                pulse = self._angle_to_pulse(self.current_yaw)
                self.pi.set_servo_pulsewidth(self.gpio, pulse)

        logger.debug(f"Servo set to Yaw={self.current_yaw}°, Pitch={self.current_pitch}°")

    def step(self, delta_yaw, delta_pitch=0.0):
        """两轴步进控制"""
        self.set_angles(self.current_yaw + delta_yaw, self.current_pitch + delta_pitch)

    def center(self):
        """两轴回中 (0°, 0°)"""
        logger.info("Centering 2-DOF servo gimbal.")
        self.set_angles(0.0, 0.0)

    def get_angles(self):
        """获取当前两轴角度 (Yaw, Pitch)"""
        return self.current_yaw, self.current_pitch

    def disable(self):
        """安全释放舵机扭矩与输出"""
        logger.info("Disabling servo torque / PWM output.")
        if not self.dry_run:
            if self.driver_type == "bus" and self.ser:
                self._send_bus_torque(self.yaw_id, enable=False)
                self._send_bus_torque(self.pitch_id, enable=False)
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
            elif self.driver_type == "pwm" and self.pi:
                self.pi.set_servo_pulsewidth(self.gpio, 0)
                self.pi.stop()
                self.pi = None
