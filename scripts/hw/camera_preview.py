import sys
import time
import argparse

from pantilt.adapters.perception.vision import CameraCapture, VisionPipeline, cv2
from pantilt.adapters.runtime.desktop import DesktopPreview
from pantilt.infrastructure.config import load_config, setup_logger
from pantilt.infrastructure.paths import DATA_DIR, DEFAULT_CONFIG


def desktop_preview(config):
    vision = VisionPipeline(config['camera'])
    preview = DesktopPreview()
    try:
        if not vision.start():
            return 1
        while preview.show(vision):
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        vision.stop()
        preview.close()
    return 0

def main():
    parser = argparse.ArgumentParser(description="摄像头取流与测试预览")
    parser.add_argument("--seconds", type=float, default=10.0, help="测试运行时长 (秒)")
    parser.add_argument("--desktop", action="store_true", help="在桌面显示实时画面，按 Q 或 Esc 退出")
    args = parser.parse_args()
    if cv2 is None:
        parser.exit(1, "摄像头预览需要 OpenCV。\n")

    config = load_config(DEFAULT_CONFIG)
    logger = setup_logger(config)
    if args.desktop:
        return desktop_preview(config)
    
    cam = CameraCapture(config['camera'])
    if not cam.start():
        print("[-] 摄像头启动失败，请检查 /dev/video 是否存在。")
        sys.exit(1)
        
    print(f"[*] 准备预热，测试运行时长 {args.seconds}s...")
    
    frames_counted = 0
    
    try:
        # 等待相机预热出图
        time.sleep(1)
        
        # 保存一张样本图测试方向
        frame = cam.get_latest_frame()
        if frame is not None:
            out_path = DATA_DIR / "test_frame.jpg"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_path), frame)
            print(f"[+] 成功保存测试样图至: {out_path}，请核实方向是否颠倒。")
        else:
            print("[-] 未能获取到初始图像。")
            
        print("[*] 正在测量不同采集时间戳的画面数 (无头模式)...")
        _, captured_at = cam.get_latest_frame_sample(copy=False)
        started = time.monotonic()
        deadline = started + args.seconds
        while (remaining := deadline - time.monotonic()) > 0:
            _, new_capture = cam.wait_for_frame(captured_at, timeout=remaining)
            if new_capture is not None and new_capture <= deadline:
                captured_at = new_capture
                frames_counted += 1

        fps = frames_counted / max(time.monotonic() - started, 1e-9)
        print(f"\n[+] 实测应用收到的解码画面: {fps:.1f} FPS")
        if fps < 10:
            print("[!] 帧率低于 10 FPS，可能会影响后续视觉跟随的顺滑度。")
            
    except KeyboardInterrupt:
        print("\n测试被中断。")
    finally:
        cam.stop()

if __name__ == "__main__":
    raise SystemExit(main())

