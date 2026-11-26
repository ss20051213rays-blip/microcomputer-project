"""Phase 4 hardware acceptance using the production tracking loop."""

import argparse
import csv
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from pantilt.adapters.actuation.servo import serial
from pantilt.adapters.perception.vision import FaceDetector
from pantilt.adapters.runtime.desktop import DesktopPreview
from pantilt.bootstrap import create_app
from pantilt.domain.types import AudioEvent, SystemState
from pantilt.infrastructure.config import load_config, setup_logger
from pantilt.infrastructure.paths import DEFAULT_CONFIG, LOG_DIR


PHASES = (
    (0, "horizontal", "开始左右走动，观察水平跟随。"),
    (45, "vertical", "开始起立、下蹲，观察俯仰跟随。"),
    (90, "center", "回到视野中央并站定，观察是否抖动。"),
    (105, "occlusion", "现在遮挡人脸，保持 3 秒。"),
    (108, "recovery", "移开遮挡，观察是否立即续跟。"),
)
TRACK_SECONDS = 120


def preflight(config):
    camera = config["camera"]
    servo = config["servo"]
    if (camera.get("target_mode"), camera.get("detector")) != ("face", "yunet"):
        raise RuntimeError("测试配置须使用 face 模式和 YuNet 检测器。")
    if servo.get("driver_type") != "bus":
        raise RuntimeError("双轴测试须使用总线舵机。")
    if serial is None:
        raise RuntimeError("树莓派 Python 环境缺少 pyserial。")
    detector = FaceDetector(camera)
    try:
        if detector.yunet is None:
            raise RuntimeError("YuNet 初始化失败。")
    finally:
        detector.close()
    for device in (f"/dev/video{camera.get('device_index', 0)}", servo["serial_port"]):
        if not Path(device).is_char_device() or not os.access(device, os.R_OK | os.W_OK):
            raise RuntimeError(f"设备不可读写：{device}")
    print("预检通过：YuNet 可加载，相机和舵机设备节点可访问。", flush=True)


def record_tracking(app, writer, preview=None):
    started = time.monotonic()
    app.audio.event_queue.put_nowait(AudioEvent(started, 0.0, "center", 1.0, "face_tracking_probe"))
    acquisition_deadline = started + app.state_machine.turn_timeout_s + app.state_machine.search_timeout_s + 2.0
    locked = None
    phase = -1
    interval = 1.0 / app.main_loop_hz
    while app.running:
        now = time.monotonic()
        app.tick(now)
        if preview is not None and not preview.show(app.vision, app.state.value):
            raise KeyboardInterrupt
        if locked is None and app.state == SystemState.TRACK_FACE:
            locked = now
        elapsed = now - locked if locked is not None else None
        if elapsed is not None:
            while phase + 1 < len(PHASES) and elapsed >= PHASES[phase + 1][0]:
                phase += 1
                print(PHASES[phase][2], flush=True)

        obs = app.last_vision_obs
        yaw, pitch = app.servo.get_angles()
        writer.writerow((
            round(now - started, 3), None if elapsed is None else round(elapsed, 3),
            PHASES[phase][1] if phase >= 0 else "acquisition", app.state.value,
            obs.timestamp_mono if obs else None, int(obs.face_found) if obs else None,
            obs.dx_px if obs and obs.face_found else None, obs.dy_px if obs and obs.face_found else None,
            obs.confidence if obs else None, obs.fps if obs else None, yaw, pitch,
        ))

        if elapsed is not None and elapsed >= TRACK_SECONDS:
            print("两分钟采样结束。请结合现场观察和 CSV 判定跟踪表现。", flush=True)
            return 0
        if locked is None and (now >= acquisition_deadline or app.state == SystemState.IDLE):
            raise RuntimeError("寻脸未锁定。请确认站位和取景后重试。")
        time.sleep(max(0.0, interval - (time.monotonic() - now)))
    return 1


def run_probe(config, output, desktop=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8", buffering=1) as stream:
        writer = csv.writer(stream)
        writer.writerow((
            "seconds_since_trigger", "seconds_since_lock", "phase", "state", "observation_mono",
            "face_found", "dx_px", "dy_px", "confidence", "detection_fps", "yaw_cmd_deg", "pitch_cmd_deg",
        ))
        print(f"记录文件：{output}", flush=True)
        print("请站在镜头正前方。5 秒后启动云台，Ctrl+C 可结束测试。", flush=True)
        time.sleep(5)
        preview = DesktopPreview() if desktop else None
        try:
            app = create_app(config, web=False)
            return run_tracking(app, writer, preview)
        finally:
            if preview is not None:
                preview.close()


def run_tracking(app, writer, preview):
    app.audio.dry_run = True
    app.console = None
    if app.servo.ser is None:
        raise RuntimeError("总线舵机串口未打开。")
    try:
        if not app.start():
            raise RuntimeError("跟踪应用启动失败。")
        # A previous shutdown may have disabled servo torque.
        for servo_id in (app.servo.yaw_id, app.servo.pitch_id):
            app.servo._send_bus_torque(servo_id, enable=True)
        return record_tracking(app, writer, preview)
    finally:
        try:
            app.stop()
        finally:
            if app.servo.ser is not None:
                app.servo.disable()


def stop_on_signal(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="阶段 4 人脸跟踪预检与两分钟实机测试")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="CSV 输出路径，使用新文件")
    parser.add_argument("--run", action="store_true", help="启动真机跟踪，舵机会运动")
    parser.add_argument("--desktop", action="store_true", help="同时在树莓派桌面显示跟踪画面")
    args = parser.parse_args()
    config = load_config(args.config)
    config.setdefault("logging", {})["log_to_file"] = False
    logger = setup_logger(config)
    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        preflight(config)
        if not args.run:
            return 0
        output = args.output or LOG_DIR / f"face-tracking-{datetime.now():%Y%m%d-%H%M%S}.csv"
        return run_probe(config, output, args.desktop)
    except KeyboardInterrupt:
        logger.info("测试已中止。")
        return 130
    except (OSError, RuntimeError) as exc:
        logger.error("测试失败：%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
