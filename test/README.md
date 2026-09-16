# 离线 Mock 小项目：视听融合云台流程验证

这个目录是一个 **不依赖树莓派真机** 的测试小项目，用来先把主流程跑通：

`监听 → 拍手定位 → 开环转向 → 人脸跟随 → 丢失回中`

适合在 Mac 上做：

- 代码 / 架构 / 文档
- 业务逻辑与算法
- 单元测试
- GPIO / 摄像头 / 麦克风的接口 + mock
- 项目骨架、模块划分、部署脚本准备

## 目录结构

```text
test/
├── README.md
├── requirements.txt
├── configs/default.yaml
├── src/
│   ├── app.py          # 状态机主循环
│   ├── audio.py        # 拍手检测 + GCC-PHAT（含 mock）
│   ├── vision.py       # 人脸 dx 计算（含 mock）
│   ├── servo.py        # 舵机软件限位（mock）
│   ├── interfaces.py   # 硬件抽象接口
│   └── config.py
├── scripts/
│   ├── run_mock_demo.py
│   └── deploy_to_pi.sh
├── tests/
│   └── test_offline_pipeline.py
├── notes/
└── data/
```

## 快速开始（完全离线）

```bash
cd "微机原理与微系统/project/test"
python3 scripts/run_mock_demo.py
python3 -m unittest discover -s tests -v
```

> 当前离线版只用 Python 标准库，无需联网安装依赖。

## 离线能验证什么

| 能力 | 离线是否可测 | 说明 |
| --- | --- | --- |
| 配置加载 | 能 | `configs/default.yaml` |
| 拍手能量门限 + 冷却 | 能 | mock 音频脚本注入 |
| GCC-PHAT 时延/方位估算 | 能 | 合成双麦信号 |
| 三态状态机 `IDLE/TURN_ONCE/FOLLOW` | 能 | `src/app.py` |
| 人脸 dx 死区步进跟随 | 能 | mock 视觉轨迹 |
| 舵机限位 / 回中 | 能 | `MockServo` |
| 真麦克风 / 真相机 / 真舵机 | 否 | 需上树莓派联调 |

## 主流程（当前 mock 脚本）

1. `t≈0.4s`：检测到拍手，估计方位约 `+30°`
2. 进入 `TURN_ONCE`，开环转到目标角
3. 进入 `FOLLOW`，根据人脸水平偏差左右步进
4. 人脸丢失超时后回中，回到 `IDLE`

## 下一步（连上树莓派后）

把 `MockAudioSource` / `MockVisionSource` / `MockServo` 换成真实驱动，接口已经留好：

- `AudioSource.read() -> AudioEvent`
- `VisionSource.read() -> VisionEvent`
- `ServoDriver.set_angle()`

`scripts/deploy_to_pi.sh` 只是部署骨架，默认会走正常 SSH 密码验证。
