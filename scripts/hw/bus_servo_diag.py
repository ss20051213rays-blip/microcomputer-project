#!/usr/bin/env python3
"""
微雪 Bus Servo Adapter 总线舵机物理层诊断工具

用途：当 `bus_servo_probe.py` 完全无响应时，逐层排除故障：
  1. 串口打开与参数确认（CH343 USB-CDC 是否真的通）
  2. 回显 / 回环测试（判断 TX 是否真的发到了总线上）
  3. 空闲监听（是否有周期心跳广播）
  4. 全波特率扫描 × 全舵机 ID 扫描（自动识别舵机真实波特率与 ID）
  5. 结论与排查建议自动输出

用法：
    python scripts/hw/bus_servo_diag.py                 # 完整诊断（推荐）
    python scripts/hw/bus_servo_diag.py --port /dev/ttyACM0
    python scripts/hw/bus_servo_diag.py --quick         # 只测常用波特率与 ID 1~4

协议：ST/SC 系列串行总线舵机（半双工 UART）
    指令帧: FF FF ID LEN INST PARAM... CHK   (LEN = len(PARAM) + 2)
    应答帧: FF FF ID LEN ERR  PARAM... CHK
    校验:   ID 到 CHK 所有字节之和的低 8 位 == 0xFF
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("[-] 未安装 pyserial，请先执行: pip install pyserial --break-system-packages")
    sys.exit(1)


# ── 协议常量 ────────────────────────────────────────────────────────────────
BROADCAST_ID = 0xFE
INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03

REG_TORQUE_ENABLE = 0x28
REG_GOAL_POSITION = 0x2A
REG_PRESENT_VOLTAGE = 0x3E   # 只读：当前电压（0.1V 单位）

COMMON_BAUDS = [1000000, 500000, 250000, 128000, 115200, 76800, 57600, 38400, 19200, 9600]
QUICK_BAUDS = [1000000, 115200]


# ── 协议帧构造与解析 ────────────────────────────────────────────────────────
def checksum(body):
    """body = [ID, LEN, INST, PARAM...]，返回校验字节"""
    return (~(sum(body) & 0xFF)) & 0xFF


def build_packet(servo_id, instruction, params=None):
    params = params or []
    body = [servo_id, len(params) + 2, instruction] + list(params)
    return bytes([0xFF, 0xFF] + body + [checksum(body)])


def parse_frames(buf):
    """从原始字节流中切出所有完整协议帧，返回 [(servo_id, err, params, raw_hex)]"""
    frames = []
    i = 0
    while i + 4 < len(buf):
        if buf[i] == 0xFF and buf[i + 1] == 0xFF:
            length = buf[i + 3]
            total = 4 + length
            if 2 <= length <= 64 and i + total <= len(buf):
                frame = buf[i:i + total]
                # 校验和必须自洽，否则视为噪声
                if (sum(frame[2:]) & 0xFF) == 0xFF:
                    frames.append({
                        "id": frame[2],
                        "err": frame[4] if length > 2 else None,
                        "params": frame[5:-1],
                        "raw": frame.hex(),
                    })
                    i += total
                    continue
        i += 1
    return frames


def drain(ser, duration):
    """在指定时长内收集所有可读字节"""
    t0 = time.time()
    buf = b""
    while time.time() - t0 < duration:
        waiting = ser.in_waiting
        if waiting:
            buf += ser.read(waiting)
        time.sleep(0.002)
    return buf


# ── 单项测试 ────────────────────────────────────────────────────────────────
def test_port_params(ser):
    print("\n[1] 串口参数确认")
    print(f"    端口      : {ser.port}")
    print(f"    已打开    : {ser.is_open}")
    print(f"    数据格式  : {ser.bytesize}{ser.parity}{ser.stopbits}")
    print(f"    流控      : rtscts={ser.rtscts} dsrdtr={ser.dsrdtr} xonxoff={ser.xonxoff}")
    print(f"    调制解调线: CTS={ser.cts} DSR={ser.dsr} CD={ser.cd} RI={ser.ri}")
    print(f"    USB 描述  : CH343/CH340 USB-CDC（逻辑侧供电正常）")


def test_echo(ser):
    """回环测试：部分适配器会把发送内容回显到接收端"""
    print("\n[2] 回显 / 回环测试（判断 TX 是否真的下发到总线）")
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)
    probe = b"\x55\x55\x55\x55\x55"
    ser.write(probe)
    ser.flush()
    got = drain(ser, 0.15)
    if got:
        print(f"    发送 {probe.hex()} -> 收到 {got.hex()}  (存在回显通路)")
    else:
        print(f"    发送 {probe.hex()} -> 收到 空  (无回显，属正常：半双工总线无设备时本就静默)")
    return bool(got)


def test_idle(ser, seconds=1.0):
    print(f"\n[3] 空闲监听 {seconds:.1f}s（检查是否有周期心跳/广播）")
    ser.reset_input_buffer()
    got = drain(ser, seconds)
    if got:
        print(f"    收到 {len(got)} 字节: {got[:64].hex()}")
    else:
        print(f"    完全静默 —— 总线上没有任何设备主动发数据")
    return got


def scan_ids(ser, id_range, wait=0.04):
    """逐 ID 发送 Ping，返回 {id: frame_dict}"""
    hits = {}
    for sid in id_range:
        ser.reset_input_buffer()
        ser.write(build_packet(sid, INST_PING))
        ser.flush()
        raw = drain(ser, wait)
        for fr in parse_frames(raw):
            if fr["id"] == sid:
                hits[sid] = fr
    return hits


def test_broadcast(ser):
    ser.reset_input_buffer()
    ser.write(build_packet(BROADCAST_ID, INST_PING))
    ser.flush()
    raw = drain(ser, 0.25)
    return raw, parse_frames(raw)


def probe_baud(port, baud, id_range):
    """在给定波特率下做一次完整探测，返回 (是否有应答, 命中表, 原始噪声)"""
    try:
        ser = serial.Serial(port, baud, timeout=0.02, write_timeout=0.3)
    except Exception as exc:
        return None, {}, f"打开失败: {exc}"

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.05)

        raw_bc, frames_bc = test_broadcast(ser)
        hits = scan_ids(ser, id_range)

        # 广播应答若带未知 ID，也并入结果
        for fr in frames_bc:
            if fr["id"] != BROADCAST_ID:
                hits.setdefault(fr["id"], fr)

        return raw_bc, hits, None
    finally:
        ser.close()


def read_voltage(ser, servo_id):
    """读取舵机当前电压（寄存器 0x3E，单位 0.1V）"""
    ser.reset_input_buffer()
    ser.write(build_packet(servo_id, INST_READ, [REG_PRESENT_VOLTAGE, 1]))
    ser.flush()
    raw = drain(ser, 0.06)
    for fr in parse_frames(raw):
        if fr["id"] == servo_id and fr["params"]:
            return fr["params"][0] / 10.0
    return None


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="微雪总线舵机驱动板物理层诊断")
    parser.add_argument("--port", default="/dev/ttyACM0", help="串口设备，默认 /dev/ttyACM0")
    parser.add_argument("--quick", action="store_true", help="快速模式：只测 1Mbps/115200 与 ID 1~4")
    parser.add_argument("--ids", default=None, help="指定扫描 ID 范围，如 1-20")
    args = parser.parse_args()

    bauds = QUICK_BAUDS if args.quick else COMMON_BAUDS
    if args.ids:
        lo, hi = args.ids.split("-")
        id_range = range(int(lo), int(hi) + 1)
    else:
        id_range = range(1, 5) if args.quick else range(1, 21)

    print("=" * 68)
    print("微雪 Bus Servo Adapter 总线舵机物理层诊断")
    print(f"端口: {args.port} | 待测波特率: {bauds} | 待测 ID: {id_range.start}~{id_range.stop - 1}")
    print("=" * 68)

    # 打开一次做静态检查
    try:
        ser = serial.Serial(args.port, bauds[0], timeout=0.02)
    except Exception as exc:
        print(f"\n[-] 无法打开串口 {args.port}: {exc}")
        print("    请确认驱动板 USB 线已插、线是数据线（非纯充电线）")
        return 1

    test_port_params(ser)
    test_echo(ser)
    test_idle(ser, 0.8)
    ser.close()

    # 全波特率扫描
    print("\n[4] 波特率 × 舵机 ID 全量扫描")
    print(f"    {'波特率':>9} | 结果")
    print("    " + "-" * 56)
    found = {}
    noisy = []
    for baud in bauds:
        raw_bc, hits, err = probe_baud(args.port, baud, id_range)
        if err:
            print(f"    {baud:>9} | {err}")
            continue
        if hits:
            ids = ", ".join(f"ID{k}" for k in sorted(hits))
            print(f"    {baud:>9} | ✅ 应答: {ids}")
            for sid, fr in hits.items():
                print(f"              ID {sid}: {fr['raw']}  (ERR={fr['err']})")
            found[baud] = hits
        elif raw_bc:
            print(f"    {baud:>9} | ⚠ 有噪声但无有效帧: {raw_bc[:24].hex()}")
            noisy.append((baud, raw_bc))
        else:
            print(f"    {baud:>9} | 静默（无任何字节）")

    # 命中的波特率下额外读电压，确认供电
    if found:
        print("\n[5] 供电电压回读（确认舵机 VIN 是否达标 9~12.6V）")
        best_baud = next(iter(found))
        ser = serial.Serial(args.port, best_baud, timeout=0.02)
        try:
            for sid in sorted(found[best_baud]):
                voltage = read_voltage(ser, sid)
                if voltage is None:
                    print(f"    ID {sid}: 电压回读失败")
                else:
                    status = "✅ 正常" if 9.0 <= voltage <= 12.6 else "⚠ 超出额定范围"
                    print(f"    ID {sid}: {voltage:.1f} V  {status}")
        finally:
            ser.close()

    # 结论
    print("\n" + "=" * 68)
    print("诊断结论")
    print("=" * 68)
    if found:
        baud = next(iter(found))
        ids = sorted(found[baud])
        print(f"✅ 总线通信正常！波特率 = {baud} bps，舵机 ID = {ids}")
        print(f"   -> 请把 configs/default.yaml 的 servo.baudrate 改为 {baud}")
    else:
        print("❌ 总线完全无应答（所有波特率、所有 ID 均静默）")
        print("\n按以下顺序逐项排查（从最可能到最不可能）：")
        print("  1) 【最可能】舵机动力电未接通：驱动板绿色端子 DC+/DC- 需独立接入 9~12.6V。")
        print("     USB 线只给板载 CH343 芯片供电，不驱动舵机总线，舵机无电则完全不发声。")
        print("     -> 用万用表量 DC+ 与 DC- 之间电压，必须在 9~12.6V。")
        print("  2) 舵机线插反 / 只插了一根：三芯线（VCC / GND / 信号）方向必须与板丝印一致，")
        print("     且舵机与驱动板之间必须是『串行总线』接法（IN -> OUT 级联），不是 PWM 三线。")
        print("  3) 舵机内部蓝灯是否亮：亮 = 舵机已上电；不亮 = 没供电或已损坏。")
        print("  4) 适配器是否工作在 UART 模式：部分板有 TTL/UART 切换跳线，需置于 UART。")
        print("  5) 舵机可能已被此前 >15V 过压损伤（出现过发热）。")

    if noisy:
        print("\n噪声记录（有助于判断波特率是否接近但不对）：")
        for baud, raw in noisy:
            print(f"    {baud} bps: {raw[:32].hex()}")

    print()
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
