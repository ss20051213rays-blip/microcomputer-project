"""双轴跟踪速度和加减速约束。"""

import pytest

from pantilt.domain.controller import DeadzoneStepController
from pantilt.domain.types import VisionObservation

PERIOD = 1.0 / 30.0


@pytest.fixture
def controller():
    return DeadzoneStepController({"observation_timeout_s": 0.3}, {})


def obs(dx=0.0, dy=0.0, *, timestamp=1.0, found=True):
    return VisionObservation(timestamp, found, dx, (10, 10, 50, 50), 0.9, 12.5, dy_px=dy)


def test_large_error_ramps_up_across_control_ticks_with_same_frame(controller):
    frame = obs(dx=-1000, dy=-1000)
    first = controller.compute_steps(frame, 1.0)
    second = controller.compute_steps(frame, 1.0 + PERIOD)
    assert first == pytest.approx((-210 * PERIOD**2 / 2, 150 * PERIOD**2 / 2))
    assert second == pytest.approx(tuple(3 * step for step in first))


def test_output_is_limited_per_axis(controller):
    for tick in range(30):
        now = 1.0 + tick * PERIOD
        yaw, pitch = controller.compute_steps(obs(dx=1000, dy=1000, timestamp=now), now)
        assert 0.0 < yaw <= 42 * PERIOD
        assert -28 * PERIOD <= pitch < 0.0
    assert (yaw, pitch) == pytest.approx((42 * PERIOD, -28 * PERIOD))


def test_small_error_slows_near_deadzone(controller):
    assert controller.compute_steps(obs(dx=30, dy=25), 1.0) == (0.0, 0.0)
    frame = obs(dx=31, dy=-26)
    controller.compute_steps(frame, 1.0 + PERIOD)
    assert controller.compute_steps(frame, 1.0 + 2 * PERIOD) == pytest.approx((0.5 * PERIOD, 0.4 * PERIOD))


def test_reversal_decelerates_through_zero(controller):
    right = obs(dx=200)
    controller.compute_steps(right, 1.0)
    controller.compute_steps(right, 1.0 + PERIOD)
    left = obs(dx=-200, timestamp=1.0 + 2 * PERIOD)
    steps = [controller.compute_steps(left, 1.0 + tick * PERIOD)[0]
             for tick in range(2, 5)]
    assert steps[0] > steps[1] > 0 > steps[2]


def test_repeated_tick_and_delayed_tick_do_not_add_extra_motion(controller):
    frame = obs(dx=1000)
    controller.compute_steps(frame, 1.0)
    assert controller.compute_steps(frame, 1.0) == (0.0, 0.0)
    assert controller.compute_steps(frame, 1.2)[0] == pytest.approx(1.5 * 210 * PERIOD**2)


@pytest.mark.parametrize("lost", [None, obs(found=False), obs(dx=120, timestamp=0.0)])
def test_missing_or_expired_frame_holds_and_resets_speed(controller, lost):
    frame = obs(dx=200, dy=-100)
    initial = controller.compute_steps(frame, 1.0)
    controller.compute_steps(frame, 1.0 + PERIOD)
    assert controller.compute_steps(lost, 1.0 + 2 * PERIOD) == (0.0, 0.0)
    reacquired = obs(dx=200, dy=-100, timestamp=1.0 + 3 * PERIOD)
    assert controller.compute_steps(reacquired, reacquired.timestamp_mono) == pytest.approx(initial)
