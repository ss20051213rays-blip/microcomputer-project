"""阶段 4 四态状态机与 2-DOF 云台脱机联调测试。"""
import time

from pantilt.adapters.actuation import servo as servo_module
from pantilt.adapters.actuation.servo import ServoController
from pantilt.bootstrap import create_app
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.paths import DEFAULT_CONFIG


def test_2dof_face_tracking_state_flow():
    app = create_app(load_config(DEFAULT_CONFIG), dry_run=True, web=False)
    assert app.start()
    try:
        now = time.monotonic()
        assert app.state == SystemState.IDLE
        assert not app.vision._tracking_active
        assert app.servo.get_angles() == (0.0, 0.0)
        assert not hasattr(app, "laser")

        app.audio.event_queue.put(AudioEvent(now, 25.0, "right", 0.9, "test"))
        app.tick(now)
        assert app.state == SystemState.TURN_AND_RESPOND
        assert app.vision._tracking_active
        assert app.servo.current_yaw == 25.0
        assert app.servo.current_pitch == 30.0

        app.tick(now + 0.01)
        now += app.turn_settle_s + 0.02
        app.tick(now)
        assert app.state == SystemState.SEARCH_FACE

        # 寻脸到位即切 TRACK_FACE，并对水平/垂直误差同时作比例跟随。
        obs = VisionObservation(now, True, 80.0, (360, 160, 70, 70), 0.95, 20.0, dy_px=-50.0)
        app.vision.set_mock_observation(obs)
        app.tick(now)
        assert app.state == SystemState.TRACK_FACE
        yaw, pitch = app.servo.get_angles()
        assert yaw > 25.0
        assert pitch > 0.0

        # 丢脸后不回中，恢复入画后继续跟随。
        held = app.servo.get_angles()
        lost_at = now + 4.0
        missing = VisionObservation(lost_at, False, 0, (0, 0, 0, 0), 0, 20)
        app.vision.set_mock_observation(missing)
        app.tick(lost_at)
        assert app.state == SystemState.TRACK_FACE
        assert app.servo.get_angles() == held

        now = lost_at + 0.05
        app.vision.set_mock_observation(VisionObservation(now, True, -70, (150, 160, 70, 70),
                                                         0.95, 20.0, dy_px=35.0))
        app.tick(now)
        assert app.servo.current_yaw < held[0]
        assert app.servo.current_pitch < held[1]
    finally:
        app.stop()


def test_bus_tracking_limits_speed_and_skips_repeated_position(monkeypatch):
    frames = []

    class FakeSerial:
        def reset_input_buffer(self):
            pass

        def write(self, packet):
            frames.append(packet)

        def flush(self):
            pass

    monkeypatch.setattr(servo_module.time, "sleep", lambda _delay: None)
    servo = ServoController({"driver_type": "bus", "max_yaw_angle": 1.0}, dry_run=True)
    servo.dry_run = False
    servo.ser = FakeSerial()
    servo.center()
    assert [int.from_bytes(frame[10:12], "little") for frame in frames] == [0, 0]
    frames.clear()

    servo.step(0.01, period_s=1 / 30)
    assert frames == []  # 子刻度命令留在软件角度中，避免重发相同位置
    servo.step(0.99, period_s=1 / 30)
    servo.step(0.50, period_s=1 / 30)
    assert len(frames) == 1  # 只写水平轴，到限位后不重复发送
    assert frames[0][2] == servo.yaw_id
    assert int.from_bytes(frames[0][10:12], "little") == 338
