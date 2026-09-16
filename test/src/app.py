from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .config import AppConfig, load_config
from .interfaces import AudioEvent, VisionEvent
from .audio import MockAudioSource
from .vision import MockVisionSource
from .servo import MockServo


class State(str, Enum):
    IDLE = "IDLE"
    TURN_ONCE = "TURN_ONCE"
    FOLLOW = "FOLLOW"


@dataclass
class StepLog:
    t: float
    state: str
    angle: float
    note: str


@dataclass
class Controller:
    config: AppConfig
    audio: MockAudioSource
    vision: MockVisionSource
    servo: MockServo
    state: State = State.IDLE
    t: float = 0.0
    target_angle: Optional[float] = None
    turn_elapsed: float = 0.0
    face_lost_elapsed: float = 0.0
    logs: List[StepLog] = field(default_factory=list)

    def _log(self, note: str) -> None:
        self.logs.append(
            StepLog(t=round(self.t, 3), state=self.state.value, angle=round(self.servo.get_angle(), 2), note=note)
        )

    def on_audio(self, event: AudioEvent) -> None:
        if self.state == State.IDLE and event.clap_detected and event.azimuth_deg is not None:
            self.target_angle = self.servo.clamp(event.azimuth_deg)
            self.state = State.TURN_ONCE
            self.turn_elapsed = 0.0
            self._log(f"clap -> turn to {self.target_angle:.1f} deg (energy={event.energy:.2f})")

    def on_vision(self, event: VisionEvent) -> None:
        if self.state != State.FOLLOW:
            return

        if event.face_found and event.dx_px is not None:
            self.face_lost_elapsed = 0.0
            dx = event.dx_px
            if abs(dx) <= self.config.follow_deadzone_px:
                self._log(f"follow hold dx={dx:.1f}px")
                return
            direction = 1.0 if dx > 0 else -1.0
            new_angle = self.servo.step(direction * self.config.follow_step_deg)
            self._log(f"follow step dx={dx:.1f}px -> {new_angle:.1f} deg")
            return

        self.face_lost_elapsed += 1.0 / self.config.control_hz
        if self.face_lost_elapsed >= self.config.face_lost_timeout_s:
            self.servo.center()
            self.state = State.IDLE
            self.face_lost_elapsed = 0.0
            self._log("face lost timeout -> center + IDLE")

    def tick(self) -> None:
        dt = 1.0 / self.config.control_hz
        self.t += dt

        # Always sample sensors; audio only acts in IDLE.
        audio_event = self.audio.read()
        vision_event = self.vision.read()
        self.on_audio(audio_event)

        if self.state == State.TURN_ONCE and self.target_angle is not None:
            self.turn_elapsed += dt
            # Open-loop: jump toward target with small steps for observability.
            current = self.servo.get_angle()
            err = self.target_angle - current
            if abs(err) <= self.config.turn_tolerance_deg or self.turn_elapsed >= self.config.turn_timeout_s:
                self.servo.set_angle(self.target_angle)
                self.state = State.FOLLOW
                self.face_lost_elapsed = 0.0
                self._log("turn done -> FOLLOW")
            else:
                step = max(-8.0, min(8.0, err))
                self.servo.set_angle(current + step)
                self._log(f"turning err={err:.1f}")

        self.on_vision(vision_event)


def build_demo_controller(config: Optional[AppConfig] = None) -> Controller:
    cfg = config or load_config()
    audio = MockAudioSource(
        cfg,
        script=[
            {"t": 0.4, "azimuth_deg": 30.0},
        ],
    )
    vision = MockVisionSource(
        cfg,
        script=[
            # After turn, face appears slightly right of center, then moves further right, then lost.
            {"t": 1.0, "face_x": 360},
            {"t": 1.5, "face_x": 420},
            {"t": 2.2, "face_x": 470},
            {"t": 3.0, "face_x": None},
        ],
    )
    servo = MockServo(cfg)
    return Controller(config=cfg, audio=audio, vision=vision, servo=servo)


def run_offline_demo(seconds: float = 4.0, config_path: Optional[str] = None) -> Controller:
    cfg = load_config(config_path)
    controller = build_demo_controller(cfg)
    steps = int(seconds * cfg.control_hz)
    for _ in range(steps):
        controller.tick()
    return controller


def main() -> None:
    controller = run_offline_demo()
    print("Offline PTZ mock demo finished")
    print(f"final_state={controller.state.value} final_angle={controller.servo.get_angle():.1f}")
    print("--- timeline ---")
    for row in controller.logs:
        print(f"t={row.t:5.2f}s  {row.state:10s}  angle={row.angle:6.1f}  {row.note}")


if __name__ == "__main__":
    main()
