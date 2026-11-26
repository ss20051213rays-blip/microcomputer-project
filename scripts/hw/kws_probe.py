"""在 AC3104 上独立测试离线唤醒和语音回应。"""

import argparse
from collections import deque
import math
from pathlib import Path
import shutil
import subprocess
import time
import wave

import numpy as np


SAMPLE_RATE = 16000
BLOCK_SIZE = 1024
PCM_SCALE = 32768
DEFAULT_KEYWORDS = Path(__file__).resolve().parents[2] / "configs/kws_wenetspeech.txt"
PLAYBACK_DEVICE = "hw:CARD=respeaker2micac,DEV=0"
PLAYBACK_STATUS = Path("/proc/asound/respeaker2micac/pcm0p/sub0/status")


class ReplyPlayback:
    def __init__(self, wav_path):
        self.command = ["aplay", "-q", "-D", PLAYBACK_DEVICE, str(wav_path)]
        self.process = None
        self.completed = 0
        self.resume_at = 0.0
        self.started_at = 0.0
        self.started = False

    def start(self, detected_at):
        self.started_at = detected_at
        self.started = False
        self.process = subprocess.Popen(self.command)

    def suppressing(self):
        now = time.monotonic()
        if self.process is None:
            return now < self.resume_at
        if not self.started and "state: RUNNING" in PLAYBACK_STATUS.read_text():
            self.started = True
            delay_ms = (now - self.started_at) * 1000
            print(f"[REPLY_START] {self.completed + 1} pcm_running_ms={delay_ms:.0f}", flush=True)
        result = self.process.poll()
        if result is None:
            if now - self.started_at > 5:
                raise TimeoutError("AC3104 放音超时")
            return True
        self.process = None
        if result != 0 or not self.started:
            raise RuntimeError(f"AC3104 放音验证失败（aplay 退出码 {result}）")
        self.completed += 1
        self.resume_at = now + 0.5
        print(f"[REPLY] {self.completed} 我在", flush=True)
        return True

    def wait_for_finish(self):
        while self.process is not None:
            self.suppressing()
            time.sleep(0.01)

    def close(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait()


def read_wav(path, require_stereo=False):
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        if (channels not in (1, 2) or source.getsampwidth() != 2
                or source.getframerate() != SAMPLE_RATE or not source.getnframes()):
            raise ValueError("测试 WAV 须含 16 kHz、16 位的单声道或双声道 PCM")
        if require_stereo and channels != 2:
            raise ValueError("双麦测向须使用立体声 WAV")
        while pcm := source.readframes(BLOCK_SIZE):
            yield np.frombuffer(pcm, dtype="<i2").reshape(-1, channels), False
    # Provide trailing audio for a keyword at the end of a file.
    yield np.zeros((SAMPLE_RATE * 2 // 5, channels), dtype=np.int16), False


def read_mics(device_name, seconds):
    import sounddevice as sd

    device = next(
        (index for index, info in enumerate(sd.query_devices())
         if device_name.casefold() in info["name"].casefold()
         and info["max_input_channels"] >= 2),
        None,
    )
    if device is None:
        raise ValueError(f"未找到双声道输入设备 {device_name!r}")

    with sd.InputStream(device=device, samplerate=SAMPLE_RATE, channels=2,
                        dtype="int16", blocksize=BLOCK_SIZE) as microphone:
        print(f"[READY] {sd.query_devices(device)['name']} · 监听 {seconds:g} 秒", flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            yield microphone.read(BLOCK_SIZE)


def run_probe(spotter, blocks, input_gain, reply=None, max_hits=None,
              direction=None, expected_angle=None):
    stream = spotter.create_stream()
    samples = hits = overflows = 0
    peak_rms = 0.0
    valid_directions = 0
    history = deque(maxlen=math.ceil(2 * SAMPLE_RATE / BLOCK_SIZE))
    wall_start = time.monotonic()
    cpu_start = time.process_time()
    try:
        for pcm, overflowed in blocks:
            overflows += int(overflowed)
            samples += len(pcm)
            if reply is not None and reply.suppressing():
                history.clear()
                continue
            if hits == max_hits:
                break
            if overflowed:
                spotter.reset_stream(stream)
                history.clear()
            if direction is not None:
                history.append(pcm)
            mono = pcm.mean(axis=1, dtype=np.float32) / PCM_SCALE
            peak_rms = max(peak_rms, float(np.sqrt(np.mean(mono * mono))))
            if input_gain != 1.0:
                mono *= input_gain
                np.clip(mono, -1.0, 1.0, out=mono)
            stream.accept_waveform(SAMPLE_RATE, mono)
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
                if keyword := spotter.get_result(stream):
                    detected_at = time.monotonic()
                    hits += 1
                    print(f"[HIT] {hits} {samples / SAMPLE_RATE:.3f}s {keyword}", flush=True)
                    if direction is not None:
                        # Use synchronized PCM from before the reply and before gain/mono conversion.
                        latest = np.concatenate(history, axis=0)[-SAMPLE_RATE:]
                        result = direction.estimate_speech_direction(latest.astype(np.float32) / PCM_SCALE)
                        valid_directions += int(result.angle_deg is not None)
                        angle = "na" if result.angle_deg is None else f"{result.angle_deg:+.2f}"
                        delay = "na" if result.delay_s is None else f"{result.delay_s * 1e6:+.1f}"
                        target = "na" if expected_angle is None else f"{expected_angle:+g}"
                        print(
                            f"[DOA] hit={hits} expected_deg={target} angle_deg={angle} "
                            f"side={result.side} confidence={result.confidence:.3f} "
                            f"tau_us={delay} method={result.method} "
                            f"frames={result.agreeing_frames}/{result.voiced_frames}",
                            flush=True,
                        )
                    if reply is not None:
                        reply.start(detected_at)
                        # Drop context from before the speaker cooldown.
                        stream = spotter.create_stream()
                        break
                    spotter.reset_stream(stream)
                    if hits == max_hits:
                        break
        if reply is not None:
            reply.wait_for_finish()
    except KeyboardInterrupt:
        print("[STOP] 测试中断", flush=True)
    finally:
        blocks.close()
        if reply is not None:
            reply.close()

    cpu_seconds = time.process_time() - cpu_start
    wall_seconds = time.monotonic() - wall_start
    print(
        f"[SUMMARY] hits={hits} audio_s={samples / SAMPLE_RATE:.3f} "
        f"wall_s={wall_seconds:.3f} cpu_s={cpu_seconds:.3f} "
        f"single_core_pct={100 * cpu_seconds / wall_seconds:.1f} "
        f"overflows={overflows} peak_rms={peak_rms:.5f} "
        f"replies={reply.completed if reply is not None else 0}"
        + (f" doa_valid={valid_directions}" if direction is not None else ""),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS)
    parser.add_argument("--device", default="respeaker-2mic-ac3104")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--score", type=float, default=1.0)
    parser.add_argument("--input-gain", type=float, default=1.0, help="输入送入模型前的增益倍数")
    parser.add_argument("--wav", type=Path, help="用 16 kHz PCM WAV 做离线验证")
    parser.add_argument("--reply-wav", type=Path, help="每次命中通过 AC3104 播放的 16 kHz 立体声 WAV")
    parser.add_argument("--max-hits", type=int, help="达到该命中数后结束本轮")
    parser.add_argument("--doa", action="store_true", help="记录唤醒词的双麦方位")
    parser.add_argument("--mic-spacing-m", type=float, default=0.048, help="GCC-PHAT 使用的有效双麦间距")
    parser.add_argument("--expected-angle", type=float, help="记录标定站位的水平角度")
    args = parser.parse_args()
    if not 0 < args.seconds <= 600:
        parser.error("--seconds 必须大于 0 且最多 600 秒")
    if not 0 < args.threshold <= 1:
        parser.error("--threshold 必须在 (0, 1]")
    if any(not math.isfinite(value) or value <= 0 for value in (args.score, args.input_gain)):
        parser.error("--score 和 --input-gain 必须为有限正数")
    if args.max_hits is not None and args.max_hits < 1:
        parser.error("--max-hits 必须是正整数")
    if not 0 < args.mic_spacing_m <= 0.25:
        parser.error("--mic-spacing-m 必须在 (0, 0.25] 米内")
    if args.expected_angle is not None and not -90 <= args.expected_angle <= 90:
        parser.error("--expected-angle 必须在 −90° 到 +90° 之间")
    if args.reply_wav is not None:
        if args.wav:
            parser.error("--reply-wav 只用于双麦实机测试")
        if not shutil.which("aplay") or not PLAYBACK_STATUS.is_file():
            parser.error("播放回应需要 AC3104 播放设备和 aplay")
        try:
            with wave.open(str(args.reply_wav), "rb") as clip:
                if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) != (2, 2, SAMPLE_RATE):
                    parser.error("--reply-wav 须为 16 kHz、16 位立体声 WAV")
                if not 0 < clip.getnframes() <= 4 * SAMPLE_RATE:
                    parser.error("--reply-wav 的时长须在 0–4 秒之间")
        except (OSError, EOFError, wave.Error) as error:
            parser.error(str(error))

    model_paths = {
        part: args.model_dir / f"{part}-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        for part in ("encoder", "decoder", "joiner")
    }
    model_paths["tokens"] = args.model_dir / "tokens.txt"
    model_paths["keywords_file"] = args.keywords
    for path in model_paths.values():
        if not path.is_file():
            parser.error(f"找不到文件 {path}")

    import sherpa_onnx

    spotter = sherpa_onnx.KeywordSpotter(
        **{name: str(path) for name, path in model_paths.items()},
        sample_rate=SAMPLE_RATE,
        num_threads=1,
        max_active_paths=4,
        keywords_threshold=args.threshold,
        keywords_score=args.score,
        provider="cpu",
    )
    print(
        f"[CONFIG] threshold={args.threshold:g} score={args.score:g} input_gain={args.input_gain:g}",
        flush=True,
    )
    direction = None
    if args.doa:
        from pantilt.adapters.perception.audio import AudioPipeline

        direction = AudioPipeline({"sample_rate": SAMPLE_RATE, "mic_spacing_m": args.mic_spacing_m})
        print(f"[DOA_CONFIG] mic_spacing_m={direction.mic_spacing:g} audio_zero_deg=0 window_s=1",
              flush=True)
    blocks = read_wav(args.wav, require_stereo=args.doa) if args.wav else read_mics(args.device, args.seconds)
    reply = ReplyPlayback(args.reply_wav) if args.reply_wav else None
    run_probe(spotter, blocks, args.input_gain, reply, args.max_hits, direction, args.expected_angle)


if __name__ == "__main__":
    main()
