# 视听融合云台系统 · Web前端总体架构与通信接口协议规范 (M7 Web HUD)

> **版本**：v1.0.0  
> **编写者**：系统架构师 (`architect`)  
> **归属模块**：M7 交互与多媒体 (Web 监控中心与实况 HUD 遥测大屏)  
> **技术定位**：前后端极度轻量、零重型构建依赖、原生自包含、ARMv8 (树莓派 4B) 硬件友好

---

## 1. 架构背景与设计目标

### 1.1 演进背景与系统定位
本项目为《微机原理与微系统》课程设计旗舰项目：**视听融合声源定位与目标跟踪两轴总线云台系统**。
在前期阶段中，系统已构建了基于 Clean Architecture 分层架构的完整控制闭环：
- **执行层**：微雪串行总线舵机驱动 2-DOF 云台（Yaw 水平偏航 + Pitch 垂直俯仰）与 50mW 物理激光指示器；
- **感知层**：WM8960 硬件双麦立体声阵列（GCC-PHAT 亚采样互相关测向）与 OV9281 120fps 全局快门相机（ArUco 工业靶标与人脸双模视觉伺服）；
- **领域控制层**：三态状态机（`IDLE` -> `TURN_ONCE` -> `FOLLOW`）与两轴死区步进控制器。

随着系统从桌面裸机单机运行迈向高完成度工程交付，原有的终端控制台打印与本地 HDMI 拓展坞硬连线显示存在物理布线繁复、远程观测不便、交互调试门槛高等局限。
**M7 阶段的目标是打造全功能现代化 Web 前端监控与控制大屏（Web Tactical HUD）**，通过拓展坞千兆网线或 Wi-Fi 热点，使得任何操作人员在笔记本电脑、平板或手机浏览器中即可实现：
1. **实况战术 HUD 视频监视**（视频流、动态十字准星、跟踪偏差向量、目标识别框、激光点亮警告）；
2. **空间声学雷达声源监视**（极坐标声纳扫描盘、DoA 声源指向指针、双麦实时电平柱）；
3. **两轴姿态双向交互控制**（双轴刻度仪表、虚拟摇杆/键盘控制、AUTO/MANUAL 模式平滑切换、紧急回中）；
4. **全系统遥测大屏与滚动日志终端**（主循环 Hz、视觉 FPS、状态机驻留计时、实时后端结构化日志）。

---

### 1.2 架构设计三大铁律

1. **严格遵循整洁分层架构 (Clean Architecture / Hexagonal Architecture)**：
   - Web 运行时作为 Presentation/Runtime 适配器收敛于 `src/pantilt/adapters/web/`；
   - 依赖方向严格单向向内：`adapters/web` -> `application/tracker` -> `domain`；
   - 绝对禁止 Web 适配器逆向污染领域模型与核心状态机逻辑。

2. **零重型 npm 构建依赖，极度轻量与自包含 (Zero-build Self-contained)**：
   - 树莓派 4B ARM 架构 CPU 与内存资源极其宝贵，必须优先保障 120fps 视觉采集与声学实时处理；
   - 坚决杜绝在树莓派上安装 Node.js、npm、Webpack、Vite 或引入上百兆 `node_modules` 依赖池；
   - 前端采用**现代原生 Web 技术栈**（原生 ES6+ Modules、现代化 CSS Custom Properties、HTML5 Canvas 2D、原生 Web Audio 与 Server-Sent Events），零编译、零打包、开箱即用，代码总重 < 100KB。

3. **双向低延迟与高鲁棒性通信协议栈**：
   - 单向高频遥测：基于 **Server-Sent Events (SSE)**，原生自动重连、极低协议报头开销；
   - 视频低延迟投屏：基于 **MJPEG** Multipart 流，零解码器依赖，浏览器原生毫秒级呈现；
   - 控制与配置指令：基于 **REST API (JSON)**，状态明确、幂等安全、包含严格限位与超时校验；
   - 脱机/无硬件自愈：支持 `dry_run` 模式，自动生成合成靶标与模拟雷达数据，实现脱机 100% 独立开发与测试。

---

## 2. 系统总体架构与模块关系

