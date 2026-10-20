# 视听融合声源定位与目标跟踪云台

基于 Raspberry Pi 的单轴水平云台：声学负责在拍手或突发声后判断“往哪看一次”，视觉负责转向后“盯着目标左右跟”。当前基础主线是 **1-DOF 水平舵机 + 双通道音频 + 相机人脸检测 + 三态状态机**。

本 README 是项目入口。完整验收标准见[开发计划](视听融合声源定位与目标跟踪云台-开发计划.md)，需要现场接线或观察的事项见[人工待办与硬件验证](人工待办与硬件验证.md)，所有历史变更和证据见[项目日志](项目日志.md)，采购建议见[购买清单](购买清单.md)。

## 当前状态

截至 **2026-10-20**：

| 范围 | 状态 |
| --- | --- |
| M0 配置、日志和命令入口 | 已实现；依赖环境需按设备安装 |
| M1 健康检查 | 已实现；树莓派健康检查有历史通过记录，整机联调前需复查 |
| M2 舵机驱动 | 已实现；GPIO 18 + `pigpio`，SG90 轻负载压力测试通过，物理方向仍需确认 |
| M3 音频 | 已实现 SED、GCC-PHAT、亚采样插值和能量差降级；双麦实机验证待完成 |
| M4 视觉 | 已实现 OpenCV 取流、MediaPipe / Haar 检测和最新观测缓存；相机实机验证待完成 |
| M5 控制集成 | FSM、死区跟随和模拟验收已实现；端到端实机待完成 |
| M6 标定与交付 | 脚本和文档已建立；标定、证据归档、最终交付待完成 |
| M7 语音播报与 HUD | 目前是设计和配置占位，`src/speaker.py`、`src/display.py` 尚未实现 |

当前最短路径是：确认舵机方向 → 接入双麦和相机 → 完成音频/视觉单模块验证 → 完成基础闭环实机演示。M7 和双轴等拓展不得提前替代基础闭环。

## 架构速览

```text
双麦克风 -> sounddevice 回调 -> 有界 PCM 队列 -> SED -> GCC-PHAT / 能量差
                                                        |
相机 -> CameraCapture 最新帧缓存 -> FaceDetector -> 最新 VisionObservation
                                                        |
                         主控循环 (约 30 Hz)
                 IDLE -> TURN_ONCE -> FOLLOW -> IDLE
                                                        |
                       死区步进控制器
                                                        |
                 ServoController -> GPIO 18 / pigpio PWM
```

系统只在 `IDLE` 接受新的 `AudioEvent`。`TURN_ONCE` 按声学角度转向并屏蔽回声；`FOLLOW` 只使用新鲜的人脸观测，根据 `dx` 做小步进；连续丢脸超时后回中并回到 `IDLE`。

当前代码模块：

- `src/app.py`：主控循环、三态 FSM、`--dry-run` / `--simulate`、`c` 回中和 `q` 退出。
- `src/audio.py`：双通道采集、RMS 能量 SED、GCC-PHAT、低置信度能量差降级。
- `src/vision.py`：OpenCV 相机取流、最新帧缓存、MediaPipe / Haar 人脸检测、`dx` 输出。
- `src/controller.py`：死区步进控制，过期或无脸观测不产生动作。
- `src/servo.py`：GPIO 18 `pigpio` PWM、角度限位、方向符号、回中和安全释放。
- `src/config.py`：YAML 配置加载与日志初始化。

## 硬件接线与安全

```text
[官方 5V/3A Type-C] ------> Raspberry Pi 4B
                              GPIO 18 (PWM) ----> 舵机信号线
[独立 5–6V / ≥3A 电源] ---> 舵机正极
          |                    |
          +------ 共地 ------> Raspberry Pi GND + 舵机负极
```

- 舵机正极不能接树莓派 5V；舵机必须使用独立 5–6 V、额定电流不低于 3 A 的电源。
- 树莓派使用独立稳定的 5 V / 3 A Type-C 电源，不使用电脑 USB 口给主板供电。
- 舵机动力输入端并联 1000–2200 µF 电解电容，确认极性；树莓派和舵机必须共地。
- 上电先开舵机电源，再开树莓派；关机顺序相反。
- 当前主线直接使用 GPIO 18 + `pigpio`。PCA9685 不在现有代码主线中，不能按它的接线替代当前 GPIO 方案。
- 连续人脸检测时应使用散热片和风扇；温度、欠压和 `pigpiod` 状态先通过健康检查确认。

