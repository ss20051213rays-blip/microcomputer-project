# Web HUD Architecture & Communication Protocol Specification

Please refer to the comprehensive specification document:
- [Web前端总体架构与通信接口协议规范.md](Web前端总体架构与通信接口协议规范.md)

### Executive Summary

- **Layering**: Clean Architecture adapter under `src/pantilt/adapters/web/`.
- **Runtime**: Zero heavy npm build. Vanilla modern ES6+ Modules, CSS custom properties (Cyber/Tactical HUD dark theme), HTML5 Canvas 2D (acoustic polar radar + live HUD crosshair overlay), Web Audio API.
- **Protocols**:
  - **REST API** (`/api/status`, `/api/telemetry`, `/api/control/*`, `/api/config`, `/api/logs`)
  - **Server-Sent Events (SSE)** (`/api/stream/events`) for 20~30 Hz live telemetry push, acoustic triggers, state change broadcasts, and logs.
  - **MJPEG Stream** (`/api/stream/video`) for low-latency live camera streaming with synthetic dry-run fallback.
  - **WebSocket** (`/ws`) optional bidirectional channel.
- **Safety Interlocks**:
  - Gimbal 2-DOF software limit clamping (`yaw`: -90°~+90°, `pitch`: -30°~+45°).
  - Laser indicator 10s maximum continuous-on timeout protection.
  - Mode switching between `AUTO` (Audio-Visual FSM) and `MANUAL` (Web teleoperation).
- **Python Schema**:
  - Implemented in `src/pantilt/adapters/web/protocol.py`.
