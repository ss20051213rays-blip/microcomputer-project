from __future__ import annotations

import cmath
import math
from typing import List, Optional, Sequence, Tuple

from .config import AppConfig
from .interfaces import AudioEvent


def rms_energy(frame: Sequence[float]) -> float:
    if not frame:
        return 0.0
    acc = 0.0
    for x in frame:
        acc += x * x
    return math.sqrt(acc / len(frame))


def _fft(values: List[complex]) -> List[complex]:
    n = len(values)
    if n == 1:
        return values
    if n & (n - 1):
        raise ValueError("FFT length must be power of 2")
    even = _fft(values[0::2])
    odd = _fft(values[1::2])
    out = [0j] * n
    for k in range(n // 2):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        out[k] = even[k] + twiddle
        out[k + n // 2] = even[k] - twiddle
    return out


def _ifft(values: List[complex]) -> List[complex]:
    n = len(values)
    conjugated = [v.conjugate() for v in values]
    forward = _fft(conjugated)
    return [v.conjugate() / n for v in forward]


def gcc_phat_delay(left: Sequence[float], right: Sequence[float], max_tau: int) -> int:
    n = 1
    need = len(left) + len(right)
    while n < need:
        n *= 2

    left_c = [complex(x, 0.0) for x in left] + [0j] * (n - len(left))
    right_c = [complex(x, 0.0) for x in right] + [0j] * (n - len(right))
    left_f = _fft(left_c)
    right_f = _fft(right_c)

    # Peak lag = delay of right relative to left.
    cross = []
    for a, b in zip(left_f, right_f):
        prod = b * a.conjugate()
        mag = abs(prod)
        cross.append(prod / mag if mag > 1e-12 else 0j)

    cc = _ifft(cross)
    # Build window around zero lag: [-max_tau, +max_tau]
    window = [cc[n + i].real for i in range(-max_tau, 0)] + [cc[i].real for i in range(0, max_tau + 1)]
    shift = max(range(len(window)), key=lambda i: window[i]) - max_tau
    return int(shift)


def delay_to_azimuth_deg(
    delay_samples: int,
    sample_rate: int,
    mic_distance_m: float,
    speed_of_sound: float,
) -> float:
    """Map lag(right behind left) to azimuth.

    Convention:
    - positive azimuth = source on the right
    - source on the right => right mic leads => delay_samples < 0
    """
    tau = delay_samples / float(sample_rate)
    max_tau = mic_distance_m / speed_of_sound
    ratio = 0.0 if max_tau <= 0 else max(-1.0, min(1.0, -tau / max_tau))
    return math.degrees(math.asin(ratio))


class ClapLocalizer:
    def __init__(self, config: AppConfig):
        self.config = config
        self._cooldown = 0.0
        max_tau_sec = config.mic_distance_m / config.speed_of_sound
        self.max_tau = max(1, int(round(max_tau_sec * config.sample_rate)))

    def process(self, left: Sequence[float], right: Sequence[float], dt: float) -> AudioEvent:
        energy = 0.5 * (rms_energy(left) + rms_energy(right))
        self._cooldown = max(0.0, self._cooldown - dt)
        if energy < self.config.clap_energy_threshold or self._cooldown > 0:
            return AudioEvent(clap_detected=False, azimuth_deg=None, energy=energy)

        delay = gcc_phat_delay(left, right, self.max_tau)
        azimuth = delay_to_azimuth_deg(
            delay,
            self.config.sample_rate,
            self.config.mic_distance_m,
            self.config.speed_of_sound,
        )
        self._cooldown = self.config.clap_cooldown_s
        return AudioEvent(clap_detected=True, azimuth_deg=azimuth, energy=energy)


class MockAudioSource:
    def __init__(self, config: AppConfig, script: Optional[Sequence[dict]] = None):
        self.config = config
        self.localizer = ClapLocalizer(config)
        self.script: List[dict] = list(script or [])
        self.t = 0.0
        self.dt = config.frame_ms / 1000.0
        self._cursor = 0

    def _synthetic_pair(self, azimuth_deg: float, amplitude: float = 1.0) -> Tuple[List[float], List[float]]:
        n = self.config.frame_samples
        wave = []
        for i in range(n):
            t = i / self.config.sample_rate
            wave.append(amplitude * math.sin(2 * math.pi * 1200 * t) * math.exp(-35 * t))

        max_tau = self.config.mic_distance_m / self.config.speed_of_sound
        tau = max_tau * math.sin(math.radians(azimuth_deg))
        # Positive azimuth (right): right mic leads => advance right channel.
        delay = int(round(tau * self.config.sample_rate))
        left = list(wave)
        right = [wave[(i + delay) % n] for i in range(n)]
        return left, right

    def read(self) -> AudioEvent:
        self.t += self.dt
        left = [0.0] * self.config.frame_samples
        right = [0.0] * self.config.frame_samples
        if self._cursor < len(self.script):
            item = self.script[self._cursor]
            if self.t >= float(item["t"]):
                left, right = self._synthetic_pair(float(item["azimuth_deg"]), float(item.get("amp", 1.0)))
                self._cursor += 1
        return self.localizer.process(left, right, self.dt)
