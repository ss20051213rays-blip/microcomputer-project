import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.vision import VisionObservation
from src.controller import DeadzoneStepController
import time

def main():
    print("=== 死区步进控制器模拟测试 ===")
    
    config_control = {"observation_timeout_s": 0.5}
    config_servo = {"deadzone_px": 30, "step_deg": 2.0}
    
    controller = DeadzoneStepController(config_control, config_servo)
    
    now = time.monotonic()
    
    # 模拟场景列表
    test_cases = [
        ("场景1: 偏差 -50 px (明显偏左)", -50.0, 0.0),
        ("场景2: 偏差 +45 px (明显偏右)", 45.0, 0.0),
        ("场景3: 偏差 -10 px (死区内偏左)", -10.0, 0.0),
        ("场景4: 偏差 +20 px (死区内偏右)", 20.0, 0.0),
        ("场景5: 观测已过期 1 秒 (防抖)", -60.0, 1.0),
        ("场景6: 未检测到人脸", None, 0.0)
    ]
    
    for name, dx, age in test_cases:
        if dx is None:
            obs = VisionObservation(now - age, False, 0.0, (0,0,0,0), 0.0, 15.0)
        else:
            obs = VisionObservation(now - age, True, dx, (10,10,50,50), 0.9, 15.0)
            
        step = controller.compute_step(obs)
        print(f"{name:30s} => 输出步进角: {step:>5.1f}°")

if __name__ == "__main__":
    main()
