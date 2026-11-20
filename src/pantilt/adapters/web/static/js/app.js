/**
 * 前端应用主入口 (Application Orchestrator)
 * 组装四大视口组件、建立 SSE 事件流订阅、提供 Web Audio 交互声效与全局键盘快捷键。
 */

import { Api } from './api.js';
import { SSEClient } from './sse.js';
import { HUDCanvasRenderer } from './hud_canvas.js';
import { RadarCanvasRenderer } from './radar_canvas.js';
import { GimbalWidget } from './gimbal_widget.js';
import { TelemetryView } from './telemetry_view.js';
import { TerminalLogs } from './terminal_logs.js';

class TacticalApp {
    constructor() {
        this.audioCtx = null;
        this.soundMuted = false;

        // 子组件引用
        this.hudRenderer = null;
        this.radarRenderer = null;
        this.gimbalWidget = null;
        this.telemetryView = null;
        this.terminalLogs = null;
        this.sseClient = null;

        this.init();
    }

    async init() {
        console.log('[App] Initializing Pan-Tilt Tactical Web HUD...');

        this.initAudioFeedback();
        this.initDOMComponents();
        this.initHeaderControls();
        this.initKeyboardShortcuts();
        this.initSSE();

        // 初始拉取历史日志与状态
        try {
            const logsRes = await Api.getLogs(50);
            if (logsRes && logsRes.data) {
                this.terminalLogs.setInitialLogs(logsRes.data);
            }
        } catch (_) {}

        console.log('[App] Tactical Web HUD successfully initialized.');
    }

    initAudioFeedback() {
        const initCtx = () => {
            if (!this.audioCtx) {
                const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
                if (AudioCtxClass) {
                    this.audioCtx = new AudioCtxClass();
                }
            }
            window.removeEventListener('click', initCtx);
            window.removeEventListener('keydown', initCtx);
        };
        window.addEventListener('click', initCtx);
        window.addEventListener('keydown', initCtx);
    }

