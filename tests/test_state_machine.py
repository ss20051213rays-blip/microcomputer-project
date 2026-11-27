"""阶段 4 四态人脸跟踪状态机单测。"""
import time

from pantilt.bootstrap import create_app
from pantilt.domain.types import AudioEvent, SystemState, VisionObservation


def test_wakeup_listening_pauses_when_wakeup_triggers_turn(running_app):
    running_app.audio.wakeup_active = True
    now = time.monotonic()

    running_app.tick(now)
    assert running_app.audio.wakeup_listening is True

    running_app.audio.event_queue.put(AudioEvent(now + 0.01, -20.0, "left", 0.9, "gcc_phat"))
    running_app.tick(now + 0.01)

    assert running_app.state == SystemState.TURN_AND_RESPOND
    assert running_app.audio.wakeup_listening is False


 def _start_search(app):
    now = time.monotonic()
    app.audio.event_queue.put(AudioEvent(now, -20.0, "left", 0.9, "test"))
    app.tick(now)
    assert app.state == SystemState.TURN_AND_RESPOND
    app.tick(now + 0.01)  # 开始到位平息计时
    now += app.turn_settle_s + 0.02
    app.tick(now)
    assert app.state == SystemState.SEARCH_FACE
    return now


def _face(now, dx=0.0, dy=0.0):
    return VisionObservation(now, True, dx, (300, 180, 40, 40), 0.95, 20.0, dy_px=dy)


def test_boots_idle_without_laser_dependency(running_app):
    assert running_app.state == SystemState.IDLE
    assert running_app.servo.get_angles() == (0.0, 0.0)
    assert not hasattr(running_app, "laser")


def test_audio_event_turns_then_settle_enters_search(running_app):
    now = time.monotonic()
    running_app.audio.event_queue.put(AudioEvent(now, -35.0, "left", 0.85, "gcc_phat"))
    running_app.tick(now)
    assert running_app.state == SystemState.TURN_AND_RESPOND
    assert running_app.servo.current_yaw == -35.0
    assert running_app.servo.current_pitch == 30.0

    running_app.tick(now + 0.01)
    running_app.tick(now + running_app.turn_settle_s + 0.02)
    assert running_app.state == SystemState.SEARCH_FACE


def test_turn_waits_for_pitch_target_before_settle(running_app):
    machine = running_app.state_machine
    now = time.monotonic()
    event = AudioEvent(now, -10.0, "left", 0.9, "test")
    first = machine.step(now, event, None, 0.0, running_app.controller, current_pitch=0.0)
    assert first.servo_action == "set_angles"
    assert first.target_pitch_angle == 30.0

    machine.step(now + 0.01, None, None, -10.0, running_app.controller, current_pitch=29.0)
    assert machine.state == SystemState.TURN_AND_RESPOND
    machine.step(now + 0.02, None, None, -10.0, running_app.controller, current_pitch=30.0)
    assert machine.state == SystemState.TURN_AND_RESPOND
    machine.step(now + 0.35, None, None, -10.0, running_app.controller, current_pitch=30.0)
    assert machine.state == SystemState.SEARCH_FACE


def test_face_found_immediately_enters_tracking(running_app):
    now = _start_search(running_app)
    running_app.vision.set_mock_observation(_face(now, dx=45.0, dy=-40.0))
    running_app.tick(now)
    assert running_app.state == SystemState.TRACK_FACE
    yaw, pitch = running_app.servo.get_angles()
    assert yaw > -20.0
    assert pitch > 0.0


def test_search_sweeps_then_returns_to_center(running_app):
    now = _start_search(running_app)
    # With no face, the first sweep step moves 10 degrees from the arrival heading.
    running_app.tick(now + 0.6)
    assert running_app.state == SystemState.SEARCH_FACE
    assert running_app.servo.current_yaw == -10.0

    running_app.tick(now + running_app.state_machine.search_timeout_s + 0.1)
    assert running_app.state == SystemState.IDLE
    assert running_app.servo.get_angles() == (0.0, 0.0)


