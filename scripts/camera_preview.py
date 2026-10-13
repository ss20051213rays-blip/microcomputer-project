import sys
import os
import time
import argparse

try:
    import cv2
except ImportError:
    print("Error: OpenCV not installed. Run: pip install opencv-python")
    sys.exit(1)

# 加入项目根目录
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.config import load_config, setup_logger
from src.vision import CameraCapture

def main():
    parser = argparse.ArgumentParser(description="摄像头取流与测试预览")
    parser.add_argument("--seconds", type=float, default=10.0, help="测试运行时长 (秒)")
    args = parser.parse_args()

    config = load_config(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "default.yaml")))
    logger = setup_logger(config)
    
    cam = CameraCapture(config['camera'])
    if not cam.start():
        print("[-] 摄像头启动失败，请检查 /dev/video 是否存在。")
        sys.exit(1)
        
    print(f"[*] 准备预热，测试运行时长 {args.seconds}s...")
    
    frames_counted = 0
    start_time = time.time()
    
    try:
        # 等待相机预热出图
        time.sleep(1)
        
        # 保存一张样本图测试方向
        frame = cam.get_latest_frame()
        if frame is not None:
            out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "test_frame.jpg"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            cv2.imwrite(out_path, frame)
            print(f"[+] 成功保存测试样图至: {out_path}，请核实方向是否颠倒。")
        else:
            print("[-] 未能获取到初始图像。")
            
        print("[*] 正在测试取帧性能 (无头模式，不弹窗显示)...")
        while time.time() - start_time < args.seconds:
            frame = cam.get_latest_frame()
            if frame is not None:
                frames_counted += 1
            # 模拟后端的处理延迟
            time.sleep(0.03)
            
        fps = frames_counted / args.seconds
        print(f"\n[+] 测试完成! 实测空跑提取帧率: {fps:.1f} FPS")
        if fps < 10:
            print("[!] 帧率低于 10 FPS，可能会影响后续视觉跟随的顺滑度。")
            
    except KeyboardInterrupt:
        print("\n测试被中断。")
    finally:
        cam.stop()

if __name__ == "__main__":
    main()

