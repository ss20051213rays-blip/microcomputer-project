import sys
import os
import time
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.config import load_config, setup_logger
from src.audio import AudioPipeline

def main():
    parser = argparse.ArgumentParser(description="GCC-PHAT 角度估计精准度测试工具")
    args = parser.parse_args()

    config = load_config("configs/default.yaml")
    logger = setup_logger(config)
    
    print("=== GCC-PHAT 方位角测试 ===")
    print("说明: 本脚本用于专门验证 GCC-PHAT 在触发后的角度计算是否准确。")
    print("测试方法:")
    print("  1. 站在云台正前方(0°)，拍手 3 次")
    print("  2. 站在云台左侧(-30°)，拍手 3 次")
    print("  3. 站在云台右侧(+30°)，拍手 3 次")
    print("--------------------------------------------------")
    
    pipeline = AudioPipeline(config['audio'])
    if not pipeline.start():
        sys.exit(1)
        
    print("[+] 启动成功。等待拍手触发...\n")
    
    try:
        while True:
            event = pipeline.get_latest_event(block=True, timeout=1.0)
            if event:
                if event.method == "energy_diff":
                    print(f"⚠️ [降级模式] GCC-PHAT 置信度过低({event.confidence:.3f})，退化为能量差侧别。")
                    print(f"   => 判决侧别: {event.side}, 固定分配角度: {event.theta_audio_deg}°")
                else:
                    print(f"🎯 [精确定位] 算法: {event.method}, 侧别: {event.side}")
                    print(f"   => 计算出角度: {event.theta_audio_deg:.1f}° (置信度: {event.confidence:.3f})")
                print("-" * 50)
    except KeyboardInterrupt:
        print("\n测试结束。")
    finally:
        pipeline.stop()

if __name__ == "__main__":
    main()

