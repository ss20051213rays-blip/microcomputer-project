import sys
import os
import time
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.config import load_config, setup_logger
from src.audio import AudioPipeline

def main():
    parser = argparse.ArgumentParser(description="声音事件检测 (SED) 阈值调试工具")
    args = parser.parse_args()

    config = load_config(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "default.yaml")))
    # 为了清晰查看日志，我们配置 logger
    logger = setup_logger(config)
    
    print("=== SED 触发测试 ===")
    print(f"当前能量阈值 (energy_threshold): {config['audio'].get('energy_threshold', 0.05)}")
    print(f"当前防抖锁存 (min_event_gap_ms): {config['audio'].get('min_event_gap_ms', 300)}ms")
    print("--------------------------------------------------")
    print("[*] 正在启动音频管线...")
    
    pipeline = AudioPipeline(config['audio'])
    if not pipeline.start():
        sys.exit(1)
        
    print("[+] 启动成功。请在周围拍手、讲话或制造噪音。")
    print("[+] 观察终端输出，如果环境音频繁触发，请**调高** threshold。")
    print("[+] 如果拍手很难触发，请**调低** threshold。")
    print("[+] 如果拍一次手输出了两条事件，请**调高** gap_ms。")
    print("按 Ctrl+C 退出。\n")
    
    try:
        while True:
            event = pipeline.get_latest_event(block=True, timeout=1.0)
            if event:
                print(f"[✅ 检测到突发声] 侧别: {event.side:6s} | 角度: {event.theta_audio_deg:>6.1f}° | "
                      f"置信度: {event.confidence:.3f} | 算法: {event.method}")
    except KeyboardInterrupt:
        print("\n测试结束。")
    finally:
        pipeline.stop()

if __name__ == "__main__":
    main()

