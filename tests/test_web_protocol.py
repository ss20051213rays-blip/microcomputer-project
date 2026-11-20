"""Web 前端通信协议与数据传输对象 (DTO) 单元测试。"""
import json
import time

from pantilt.adapters.web.protocol import (
    AudioTelemetryDTO,
    ConfigUpdateCommand,
    ControlMode,
    EventStreamType,
    LaserControlCommand,
    LaserTelemetryDTO,
    LogEntryDTO,
    ModeSwitchCommand,
    ServoControlCommand,
    ServoTelemetryDTO,
    SystemStatusDTO,
    TelemetryPacketDTO,
    VisionTelemetryDTO,
    WebRoutes,
    create_sse_frame,
)


def test_web_routes_and_enums():
    """验证所有路由端点与枚举定义完整性。"""
    assert WebRoutes.STATUS == "/api/status"
    assert WebRoutes.TELEMETRY == "/api/telemetry"
    assert WebRoutes.STREAM_EVENTS == "/api/stream/events"
    assert WebRoutes.STREAM_VIDEO == "/api/stream/video"
    assert WebRoutes.CONTROL_SERVO == "/api/control/servo"
    assert WebRoutes.CONTROL_CENTER == "/api/control/center"
    assert WebRoutes.CONTROL_LASER == "/api/control/laser"
    assert WebRoutes.CONTROL_MODE == "/api/control/mode"
    assert WebRoutes.CONTROL_RESET == "/api/control/reset"
    assert WebRoutes.CONFIG == "/api/config"
    assert WebRoutes.LOGS == "/api/logs"

    assert ControlMode.AUTO == "AUTO"
    assert ControlMode.MANUAL == "MANUAL"
    assert ControlMode.CALIBRATION == "CALIBRATION"

    assert EventStreamType.TELEMETRY == "telemetry"
    assert EventStreamType.ACOUSTIC == "acoustic"
    assert EventStreamType.STATE_CHANGE == "state_change"


def test_telemetry_packet_serialization():
    """验证全量高频遥测快照 DTO 序列化与反序列化完整性。"""
    now = time.monotonic()
    status = SystemStatusDTO(
        app_state="FOLLOW",
        control_mode="AUTO",
        running=True,
        dry_run=False,
        uptime_s=120.5,
        main_loop_hz=30.0,
        version="0.2.0",
        cpu_temp_c=48.2,
    )
    servo = ServoTelemetryDTO(
        yaw=25.0,
        pitch=-10.0,
        target_yaw=25.0,
        target_pitch=-10.0,
        min_yaw=-90.0,
        max_yaw=90.0,
        min_pitch=-30.0,
        max_pitch=45.0,
        driver_type="bus",
        torque_enabled=True,
    )
    vision = VisionTelemetryDTO(
        target_found=True,
        target_type="aruco",
        target_id=15,
        dx_px=-8.5,
        dy_px=4.2,
        bbox=(200, 150, 60, 60),
        confidence=1.0,
        fps=119.0,
        in_deadzone=True,
        age_s=0.005,
    )
    audio = AudioTelemetryDTO(
        event_detected=True,
        theta_deg=-30.0,
        side="left",
        confidence=0.88,
        method="gcc_phat",
        energy_rms=0.075,
        age_s=2.3,
    )
    laser = LaserTelemetryDTO(
        is_on=True,
        continuous_s=2.1,
        max_continuous_s=10.0,
        locked_frames=6,
        lock_min_frames=3,
        hardware_enabled=True,
    )

    packet = TelemetryPacketDTO(
        timestamp_mono=now,
        iso_time="2026-11-10T20:00:00Z",
        status=status,
        servo=servo,
        vision=vision,
        audio=audio,
        laser=laser,
    )

    d = packet.to_dict()
    assert isinstance(d, dict)
    assert d["status"]["app_state"] == "FOLLOW"
    assert d["servo"]["yaw"] == 25.0
    assert d["vision"]["target_id"] == 15
    assert d["audio"]["theta_deg"] == -30.0
    assert d["laser"]["is_on"] is True

    json_str = packet.to_json()
    parsed = json.loads(json_str)
    assert parsed["status"]["cpu_temp_c"] == 48.2
    assert parsed["servo"]["pitch"] == -10.0


def test_sse_frame_formatting():
    """验证标准 Server-Sent Events (SSE) 文本帧格式。"""
    frame = create_sse_frame("telemetry", {"state": "IDLE", "yaw": 0.0}, event_id=42)
    expected_lines = [
        "id: 42",
        "event: telemetry",
        'data: {"state": "IDLE", "yaw": 0.0}',
        "",
        "",
    ]
    assert frame == "\n".join(expected_lines)

    frame_no_id = create_sse_frame("alert", "Laser safety shutdown")
    assert "id:" not in frame_no_id
    assert "event: alert\n" in frame_no_id
    assert "data: Laser safety shutdown\n\n" in frame_no_id


def test_servo_control_command_validation_and_clamping():
    """验证舵机步进与绝对定位指令软限位安全截断逻辑。"""
    # 1. 绝对定位在安全范围内
    cmd_abs = ServoControlCommand(mode="absolute", yaw=45.0, pitch=15.0)
    yaw, pitch = cmd_abs.validate_and_clamp()
    assert yaw == 45.0
    assert pitch == 15.0

    # 2. 绝对定位越界截断
    cmd_over = ServoControlCommand(mode="absolute", yaw=120.0, pitch=-50.0)
    yaw, pitch = cmd_over.validate_and_clamp(
        min_yaw=-90.0, max_yaw=90.0, min_pitch=-30.0, max_pitch=45.0
    )
    assert yaw == 90.0
    assert pitch == -30.0

    # 3. 步进模式正常累加
    cmd_step = ServoControlCommand(mode="step", delta_yaw=5.0, delta_pitch=-2.0)
    yaw, pitch = cmd_step.validate_and_clamp(current_yaw=20.0, current_pitch=10.0)
    assert yaw == 25.0
    assert pitch == 8.0

    # 4. 步进模式触碰上限截断
    cmd_step_clip = ServoControlCommand(mode="step", delta_yaw=15.0, delta_pitch=40.0)
    yaw, pitch = cmd_step_clip.validate_and_clamp(
        min_yaw=-90.0, max_yaw=90.0, min_pitch=-30.0, max_pitch=45.0,
        current_yaw=80.0, current_pitch=20.0
    )
    assert yaw == 90.0
    assert pitch == 45.0


def test_command_and_log_dtos():
    """验证激光控制、模式切换、配置热更与日志 DTO。"""
    laser_cmd = LaserControlCommand(enable=True, force_override=False)
    assert laser_cmd.enable is True

    mode_cmd = ModeSwitchCommand(mode="MANUAL")
    assert mode_cmd.mode == "MANUAL"

    cfg_cmd = ConfigUpdateCommand(params={"deadzone_px_x": 15, "step_deg_yaw": 1.0})
    assert cfg_cmd.params["deadzone_px_x"] == 15

    log_entry = LogEntryDTO(
        timestamp=1731269730.0,
        iso_time="2026-11-10 20:15:30",
        level="INFO",
        logger="App",
        message="System started",
    )
    log_dict = log_entry.to_dict()
    assert log_dict["level"] == "INFO"
    assert log_dict["message"] == "System started"