    playFeedback(type) {
        if (this.soundMuted || !this.audioCtx) return;
        try {
            const ctx = this.audioCtx;
            if (ctx.state === 'suspended') ctx.resume();

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            const now = ctx.currentTime;

            if (type === 'beep') {
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, now);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);
                osc.start(now);
                osc.stop(now + 0.08);
            } else if (type === 'click') {
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(440, now);
                gain.gain.setValueAtTime(0.04, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
                osc.start(now);
                osc.stop(now + 0.04);
            } else if (type === 'laser_on') {
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(1200, now);
                osc.frequency.linearRampToValueAtTime(600, now + 0.2);
                gain.gain.setValueAtTime(0.12, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
                osc.start(now);
                osc.stop(now + 0.25);
            } else if (type === 'lock') {
                osc.type = 'square';
                osc.frequency.setValueAtTime(1046, now);
                osc.frequency.setValueAtTime(1318, now + 0.08);
                gain.gain.setValueAtTime(0.06, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
                osc.start(now);
                osc.stop(now + 0.2);
            } else if (type === 'center') {
                osc.type = 'sine';
                osc.frequency.setValueAtTime(523, now);
                osc.frequency.linearRampToValueAtTime(784, now + 0.15);
                gain.gain.setValueAtTime(0.06, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
                osc.start(now);
                osc.stop(now + 0.18);
            }
        } catch (_) {}
    }

    initDOMComponents() {
        // 1. 视口 1: 实况视频与 HUD Canvas
        const hudCanvas = document.getElementById('hud-canvas');
        const videoImg = document.getElementById('video-stream-img');
        this.hudRenderer = new HUDCanvasRenderer(hudCanvas, videoImg);

        // 2. 视口 2: 空间声学极坐标雷达
        const radarCanvas = document.getElementById('radar-canvas');
        this.radarRenderer = new RadarCanvasRenderer(radarCanvas);

        // 3. 视口 3: 双轴云台控制台
        const gimbalContainer = document.getElementById('viewport-gimbal');
        this.gimbalWidget = new GimbalWidget(gimbalContainer, {
            playFeedback: (t) => this.playFeedback(t),
        });

        // 4. 视口 4: 系统全量遥测大屏
        const telemetryContainer = document.getElementById('viewport-telemetry');
        this.telemetryView = new TelemetryView(telemetryContainer, {
            playFeedback: (t) => this.playFeedback(t),
        });

        // 5. 视口 4: 实时日志终端
        const terminalContainer = document.getElementById('viewport-terminal');
        this.terminalLogs = new TerminalLogs(terminalContainer);
    }

    initHeaderControls() {
        // 视频流 HUD 开关 (切换 ?raw=1 与 ?hud=1)
        const toggleStreamHudBtn = document.getElementById('btn-toggle-stream-hud');
        const videoImg = document.getElementById('video-stream-img');
        let isHudMode = false;

        if (toggleStreamHudBtn && videoImg) {
            toggleStreamHudBtn.addEventListener('click', () => {
                isHudMode = !isHudMode;
                videoImg.src = isHudMode ? '/api/stream/video?hud=1' : '/api/stream/video?raw=1';
                toggleStreamHudBtn.textContent = `流模式: ${isHudMode ? '后端HUD' : '原始RAW'}`;
                this.playFeedback('click');
            });
        }

        // 音效静音开关
        const muteBtn = document.getElementById('btn-toggle-sound');
        if (muteBtn) {
            muteBtn.addEventListener('click', () => {
                this.soundMuted = !this.soundMuted;
                muteBtn.textContent = `音效: ${this.soundMuted ? 'MUTE' : 'ON'}`;
                muteBtn.classList.toggle('active', !this.soundMuted);
                this.playFeedback('click');
            });
        }

        // 顶部模式与复位快捷按钮
        document.getElementById('header-btn-center')?.addEventListener('click', () => {
            this.gimbalWidget.centerGimbal();
        });
    }

    initKeyboardShortcuts() {
        window.addEventListener('keydown', (e) => {
            // 如果焦点在输入框内则不触发快捷键
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;

            const step = this.gimbalWidget.selectedStep || 2.0;

            switch (e.key) {
                case 'ArrowLeft':
                case 'a':
                case 'A':
                    e.preventDefault();
                    this.gimbalWidget.sendJog(-step, 0);
                    break;
                case 'ArrowRight':
                case 'd':
                case 'D':
                    e.preventDefault();
                    this.gimbalWidget.sendJog(step, 0);
                    break;
                case 'ArrowUp':
                case 'w':
                case 'W':
                    e.preventDefault();
                    this.gimbalWidget.sendJog(0, step);
                    break;
                case 'ArrowDown':
                case 's':
                case 'S':
                    e.preventDefault();
                    this.gimbalWidget.sendJog(0, -step);
                    break;
                case ' ':
                case 'c':
                case 'C':
                    e.preventDefault();
                    this.gimbalWidget.centerGimbal();
                    break;
                case 'l':
                case 'L':
                    e.preventDefault();
                    this.gimbalWidget.toggleLaser();
                    break;
                case 'm':
                case 'M':
                    e.preventDefault();
                    this.gimbalWidget.toggleMode();
                    break;
                case 'r':
                case 'R':
                    e.preventDefault();
                    this.gimbalWidget.resetSystem();
                    break;
            }
        });
    }

    initSSE() {
        const connBadge = document.getElementById('header-conn-status');

        this.sseClient = new SSEClient({
            url: '/api/stream/events',
            onTelemetry: (telemetry) => {
                this.hudRenderer.updateTelemetry(telemetry);
                this.radarRenderer.updateTelemetry(telemetry);
                this.gimbalWidget.updateTelemetry(telemetry);
                this.telemetryView.updateTelemetry(telemetry);
            },
            onAcoustic: (event) => {
                this.radarRenderer.triggerAcousticRipple(event);
                this.playFeedback('beep');
                this.terminalLogs.addLog({
                    level: 'INFO',
                    logger: 'Audio',
                    message: `[声学检测] 方位角: ${event.theta_deg > 0 ? '+' : ''}${event.theta_deg}° (${event.side}), 置信度: ${Math.round(event.confidence * 100)}%`,
                });
            },
            onStateChange: (stateData) => {
                this.playFeedback('beep');
                this.terminalLogs.addLog({
                    level: 'INFO',
                    logger: 'FSM',
                    message: `[状态转移] ${stateData.from_state} ➔ ${stateData.to_state} (${stateData.reason || ''})`,
                });
            },
            onAlert: (alertData) => {
                this.playFeedback('laser_on');
                this.terminalLogs.addLog({
                    level: alertData.level || 'WARNING',
                    logger: 'Safety',
                    message: `[安全联锁] ${alertData.message}`,
                });
            },
            onLog: (logData) => {
                this.terminalLogs.addLog(logData);
            },
            onStatusChange: (status) => {
                if (!connBadge) return;
                if (status === 'connected') {
                    connBadge.textContent = 'ONLINE (SSE)';
                    connBadge.className = 'header-badge badge-online';
                } else if (status === 'connecting') {
                    connBadge.textContent = 'CONNECTING...';
                    connBadge.className = 'header-badge badge-connecting';
                } else {
                    connBadge.textContent = 'POLLING (FALLBACK)';
                    connBadge.className = 'header-badge badge-fallback';
                }
            },
        });

        this.sseClient.start();
    }
}

// 页面加载完成后启动单例应用
document.addEventListener('DOMContentLoaded', () => {
    window.pantiltApp = new TacticalApp();
});
