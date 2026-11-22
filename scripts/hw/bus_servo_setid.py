#!/usr/bin/env python3
"""
微雪总线舵机（ST/SCS 系列）ID 修改与 EEPROM 信息读取工具

背景：新舵机出厂 ID 通常相同（常见为 1 或 0）。若两个舵机 ID 相同，
      同一条总线上会同时抢答，造成数据冲撞 —— 表现为：
        · 只发一个 ID 命令，两个舵机都动
        · 位置回读到 41471 / 31231 这类不可能的数值
        · 应答时有时无，运动幅度很小甚至乱走

正确做法：一次只接一个舵机，逐个把 ID 改成 1、2，再一起接上。

用法：
    # 只读信息（安全，不改任何东西）
    python scripts/hw/bus_servo_setid.py --port /dev/ttyACM0 --id 0 --info

    # 把当前唯一连接的那个舵机 ID 改成 1
    python scripts/hw/bus_servo_setid.py --port /dev/ttyACM0 --id 0 --set-id 1

    # 扫描总线上有几个舵机在应答
    python scripts/hw/bus_servo_setid.py --port /dev/ttyACM0 --scan
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("[-] 未安装 pyserial，请先执行: pip install pyserial --break-system-packages")
    sys.exit(1)


# ── 协议常量（ST/SMS 系列）────────────────────────────────────────────────
BROADCAST_ID = 0xFE
INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03

REG_MODEL_L = 0x03        # 型号低字节（STS: 777 = ST3215）
REG_VERSION_L = 0x04      # 固件版本
REG_ID = 0x05             # 舵机 ID（EEPROM）
REG_BAUD_RATE = 0x06      # 波特率档位（EEPROM）
REG_MIN_ANGLE_L = 0x09    # 最小角度限位（EEPROM）
REG_MAX_ANGLE_L = 0x0B    # 最大角度限位（EEPROM）
REG_MAX_TORQUE_L = 0x10   # 最大扭矩
REG_TORQUE_ENABLE = 0x28  # 扭矩使能
REG_GOAL_POSITION = 0x2A  # 目标位置
REG_PRESENT_POSITION = 0x38
REG_PRESENT_VOLTAGE = 0x3E
REG_PRESENT_TEMP = 0x3F
REG_LOCK = 0x37           # EEPROM 写保护锁（0=解锁可写, 1=上锁）

BAUD_TABLE = {
    0: 1000000, 1: 500000, 2: 250000, 3: 128000,
    4: 115200, 5: 76800, 6: 57600, 7: 38400,
}


def checksum(body):
    return (~(sum(body) & 0xFF)) & 0xFF


def build_packet(servo_id, instruction, params=None):
    params = list(params or [])
    body = [servo_id, len(params) + 2, instruction] + params
    return bytes([0xFF, 0xFF] + body + [checksum(body)])


def split_frames(buf):
    """宽松切帧：不做校验和过滤，便于观察冲突/噪声"""
    out = []
    i = 0
    while i + 4 <= len(buf):
        if buf[i] == 0xFF and buf[i + 1] == 0xFF:
            length = buf[i + 3]
            total = 4 + length
            if 2 <= length <= 40 and i + total <= len(buf):
                out.append(buf[i:i + total])
                i += total
                continue
        i += 1
    return out


def valid_frames(buf):
    return [f for f in split_frames(buf) if len(f) >= 6 and (sum(f[2:]) & 0xFF) == 0xFF]


class BusServo:
    """半双工总线舵机通信封装（注意：RTS 必须拉高，否则应答大量丢失）"""

    def __init__(self, port, baud=115200, rts=True):
        self.ser = serial.Serial(port, baud, timeout=0.03)
        self.ser.rts = rts
        self.ser.dtr = False
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.3)

    def tx(self, servo_id, instruction, params=None, repeats=1, wait=0.08):
        frames = []
        for _ in range(repeats):
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.ser.write(build_packet(servo_id, instruction, params))
            self.ser.flush()
            t0 = time.time()
            buf = b""
            while time.time() - t0 < wait:
                pending = self.ser.in_waiting
                if pending:
                    buf += self.ser.read(pending)
                time.sleep(0.002)
            frames += valid_frames(buf)
        return frames

    def ping(self, servo_id, repeats=10):
        return len(self.tx(servo_id, INST_PING, repeats=repeats, wait=0.06))

    def read(self, servo_id, addr, n, repeats=8):
        vals = []
        for f in self.tx(servo_id, INST_READ, [addr, n], repeats=repeats, wait=0.06):
            if len(f) >= 6 + n:
                vals.append(int.from_bytes(bytes(f[5:5 + n]), "little"))
        if not vals:
            return None
        # 取众数（同值出现最多的那个），比中位数更能抵御冲突脏数据
        return max(set(vals), key=vals.count)

    def write(self, servo_id, params, repeats=8):
        return len(self.tx(servo_id, INST_WRITE, params, repeats=repeats, wait=0.06))

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def show_info(bus, servo_id):
    print(f"\n=== 舵机 ID={servo_id} 信息 ===")
    model = bus.read(servo_id, REG_MODEL_L, 2)
    version = bus.read(servo_id, REG_VERSION_L, 2)
    id_reg = bus.read(servo_id, REG_ID, 1)
    baud_reg = bus.read(servo_id, REG_BAUD_RATE, 1)
    amin = bus.read(servo_id, REG_MIN_ANGLE_L, 2)
    amax = bus.read(servo_id, REG_MAX_ANGLE_L, 2)
    torque = bus.read(servo_id, REG_TORQUE_ENABLE, 1)
    pos = bus.read(servo_id, REG_PRESENT_POSITION, 2)
    volt = bus.read(servo_id, REG_PRESENT_VOLTAGE, 1)
    temp = bus.read(servo_id, REG_PRESENT_TEMP, 1)

    print(f"  型号 MODEL      = {model}   (777 = ST3215 / ST 系列)")
    print(f"  固件版本 VERSION = {version}")
    print(f"  ID 寄存器        = {id_reg}")
    if baud_reg is not None:
        print(f"  波特率档位       = {baud_reg}  -> {BAUD_TABLE.get(baud_reg, '未知')} bps")
    print(f"  最小角度限位     = {amin}   (0 = 全行程)")
    print(f"  最大角度限位     = {amax}   (4095 = 全行程)")
    print(f"  扭矩使能         = {torque}")
    print(f"  当前位置         = {pos}")
    if volt is not None:
        print(f"  当前电压         = {volt / 10.0:.1f} V")
    if temp is not None:
        print(f"  当前温度         = {temp} °C")

    if amin is not None and amax is not None and (amax - amin) < 3000:
        span_deg = (amax - amin) * 360.0 / 4096.0
        print(f"\n  ⚠ 注意：角度限位只有 {amin}~{amax}（约 {span_deg:.0f}°），")
        print(f"     这会让舵机运动幅度明显偏小！可用 --unlock-limits 解除限位。")
    return {"min": amin, "max": amax}


def set_id(bus, old_id, new_id):
    print(f"\n=== 把 ID {old_id} 改成 {new_id} ===")
    print(f"  [1/4] 解锁 EEPROM ... 应答 {bus.write(old_id, [REG_LOCK, 0], repeats=8)} 帧")
    time.sleep(0.1)
    print(f"  [2/4] 写入新 ID={new_id} ... 应答 {bus.write(old_id, [REG_ID, new_id], repeats=8)} 帧")
    time.sleep(0.3)
    print(f"  [3/4] 重新上锁 EEPROM ... 应答 {bus.write(new_id, [REG_LOCK, 1], repeats=8)} 帧")
    time.sleep(0.3)
    print(f"  [4/4] 验证：Ping 新 ID {new_id} -> {bus.ping(new_id, repeats=12)}/12")
    print(f"        Ping 旧 ID {old_id} -> {bus.ping(old_id, repeats=8)}/8（应为 0）")


def unlock_angle_limits(bus, servo_id):
    print(f"\n=== 解除 ID {servo_id} 的角度限位（恢复全行程 0~4095）===")
    print(f"  [1/3] 解锁 EEPROM ... 应答 {bus.write(servo_id, [REG_LOCK, 0], repeats=8)} 帧")
    time.sleep(0.1)
    print(f"  [2/3] 写入最小限位 0 / 最大限位 4095 ... "
          f"应答 {bus.write(servo_id, [REG_MIN_ANGLE_L, 0x00, 0x00, 0xFF, 0x0F], repeats=8)} 帧")
    time.sleep(0.3)
    print(f"  [3/3] 上锁 ... 应答 {bus.write(servo_id, [REG_LOCK, 1], repeats=8)} 帧")


def scan(bus, limit=20):
    print("\n=== 扫描应答的舵机 ID ===")
    found = []
    for sid in range(0, limit + 1):
        hits = bus.ping(sid, repeats=10)
        if hits:
            found.append(sid)
            print(f"  ✅ ID {sid:2d}: {hits}/10")
    if not found:
        print("  未发现任何舵机")
    elif len(found) > 1:
        print(f"\n  ⚠ 发现 {len(found)} 个 ID 在应答: {found}")
        print("     若您明确只接了一个舵机，说明另有设备占用了这些 ID。")
    return found


def main():
    ap = argparse.ArgumentParser(description="微雪总线舵机 ID 修改与信息读取")
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--id", type=int, default=0, help="当前舵机 ID")
    ap.add_argument("--info", action="store_true", help="只读信息")
    ap.add_argument("--scan", action="store_true", help="扫描所有应答 ID")
    ap.add_argument("--set-id", type=int, default=None, help="改成新的 ID")
    ap.add_argument("--unlock-limits", action="store_true", help="解除角度限位")
    args = ap.parse_args()

    try:
        bus = BusServo(args.port, args.baud)
    except Exception as exc:
        print(f"[-] 打开串口失败: {exc}")
        return 1

    try:
        if args.scan:
            scan(bus)
        if args.info:
            show_info(bus, args.id)
        if args.unlock_limits:
            unlock_angle_limits(bus, args.id)
        if args.set_id is not None:
            set_id(bus, args.id, args.set_id)
        if not (args.scan or args.info or args.unlock_limits or args.set_id is not None):
            show_info(bus, args.id)
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