## 软件环境

最后一次树莓派实测记录（2026-09-22）为 Pi 4B Rev 1.5、Debian 13、Python 3.13.5。代码运行需要按设备安装 `PyYAML`、`numpy`、`sounddevice`、`soundfile`、`opencv`，以及硬件侧的 `pigpio` / `pigpiod`；MediaPipe 不可用时视觉模块可降级为 Haar。

本地无硬件时，先安装 Python 依赖再执行模拟测试。`data/` 中的 WAV、图片等原始大文件默认不进 Git。

## 快速启动

从项目根目录执行：

```bash
# 检查配置和硬件状态
python scripts/healthcheck.py

# 确认 pigpio 守护进程（树莓派硬件运行必需）
sudo systemctl enable --now pigpiod

# 无硬件软件自检
python -m src.app --config configs/default.yaml --dry-run
python scripts/test_follow_logic.py
python scripts/test_fsm.py

# 真机运行前先确认双麦、相机、舵机已接好
python -m src.app --config configs/default.yaml
```

主程序交互：输入 `c` 回中并复位为 `IDLE`，输入 `q` 安全退出；按 `Ctrl-C` 也会执行资源释放流程。主程序检测不到音频或相机时会安全退出，不会驱动未知目标角。

## 单模块验证命令

| 目标 | 命令 | 证据 / 注意 |
| --- | --- | --- |
| 舵机基础、压力和限位 | `python scripts/servo_sweep.py` | 菜单选择 `1`、`2` 或 `3`；`Ctrl-C` 回中，`q` 退出 |
| 双通道录音 | `python scripts/record_audio.py --list`；`python scripts/record_audio.py -d 5` | 检查 WAV 是否为 16 kHz / 16-bit / 2 ch |
| 相机取流 | `python scripts/camera_preview.py --seconds 10` | 保存 `data/test_frame.jpg` 并输出实测 FPS；当前脚本为无头取流测试，不绘制 HUD |
| SED 防抖 | `python scripts/test_sed.py` | 记录阈值、误触发和单次事件次数 |
| GCC-PHAT | `python scripts/evaluate_audio.py` | 记录角度、侧别、置信度和降级模式 |
| 人脸检测 | `python scripts/test_face.py --seconds 20` | 检查左负右正、FPS 和无脸行为 |
| 死区控制 | `python scripts/test_follow_logic.py` | 无硬件模拟，验证方向、死区和观测超时 |
| 状态机 | `python scripts/test_fsm.py` | 无硬件模拟，验证状态时序和资源释放 |

`test_fsm.py` 依赖 `PyYAML` 等 Python 包；若本地缺少依赖，先安装依赖后再把结果写入日志，不要把“命令未运行”标成 PASS。

## 配置约定

所有硬件引脚、采样参数、阈值、限位、步长和超时集中在 `configs/default.yaml`。方向约定如下：

- 声源 / 人脸在左侧统一为负值；右侧为正值。
- 人脸观测使用 `dx = face_center_x - camera_cx`，左侧 `dx < 0`，右侧 `dx > 0`。
- 机械方向相反时只修改 `servo_sign`，不改算法源码。
- `audio_zero_deg` 只在音频模块中加到 `AudioEvent`，不要在主控再次叠加。
- `speaker` 和 `display` 配置目前是 M7 预留项；没有对应源码时不会产生播报或 HUD。

## 项目文档关系

1. 开始工作前阅读 `项目日志.md`，了解最近一次证据和已知阻塞。
2. 按开发计划的当前执行顺序推进，不以原周数或“代码存在”代替硬件验收。
3. 需要接线、观察、测量或录制证据的事项写入 `人工待办与硬件验证.md`。
4. 完成一次实现或验证后，在项目日志末尾追加日期、改动、测试结果、限制和下一步。

已完成的历史记录保留在日志中；“代码已实现”“模拟通过”“硬件通过”“设计待实现”四种状态必须分开记录。
