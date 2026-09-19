import sys
import os
import time

# 将项目根目录加入 import 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import load_config, setup_logger
from src.servo import ServoController

def main():
    config = load_config("configs/default.yaml")
    logger = setup_logger(config)
    
    dry_run = "--dry-run" in sys.argv
    
    try:
        servo = ServoController(config['servo'], dry_run=dry_run)
    except Exception as e:
        print(f"初始化舵机失败: {e}")
        sys.exit(1)
        
    try:
        servo.center()
        print("\n=== 舵机扫掠测试 ===")
        print("说明: 本脚本用于验证舵机软件限位、方向是否正确。")
        print("指令列表:")
        print("  c  : 回中 (0°)")
        print("  l  : 左转 (-30°)")
        print("  r  : 右转 (+30°)")
        print("  s  : 自动往复扫掠 (0 -> -30 -> +30 -> 0)")
        print("  q  : 退出并关闭 PWM")
        
        while True:
            cmd = input("\n输入指令 (c/l/r/s/q) 或输入具体角度: ").strip().lower()
            if cmd == 'q':
                break
            elif cmd == 'c':
                servo.center()
            elif cmd == 'l':
                servo.set_angle(-30.0)
            elif cmd == 'r':
                servo.set_angle(30.0)
            elif cmd == 's':
                print("开始扫掠... (按 Ctrl+C 停止当前动作)")
                try:
                    servo.center()
                    time.sleep(1)
                    servo.set_angle(-30.0)
                    time.sleep(1)
                    servo.set_angle(30.0)
                    time.sleep(1)
                    servo.center()
                except KeyboardInterrupt:
                    print("\n扫掠被中断")
            else:
                try:
                    val = float(cmd)
                    servo.set_angle(val)
                except ValueError:
                    print("未知指令，请输入数字或预设字母。")
    except KeyboardInterrupt:
        print("\n用户强制退出。")
    finally:
        servo.disable()

if __name__ == "__main__":
    main()

