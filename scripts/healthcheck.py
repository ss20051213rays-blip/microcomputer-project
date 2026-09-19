import subprocess

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return result.stdout.strip()
    except Exception as e:
        return str(e)

def main():
    print("=== 系统健康与硬件环境检查 (M1) ===")
    
    # 1. CPU 温度
    temp = run_cmd("vcgencmd measure_temp")
    if "VCHI initialization failed" in temp or "not found" in temp:
        print("[!] 无法获取 CPU 温度 (说明：非树莓派环境或未加入 video 用户组)")
    else:
        print(f"[*] CPU 温度: {temp}")
        
    # 2. 欠压检查
    throttled = run_cmd("vcgencmd get_throttled")
    if "throttled=0x0" in throttled:
        print("[*] 供电状态: 正常 (未欠压/未降频)")
    else:
        print(f"[!] 供电异常告警: {throttled} (警告：请检查电源是否达标！)")
        
    # 3. pigpiod 状态
    pigpiod_status = run_cmd("pgrep pigpiod")
    if pigpiod_status:
        print(f"[*] pigpiod 服务: 运行中 (PID: {pigpiod_status.replace(chr(10), ' ')})")
    else:
        print("[!] pigpiod 服务: 未运行 (请执行 'sudo pigpiod' 启动，舵机需要它！)")
        
    # 4. 音频设备
    print("\n[音频设备检查]")
    print(run_cmd("aplay -l | grep '^card' || echo '未检测到 ALSA 播放设备'"))
    print(run_cmd("arecord -l | grep '^card' || echo '未检测到 ALSA 录音设备'"))
    
    # 5. 视频设备
    print("\n[视频设备检查]")
    print(run_cmd("ls /dev/video* 2>/dev/null || echo '未检测到 /dev/video* 设备'"))

    print("\n=== 检查完毕 ===")

if __name__ == "__main__":
    main()