### 2.1 整体分层拓扑图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Client Browser (Web UI)                           │
│  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────┐  │
│  │ 1. 战术 HUD 视频视口  │ │ 2. 空间声学雷达视口   │ │ 3. 云台仪表与摇杆 │  │
│  │   (Raw MJPEG + Canvas)│ │   (Polar Radar Canvas)│ │ (Yaw/Pitch + Jog) │  │
│  └───────────────────────┘ └───────────────────────┘ └───────────────────┘  │
│  ┌─────────────────────────────────────────────────┐ ┌───────────────────┐  │
│  │ 4. 系统遥测大屏与终端控制台日志 (Metrics & Logs) │ │ 运行模式切换器    │  │
│  └─────────────────────────────────────────────────┘ └───────────────────┘  │
└──────────────┬─────────────────────────▲───────────────────────▲────────────┘
               │ HTTP GET/POST (REST)    │ SSE (text/event-stream)│ MJPEG Video
               ▼                         │ (20~30 Hz Telemetry)  │ (30~60 FPS)
┌─────────────────────────────────────────────────────────────────────────────┐
│ Web Runtime Adapter (src/pantilt/adapters/web/)                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ HTTP Micro-Server (ThreadingHTTPServer) @ port 8080                   │  │
│  │  ├─ Static Router: / (index.html, css/hud.css, js/app.js)             │  │
│  │  ├─ REST Dispatcher: /api/status, /api/control/*, /api/config, etc.   │  │
│  │  ├─ SSE Streamer: /api/stream/events (Telemetry, Acoustic, Logs)     │  │
│  │  └─ MJPEG Streamer: /api/stream/video (Frame Buffer / Synthetic Mock) │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────┐ ┌───────────────────────────────────┐  │
│  │ Protocol DTO & Schema Validator │ │ Ring-Buffer Log Handler           │  │
│  └─────────────────────────────────┘ └───────────────────────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ Dependency Injection / App Context
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Application Layer (src/pantilt/application/)                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ PanTiltTrackerApp (Main Loop Tick @ 30Hz, State Management, Safety)   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└───────────────┬───────────────────────────────┬─────────────────────────────┘
                ▼                               ▼
┌───────────────────────────────┐ ┌───────────────────────────────────────────┐
│ Domain Layer (src/pantilt/    │ │ Hardware Adapters (src/pantilt/adapters/) │
│               domain/)        │ │  ├─ Actuation: ServoController (Bus/PWM), │
│  ├─ TrackerStateMachine (FSM) │ │                LaserIndicator             │
│  ├─ DeadzoneStepController    │ │  ├─ Perception: VisionPipeline (OV9281),  │
│  └─ Core Types & Enums        │ │                 AudioPipeline (WM8960)    │
└───────────────────────────────┘ └───────────────────────────────────────────┘
```

---

## 3. 通信接口协议详细规范

### 3.1 路由总表 (WebRoutes)

| 路由路径 | HTTP 方法 | 通信模式 | 功能说明 | 认证/限流 |
| :--- | :--- | :--- | :--- | :--- |
| `/` | `GET` | 静态页面 | 交付现代化战术 HUD 单页应用 (HTML) | 静态公开 |
| `/static/*` | `GET` | 静态资源 | 交付 CSS 样式、ES 模块 JavaScript、音效资源 | 浏览器缓存 |
| `/api/status` | `GET` | REST JSON | 获取系统健康度、宏观状态机状态、版本与运行时间 | 无 |
| `/api/telemetry` | `GET` | REST JSON | 获取当前全量传感器与执行器遥测快照 | 无 |
| `/api/stream/events` | `GET` | SSE 持续流 | 20~30 Hz 高频遥测推送、突发声学事件与系统日志广播 | Keep-Alive |
| `/api/stream/video` | `GET` | MJPEG 持续流 | 实时视频画面传输（支持 `?raw=1` 与 `?hud=1`） | Multipart |
| `/api/control/servo` | `POST` | REST JSON | 双轴云台控制：支持增量微调 (`step`) 与绝对定位 (`absolute`) | 限位校验 |
| `/api/control/center` | `POST` | REST JSON | 云台双轴一键安全回中 (`0.0°, 0.0°`) | 幂等 |
| `/api/control/laser` | `POST` | REST JSON | 激光指示器手动控制开关（受 10s 安全联锁保护） | 超时联锁 |
| `/api/control/mode` | `POST` | REST JSON | 运行模式切换：`AUTO` (视听自主) / `MANUAL` (人工控制) | 状态校验 |
| `/api/control/reset` | `POST` | REST JSON | 状态机复位回到 `IDLE` 初始监听态 | 幂等 |
| `/api/config` | `GET/POST`| REST JSON | 查询或动态热更新控制阈值（死区、步长、超时时间等） | 动态生效 |
| `/api/logs` | `GET` | REST JSON | 拉取最近 100 条环形缓冲运行日志 | 分页/Limit |
| `/ws` | `GET(Upgrade)`| WebSocket | 双向长连接扩展通道（备用） | 二进制/JSON |

---

### 3.2 REST API 接口详细规格

#### 1. 系统宏观状态查询 (`GET /api/status`)
- **请求方法**：`GET`
- **响应格式**：`application/json; charset=utf-8`
- **响应体示例**：
```json
{
  "code": 200,
  "data": {
    "app_state": "FOLLOW",
    "control_mode": "AUTO",
    "running": true,
    "dry_run": false,
    "uptime_s": 142.8,
    "main_loop_hz": 30.0,
    "version": "0.2.0",
    "cpu_temp_c": 46.5
  },
  "message": "success"
}
```

#### 2. 全量遥测快照 (`GET /api/telemetry`)
- **请求方法**：`GET`
- **响应体示例**：
```json
{
  "code": 200,
  "data": {
    "timestamp_mono": 1284.521,
    "iso_time": "2026-11-10T20:15:30.521Z",
    "status": {
      "app_state": "FOLLOW",
      "control_mode": "AUTO",
      "running": true,
      "dry_run": false,
      "uptime_s": 142.8,
      "main_loop_hz": 30.0,
      "version": "0.2.0",
      "cpu_temp_c": 46.5
    },
    "servo": {
      "yaw": 24.0,
      "pitch": -8.5,
      "target_yaw": 24.0,
      "target_pitch": -8.5,
      "min_yaw": -90.0,
      "max_yaw": 90.0,
      "min_pitch": -30.0,
      "max_pitch": 45.0,
      "driver_type": "bus",
      "torque_enabled": true
    },
    "vision": {
      "target_found": true,
      "target_type": "aruco",
      "target_id": 12,
      "dx_px": 5.2,
      "dy_px": -3.8,
      "bbox": [280, 160, 80, 80],
      "confidence": 1.0,
      "fps": 118.5,
      "in_deadzone": true,
      "age_s": 0.008
    },
    "audio": {
      "event_detected": true,
      "theta_deg": 25.0,
      "side": "right",
      "confidence": 0.88,
      "method": "gcc_phat",
      "energy_rms": 0.082,
      "age_s": 12.4
    },
    "laser": {
      "is_on": true,
      "continuous_s": 1.4,
      "max_continuous_s": 10.0,
      "locked_frames": 5,
      "lock_min_frames": 3,
      "hardware_enabled": true
    }
  },
  "message": "success"
}
```

#### 3. 双轴云台控制 (`POST /api/control/servo`)
- **请求方法**：`POST`
- **请求体（增量步进模式）**：
```json
{
  "mode": "step",
  "delta_yaw": 2.0,
  "delta_pitch": -1.5
}
```
- **请求体（绝对定位模式）**：
```json
{
  "mode": "absolute",
  "yaw": 30.0,
  "pitch": 15.0
}
```
- **参数约束与安全拦截**：
  - 系统内置严格限位：`yaw ∈ [-90.0, +90.0]`，`pitch ∈ [-30.0, +45.0]`；
  - 若指令超出限位，后端自动截断（Clamp）至临界值并返回实际设置角度，绝不抛出破坏硬件的无效命令；
  - 若当前处于 `AUTO` 模式且未切换至 `MANUAL`，后端自动将系统模式平滑切换为 `MANUAL` 或在响应中提示模式变更。
- **响应体示例**：
```json
{
  "code": 200,
  "data": {
    "applied_yaw": 30.0,
    "applied_pitch": 15.0,
    "clamped": false
  },
  "message": "Servo angles updated successfully."
}
```

#### 4. 云台一键归中 (`POST /api/control/center`)
- **请求方法**：`POST`
- **请求体**：`{}`
- **业务行为**：将偏航角归零 (`0.0°`)、俯仰角归零 (`0.0°`)，重置状态机为 `IDLE`。
- **响应体**：
```json
{
  "code": 200,
  "data": { "yaw": 0.0, "pitch": 0.0 },
  "message": "Gimbal centered."
}
```

#### 5. 激光指示器手动控制 (`POST /api/control/laser`)
- **请求方法**：`POST`
- **请求体**：
```json
{
  "enable": true,
  "force_override": true
}
```
- **安全保障逻辑**：
  - 无论是否来自 Web 强制点亮，激光底层 `LaserIndicator` 的 `max_continuous_s`（10 秒）硬件安全保护倒计时严格生效；
  - 超过 10 秒后自动强制断开，防止激光管过热烧毁与人眼直视隐患。
- **响应体**：
```json
{
  "code": 200,
  "data": {
    "is_on": true,
    "max_continuous_s": 10.0
  },
  "message": "Laser enabled with safety timeout."
}
```

#### 6. 运行模式切换 (`POST /api/control/mode`)
- **请求方法**：`POST`
- **请求体**：
```json
{
  "mode": "MANUAL"
}
```
- **模式定义**：
  - `AUTO`：视听融合自主跟踪状态机接管执行器，Web 端仅作监控或辅助干预；
  - `MANUAL`：挂起自主视觉与声学下发，舵机和激光仅响应 Web 端操控指令；切出 `MANUAL` 返回 `AUTO` 时，状态机自动归为 `IDLE` 监听态。
- **响应体**：
```json
{
  "code": 200,
  "data": { "mode": "MANUAL" },
  "message": "Mode switched."
}
```

#### 7. 运行时配置查询与动态热更 (`GET/POST /api/config`)
- **`GET /api/config` 响应体**：
```json
{
  "code": 200,
  "data": {
    "deadzone_px_x": 30,
    "deadzone_px_y": 25,
    "step_deg_yaw": 2.0,
    "step_deg_pitch": 1.5,
    "lost_timeout_s": 3.0,
    "turn_settle_s": 0.3,
    "energy_threshold": 0.05
  },
  "message": "success"
}
```
- **`POST /api/config` 请求体**（支持局部更新）：
```json
{
  "params": {
    "deadzone_px_x": 20,
    "step_deg_yaw": 1.5
  }
}
```

#### 8. 系统日志查询 (`GET /api/logs`)
- **请求参数**：`limit`（默认 50，最大 200）
- **响应体示例**：
```json
{
  "code": 200,
  "data": [
    {
      "timestamp": 1731269730.12,
      "iso_time": "2026-11-10 20:15:30",
      "level": "INFO",
      "logger": "App",
      "message": "[状态转移] IDLE -> TURN_ONCE | 拍手方位=right, 估计角度=+25.0°"
    }
  ],
  "message": "success"
}
```

---

### 3.3 Server-Sent Events (SSE) 实时推流规范

#### 1. 协议特点
- **端点**：`GET /api/stream/events`
- **协议标头**：
  ```http
  Content-Type: text/event-stream; charset=utf-8
  Cache-Control: no-cache, no-transform
  Connection: keep-alive
  Access-Control-Allow-Origin: *
  ```
- **工作机制**：单条长连接维持，浏览器通过原生 `new EventSource('/api/stream/events')` 接入；断线时浏览器底层自动重连（约 3s），零代码心跳自愈。

#### 2. 事件帧分类规范
- **`telemetry` 事件**（20 Hz 周期推送）：
  ```text
  event: telemetry
  data: {"timestamp_mono":1284.52,"iso_time":"2026-11-10T20:15:30.521Z","status":{...},"servo":{...},"vision":{...},"audio":{...},"laser":{...}}

  ```
- **`acoustic` 事件**（声源突发检测即刻触发）：
  ```text
  event: acoustic
  data: {"theta_deg":-32.5,"side":"left","confidence":0.91,"method":"gcc_phat","rms":0.112}

  ```
- **`state_change` 事件**（状态机转移瞬时触发）：
  ```text
  event: state_change
  data: {"from_state":"IDLE","to_state":"TURN_ONCE","target_yaw":-32.5,"reason":"Acoustic detection"}

  ```
- **`alert` 事件**（安全联锁或硬件告警）：
  ```text
  event: alert
  data: {"level":"WARNING","type":"LASER_TIMEOUT","message":"Laser continuous on time exceeded 10.0s, forced off."}

  ```
- **`log` 事件**（实时日志行广播）：
  ```text
  event: log
  data: {"time":"20:15:30","level":"INFO","logger":"App","message":"Servo stepped to Yaw=+2.0°"}

  ```

---

### 3.4 MJPEG 实时视频流规范

#### 1. 协议特点
- **端点**：`GET /api/stream/video`
- **协议标头**：
  ```http
  Content-Type: multipart/x-mixed-replace; boundary=frame
  Cache-Control: no-cache, private
  Connection: close
  ```
- **数据帧格式**：
  ```text
  --frame
  Content-Type: image/jpeg
  Content-Length: 18452

  <Binary JPEG Data>
  --frame
  ...
  ```

#### 2. 模式参数支持
- `GET /api/stream/video?raw=1`（推荐）：输出无水印纯净相机画面，降低后端图像重绘与编解码 CPU 开销；由前端 Canvas 战术 HUD 根据最新遥测数据在客户端本地实时叠加十字准星、误差向量与识别框（达到 60~120 FPS 丝滑动画且 0 树莓派 CPU 负担）。
- `GET /api/stream/video?hud=1`：后端在图像上烧录十字准星与文字（用于调试或纯静态浏览器直接浏览）。
- **脱机模拟 (Dry-run Fallback)**：
  - 当无真实 OV9281 相机连接时，视频推流线程自动渲染 640x400 高拟真战术网格背景，包含动态正弦波运动的模拟 ArUco 靶标与动态时间码，确保前端开发在任何无硬件环境下 100% 独立验证。

---

## 4. 前端界面架构与视口布局规范

### 4.1 四象限战术座舱布局 (4-Quadrant Tactical Cockpit)

界面采用充满未来科技感的暗色机甲/战术 HUD 视觉设计（深灰黑背景 `#0a0e14`、亮青荧光绿 `#00ff9d`、战术琥珀橙 `#ffaa00` 与警示激光红 `#ff3344`）。

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│ [TOP BAR] 🎯 视听融合智能跟踪云台 Web HUD | 状态: [FOLLOW] | 模式: [AUTO] | 118 FPS │
├────────────────────────────────────────┬────────────────────────────────────────┤
│ 【视口 1】实况战术 HUD 视频视口         │ 【视口 2】空间声学雷达视口              │
│  - 实时 120fps OV9281 视频流画布       │  - 180°/360° 极坐标声纳扫描圆盘        │
│  - 动态十字瞄准准星 (锁定绿 / 调整橙)  │  - 实时 GCC-PHAT 测向波束指针与置信度扇形│
│  - 靶心偏差矢量指示线 (dx, dy)         │  - 左右声道立体声 VU 电平柱动态跳动     │
│  - ArUco ID / 人脸识别包围框           │  - 降级模式 (energy_diff) 提示牌       │
│  - [LASER ACTIVE: 3.5s] 红色警示浮层   │                                        │
├────────────────────────────────────────┼────────────────────────────────────────┤
│ 【视口 3】两轴云台仪表与交互摇杆       │ 【视口 4】系统遥测大屏与实时终端控制台  │
│  - 水平 Yaw 双向仪表弧 (-90° ~ +90°)   │  - 核心指标卡：主循环 Hz / 丢脸计时器  │
│  - 垂直 Pitch 俯仰仪表弧 (-30° ~ +45°) │  - 连续锁定帧计数器 / 激光倒计时       │
│  - 虚拟 2D 触控摇杆与八向微调步进键盘  │  - 战术深黑背景可滚动系统日志控制台    │
│  - [AUTO/MANUAL] 模式切换按键          │  - 实时日志过滤 (INFO/WARN/ERROR)      │
│  - [EMERGENCY CENTER] 一键紧急归中按键 │  - 激光安全切断 / 状态机单步复位       │
└────────────────────────────────────────┴────────────────────────────────────────┘
```

### 4.2 前端代码组织架构 (自包含原生结构)

所有前端静态资源置于 `src/pantilt/adapters/web/static/`：
```text
src/pantilt/adapters/web/static/
├── index.html              # 单页主入口：语义化 DOM 结构与四大视口骨架
├── css/
│   ├── hud.css             # 战术 HUD 机甲主题样式、CSS Grid 响应式布局、动画关键帧
│   └── components.css      # 表盘、摇杆、VU 电平条、终端控制台等细分组件样式
├── js/
│   ├── app.js              # 前端生命周期主入口、事件流接入与组件装配
│   ├── api.js              # REST API 异步请求封装 (fetch)
│   ├── sse.js              # Server-Sent Events 事件源监听与状态解包
│   ├── hud_canvas.js       # 视口 1: 视频覆盖层动态 Canvas 准星与靶标渲染器
│   ├── radar_canvas.js     # 视口 2: 空间声学极坐标雷达 Canvas 动态渲染器
│   ├── gimbal_widget.js    # 视口 3: 双轴角度仪表盘与虚拟触控摇杆交互器
│   ├── telemetry_view.js   # 视口 4: 遥测数据卡片与指标动态刷新器
│   └── terminal_logs.js    # 视口 4: 滚动日志控制台与等级着色器
└── assets/
    └── sound/              # 极轻量音效 (可选: lock.mp3, beep.mp3)
```

### 4.3 零重型构建技术实现要点
1. **模块加载**：在 `index.html` 中通过 `<script type="module" src="/static/js/app.js"></script>` 加载，由现代浏览器原生支持 ES 模块树导入，无需 Webpack/Vite 捆绑。
2. **样式隔离与自适应**：基于 CSS Variables (`:root { --hud-cyan: #00f3ff; --hud-green: #00ff9d; --hud-red: #ff3344; ... }`)，利用 CSS Grid 实现 $2 \times 2$ 等宽等高自适应网格，在桌面 1080P/2K 屏幕及平板均可完美撑满视口 (`height: 100vh`)。
3. **高帧率 Canvas 渲染优化**：采用 `requestAnimationFrame` 驱动准星 HUD 与声学雷达扫描动画，与后台 20Hz 遥测数据流解耦，确保哪怕数据更新间隔为 50ms，准星和雷达波束依然能以 60 FPS 平滑补间过渡。

---

## 5. 树莓派 ARM 资源预算与性能安全

### 5.1 算力与网络吞吐预算 (树莓派 4B 基准)

| 模块 / 任务 | 消耗资源类型 | 预算上限 | 保障策略 |
| :--- | :--- | :--- | :--- |
| **Python HTTP / SSE 线程** | CPU 单核占用 | $\le 3\%$ | 纯 I/O 事件驱动，每次推送仅数十字节 JSON |
| **MJPEG 图像推流** | CPU / 编码开销 | $\le 8\%$ | 优先直推 OpenCV 已编码的 JPEG 缓冲，避开二次压缩 |
| **网络带宽占用** | 千兆网线 / Wi-Fi | $\le 2.5 \text{ MB/s}$ | 640x400 JPEG @ 30fps 单帧约 30KB，总带宽仅约 1MB/s |
| **前端浏览器内存** | 客户端 RAM | $\le 60 \text{ MB}$ | 日志限制最近 200 条，Canvas 离屏缓冲复用，无内存泄漏 |

### 5.2 安全联锁与异常降级策略

1. **激光超时物理与网络双重锁死**：
   - 激光手动点亮指令发出后，无论 Web 页面是否关闭或断网，后端 `LaserIndicator` 会在单调时钟到达 10 秒时无条件强制拉低 GPIO 关闭激光。
2. **两轴舵机越界软保护**：
   - 所有输入的 `yaw` 与 `pitch` 在进入驱动层前严格经由 `ServoControlCommand.validate_and_clamp` 截断，舵机物理死区与硬限位绝不发生撞墙堵转。
3. **网络断连自动归中与保底**：
   - 若处于 `MANUAL` 模式且超过 5 秒未收到任何 Web 心跳或控制输入，系统自动发出警告，安全平滑归中并自动转入 `AUTO` 状态机监听态。

---

## 6. 下游任务交付对接指南

本规范已由 `architect` 冻结并作为 M7 前端工程标准规范，指导后续团队成员任务推进：

1. **对接任务 2 (`doc_specialist`)**：
   - 基于本规范中的 M7 方案，同步扩充更新 `docs/视听融合声源定位与目标跟踪云台-开发计划.md` 中的“阶段八：M7 交互多媒体”与“微机原理答辩演示方案”。
2. **对接任务 3 (`frontend_engineer`)**：
   - 在 `src/pantilt/adapters/web/` 下实现轻量 HTTP 服务器、REST 路由分发器、SSE 遥测推流器与 MJPEG 视频流发生器（依赖 `src/pantilt/adapters/web/protocol.py`）。
3. **对接任务 4 (`frontend_engineer`)**：
   - 在 `src/pantilt/adapters/web/static/` 下实现高颜值四象限战术 HUD 前端单页系统（HTML5/CSS3/Canvas/ES6）。
4. **对接任务 5 & 6 (`qa_engineer`)**：
   - 基于本规范编写 REST API 接口自动化单元测试、SSE 遥测推流解析测试、限位拦截测试及极端断网与高并发压力测试用例。
