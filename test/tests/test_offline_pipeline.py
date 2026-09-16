from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.audio import MockAudioSource, delay_to_azimuth_deg, gcc_phat_delay
from src.config import load_config
from src.app import State, build_demo_controller, run_offline_demo
from src.servo import MockServo
from src.vision import FaceTracker, MockVisionSource


class TestAudioAlgorithm(unittest.TestCase):
    def test_gcc_phat_recovers_delay(self):
        n = 256
        wave = []
        for i in range(n):
            t = i / 16000.0
            wave.append(math.sin(2 * math.pi * 900 * t) * math.exp(-20 * t))
        delay = 5  # right lags left by 5 samples
        left = wave
        right = [wave[(i - delay) % n] for i in range(n)]
        est = gcc_phat_delay(left, right, max_tau=20)
        self.assertEqual(est, delay)

    def test_delay_to_azimuth_sign(self):
        # Right-leading (negative lag) should map to positive azimuth.
        az = delay_to_azimuth_deg(-3, sample_rate=16000, mic_distance_m=0.06, speed_of_sound=343.0)
        self.assertGreater(az, 0)


class TestVisionAndServo(unittest.TestCase):
    def test_face_dx(self):
        cfg = load_config()
        tracker = FaceTracker(cfg)
        event = tracker.process(cfg.image_center_x + 50)
        self.assertTrue(event.face_found)
        self.assertAlmostEqual(event.dx_px, 50)

    def test_servo_limits(self):
        cfg = load_config()
        servo = MockServo(cfg)
        self.assertEqual(servo.set_angle(999), cfg.servo_max_deg)
        self.assertEqual(servo.set_angle(-999), cfg.servo_min_deg)


class TestStateMachine(unittest.TestCase):
    def test_full_offline_flow(self):
        controller = run_offline_demo(seconds=5.0)
        states = [row.state for row in controller.logs]
        self.assertIn("TURN_ONCE", states)
        self.assertIn("FOLLOW", states)
        self.assertEqual(controller.state, State.IDLE)
        self.assertAlmostEqual(controller.servo.get_angle(), controller.config.servo_center_deg, places=3)

    def test_follow_moves_toward_face(self):
        cfg = load_config()
        audio = MockAudioSource(cfg, script=[{"t": 0.1, "azimuth_deg": 0.0}])
        vision = MockVisionSource(cfg, script=[{"t": 0.0, "face_x": cfg.image_center_x + 120}])
        servo = MockServo(cfg)
        controller = build_demo_controller(cfg)
        controller.audio = audio
        controller.vision = vision
        controller.servo = servo

        for _ in range(int(2.5 * cfg.control_hz)):
            controller.tick()

        self.assertGreaterEqual(controller.servo.get_angle(), 0.0)


if __name__ == "__main__":
    unittest.main()
