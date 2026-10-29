#!/usr/bin/env python3
"""
微雪通用型串行总线舵机驱动板与二维云台专用测试脚本
支持：
- 扫描总线上的舵机 ID (Ping)
- 双轴 (Yaw / Pitch) 单独或联动角度设置与回中
- 自动扫掠压力测试
- 释放扭矩
- 支持 --dry-run 脱机模拟模式
"""

import os
import sys
import time
import argparse

from pantilt.core.config import load_config, setup_logger
from pantilt.core.paths import DEFAULT_CONFIG
from pantilt.actuation.servo import ServoController

def main():
    parser = argparse.ArgumentParser(description="微雪串行总线舵机与二维云台调试工具")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="脱机模拟模式")
    parser.add_argument("--yaw", type=float, help="设置水平偏航角度 (-90 ~ 90)")
    parser.add_argument("--pitch", type=float, help="设置垂直俯仰角度 (-30 ~ 45)")
    parser.add_argument("--center", action="store_true", help="两轴归中 (0, 0)")
    parser.add_argument("--sweep", action="store_true", help="执行双轴扫掠测试")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logger(config)

    cfg_servo = config.get("servo", {})
    cfg_servo["driver_type"] = "bus"  # 强制使用 bus 模式测试

    logger.info("=== 微雪总线舵机二维云台测试工具 ===")
    logger.info(f"串口: {cfg_servo.get('serial_port')} | 波特率: {cfg_servo.get('baudrate')} | Yaw ID={cfg_servo.get('yaw_id')}, Pitch ID={cfg_servo.get('pitch_id')}")

    controller = ServoController(cfg_servo, dry_run=args.dry_run)

    if args.center:
        logger.info("执行两轴归中...")
        controller.center()
        time.sleep(1.0)
        controller.disable()
        return

    if args.yaw is not None or args.pitch is not None:
        logger.info(f"指定位置设置: Yaw={args.yaw}°, Pitch={args.pitch}°")
        controller.set_angles(yaw=args.yaw, pitch=args.pitch)
        time.sleep(1.0)
        controller.disable()
        return

    if args.sweep:
        logger.info("开始双轴自动扫掠测试 (5 轮)...")
        try:
            for cycle in range(1, 6):
                logger.info(f"--- 第 {cycle}/5 轮扫掠 ---")
                # 归中
                controller.set_angles(0.0, 0.0)
                time.sleep(0.5)
                # 水平左，俯仰平
                controller.set_angles(-30.0, 0.0)
                time.sleep(0.5)
                # 水平右，俯仰平
                controller.set_angles(30.0, 0.0)
                time.sleep(0.5)
                # 抬头
                controller.set_angles(0.0, 20.0)
                time.sleep(0.5)
                # 低头
                controller.set_angles(0.0, -15.0)
                time.sleep(0.5)
            controller.center()
            time.sleep(0.5)
            logger.info("扫掠测试完成，云台已归中。")
        finally:
            controller.disable()
        return

    # 交互式菜单模式
    print("\n交互式操作菜单:")
    print("  1: 两轴归中 (0°, 0°)")
    print("  2: 水平扫掠 (-30° -> 0° -> +30° -> 0°)")
    print("  3: 垂直扫掠 (-15° -> 0° -> +20° -> 0°)")
    print("  4: 手动输入 Yaw & Pitch 角度")
    print("  q: 释放扭矩并退出")

    try:
        while True:
            choice = input("\n请选择操作 [1-4, q]: ").strip()
            if choice == "1":
                controller.center()
            elif choice == "2":
                print("执行水平偏航扫掠...")
                controller.set_angles(-30.0, 0.0)
                time.sleep(0.8)
                controller.set_angles(30.0, 0.0)
                time.sleep(0.8)
                controller.set_angles(0.0, 0.0)
            elif choice == "3":
                print("执行垂直俯仰扫掠...")
                controller.set_angles(0.0, -15.0)
                time.sleep(0.8)
                controller.set_angles(0.0, 20.0)
                time.sleep(0.8)
                controller.set_angles(0.0, 0.0)
            elif choice == "4":
                try:
                    y_str = input("请输入 Yaw 角度 (-90 ~ 90): ").strip()
                    p_str = input("请输入 Pitch 角度 (-30 ~ 45): ").strip()
                    y = float(y_str) if y_str else None
                    p = float(p_str) if p_str else None
                    controller.set_angles(y, p)
                except ValueError:
                    print("输入数值格式错误！")
            elif choice.lower() == "q":
                break
            else:
                print("无效选项，请重新选择。")
    finally:
        controller.disable()
        logger.info("总线舵机测试结束，已安全释放。")

if __name__ == "__main__":
    main()