def test_tracking_moves_both_axes_and_respects_deadzone(running_app):
    now = _start_search(running_app)
    running_app.vision.set_mock_observation(_face(now, dx=45.0, dy=-40.0))
    running_app.tick(now)
    yaw, pitch = running_app.servo.get_angles()
    assert yaw > -20.0 and pitch > 0.0

    # A centered observation lets both axes brake, then hold.
    period = running_app.controller.period_s
    running_app.vision.set_mock_observation(_face(now + period, dx=5.0, dy=3.0))
    running_app.tick(now + period)
    stopped = running_app.servo.get_angles()
    running_app.tick(now + 2 * period)
    assert running_app.servo.get_angles() == stopped


def test_tracking_holds_position_during_occlusion_and_resumes(running_app):
    now = _start_search(running_app)
    running_app.vision.set_mock_observation(_face(now, dx=45.0))
    running_app.tick(now)
    assert running_app.state == SystemState.TRACK_FACE
    before = running_app.servo.get_angles()

    lost_at = now + 5.0
    lost = VisionObservation(lost_at, False, 0, (0, 0, 0, 0), 0, 20)
    running_app.vision.set_mock_observation(lost)
    running_app.tick(lost_at)
    assert running_app.state == SystemState.TRACK_FACE
    assert running_app.servo.get_angles() == before

    now = lost_at + 0.05
    running_app.vision.set_mock_observation(_face(now, dx=-70.0))
    running_app.tick(now)
    assert running_app.state == SystemState.TRACK_FACE
    assert running_app.servo.current_yaw < before[0]


def test_fast_exit_starts_bounded_search_then_holds(running_app):
    now = _start_search(running_app)
    running_app.vision.set_mock_observation(_face(now, dx=14.0))
    running_app.tick(now)
    now += 0.07
    running_app.vision.set_mock_observation(_face(now, dx=78.0))
    running_app.tick(now)
    yaw_before, pitch_before = running_app.servo.get_angles()

    def tick_without_face(timestamp):
        missing = VisionObservation(timestamp, False, 0, (0, 0, 0, 0), 0, 20)
        running_app.vision.set_mock_observation(missing)
        running_app.tick(timestamp)

    lost_at = now + 0.08
    tick_without_face(lost_at)
    assert running_app.servo.get_angles() == (yaw_before, pitch_before)
    for n in range(1, 55):
        tick_without_face(lost_at + n / 30)
    yaw_after, pitch_after = running_app.servo.get_angles()
    assert 15.0 < yaw_after - yaw_before <= 22.0
    assert pitch_after == pitch_before
    tick_without_face(lost_at + 2.0)
    assert running_app.servo.get_angles() == (yaw_after, pitch_after)

    now = lost_at + 2.1
    running_app.vision.set_mock_observation(_face(now, dx=-65.0))
    running_app.tick(now)
    assert running_app.state == SystemState.TRACK_FACE
    assert running_app.servo.current_yaw < yaw_after


def test_vertical_exit_begins_search_but_camera_stall_holds(running_app):
    now = _start_search(running_app)
    running_app.vision.set_mock_observation(_face(now, dy=-155.0))
    running_app.tick(now)
    before = running_app.servo.get_angles()
    running_app.tick(now + 0.5)
    running_app.tick(now + 0.7)
    assert running_app.servo.get_angles() == before

    current = now + 0.80
    missing = VisionObservation(current, False, 0, (0, 0, 0, 0), 0, 20)
    running_app.vision.set_mock_observation(missing)
    running_app.tick(current)
    assert running_app.servo.current_pitch > before[1]
    after = running_app.servo.get_angles()
    running_app.tick(current + 0.4)
    assert running_app.servo.get_angles() == after


def test_audio_is_drained_outside_idle(running_app):
    now = _start_search(running_app)
    running_app.audio.event_queue.put(AudioEvent(now, 50.0, "right", 0.9, "test"))
    running_app.vision.set_mock_observation(_face(now))
    running_app.tick(now)
    assert running_app.state == SystemState.TRACK_FACE
    assert running_app.audio.get_latest_event(block=False) is None


def test_safe_shutdown(app_config):
    app = create_app(app_config, dry_run=True, web=False)
    assert app.start()
    app.stop()
    assert not app.running
