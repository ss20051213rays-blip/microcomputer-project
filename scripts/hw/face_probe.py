import sys
import os
import time
import argparse

try:
    import cv2
except ImportError:
    print("cv2 needed.")
    sys.exit(1)

from pantilt.adapters.perception.vision import CameraCapture, FaceDetector
from pantilt.infrastructure.config import load_config, setup_logger
from pantilt.infrastructure.paths import DEFAULT_CONFIG

def main():
    parser = argparse.ArgumentParser(description="人脸检测与 dx 像素偏差测试")
    parser.add_argument("--seconds", type=float, default=15.0, help="测试时长")
    args = parser.parse_args()

    config = load_config(DEFAULT_CONFIG)
    logger = setup_logger(config)
    
    print("=== 人脸检测性能测试 ===")
    
    cam = CameraCapture(config['camera'])
    detector = FaceDetector(config['camera'])
    
    if not cam.start():
        sys.exit(1)
        
    print("[*] 启动成功，预热中...")
    time.sleep(1)
    
    start_time = time.time()
    try:
        while time.time() - start_time < args.seconds:
            frame = cam.get_latest_frame()
            if frame is not None:
                obs = detector.process_frame(frame)
                if obs.face_found:
                    print(f"[✅ 检测到人脸] dx: {obs.dx_px:>6.1f} px | 置信度: {obs.confidence:.2f} | 检出帧率: {obs.fps:.1f} FPS")
                else:
                    # 偶尔打印未检测到
                    if int(time.time()*10) % 10 == 0:
                        print(f"[❌ 无人脸] 视野中未找到目标... 检出帧率: {obs.fps:.1f} FPS")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        detector.close()
        print("\n[+] 测试结束。")

if __name__ == "__main__":
    main()
