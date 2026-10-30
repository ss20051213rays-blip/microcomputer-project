import sys
import os
import time

from pantilt.adapters.actuation.servo import ServoController
from pantilt.infrastructure.config import load_config, setup_logger
from pantilt.infrastructure.paths import DEFAULT_CONFIG

def basic_test(servo):
    print("\n[基础测试] 正在执行: 中位(0°) -> 左转(-30°) -> 右转(+30°) -> 回中(0°)")
    try:
        time.sleep(0.5)
        servo.center()
        time.sleep(1)
        servo.set_angle(-30.0)
        time.sleep(1)
        servo.set_angle(30.0)
        time.sleep(1)
        servo.center()
        print("[基础测试] 动作完成！请确认舵机是否顺畅执行了指令。")
    except KeyboardInterrupt:
        print("\n[基础测试] 中断，回中。")
        servo.center()

def stress_test(servo):
    print("\n[压力测试] 开始连续往复扫掠 (-30° 到 +30°)...")
    print("⚠️  提示：随时按下键盘组合键 【Ctrl + C】 即可安全暂停并返回主菜单！")
    try:
        servo.center()
        time.sleep(1.0)
        count = 1
        while True:
            print(f" -> 扫掠第 {count} 轮...")
            servo.set_angle(-30.0)
            time.sleep(0.8)
            servo.set_angle(30.0)
            time.sleep(0.8)
            count += 1
    except KeyboardInterrupt:
        print("\n[压力测试] 收到暂停指令！正在停止并让舵机回中...")
        servo.center()
        time.sleep(0.5)

def main():
    config = load_config(DEFAULT_CONFIG)
    logger = setup_logger(config)
    
    dry_run = "--dry-run" in sys.argv
    
    try:
        servo = ServoController(config['servo'], dry_run=dry_run)
    except Exception as e:
        print(f"初始化舵机失败: {e}")
        sys.exit(1)
        
    try:
        servo.center()
        while True:
            print("\n" + "="*35)
            print("=== 🎯 舵机性能与压力测试工具 ===")
            print("  1. 基础转动测试 (单次测试连通性与方向)")
            print("  2. 连续压力测试 (验证带载能力，按Ctrl+C随时暂停)")
            print("  3. 自由输入角度 (测试死角与软件限位)")
            print("  q. 安全退出并关闭 PWM")
            print("="*35)
            
            cmd = input("请选择模式 (1/2/3/q): ").strip().lower()
            
            if cmd == 'q':
                break
            elif cmd == '1':
                basic_test(servo)
            elif cmd == '2':
                stress_test(servo)
            elif cmd == '3':
                val_str = input("请输入目标角度 (例如 0, 30, -45): ")
                try:
                    val = float(val_str)
                    servo.set_angle(val)
                except ValueError:
                    print("输入无效！")
            else:
                print("未知指令，请重新输入。")
    except KeyboardInterrupt:
        print("\n用户强制退出。")
    finally:
        servo.disable()

if __name__ == "__main__":
    main()
