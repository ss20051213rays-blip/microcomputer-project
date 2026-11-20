/**
 * 视口 3: 两轴云台交互控制台与仪表盘 (Yaw/Pitch Gimbals & Jog Controller)
 * 支持两轴角度仪表盘、虚拟触摸摇杆、八向微调点动键盘、模式切换及紧急回中。
 */
import { Api } from './api.js';

export class GimbalWidget {
    constructor(container, options = {}) {
        this.container = container;
        this.onCommand = options.onCommand || (() => {});
        this.playFeedback = options.playFeedback || (() => {});

        this.currentYaw = 0.0;
        this.currentPitch = 0.0;
        this.stepDegYaw = 2.0;
        this.stepDegPitch = 1.5;
        this.selectedStep = 2.0;

        this.initDOM();
        this.bindEvents();
    }

    initDOM() {
        this.container.innerHTML = `
            <div class="gimbal-cockpit">
                <!-- 角度仪表双联表盘 -->
                <div class="gauges-row">
                    <div class="gauge-card" id="gauge-yaw">
                        <div class="gauge-header">
                            <span class="gauge-title">YAW 偏航角</span>
                            <span class="gauge-limits">[-90° ~ +90°]</span>
                        </div>
                        <div class="gauge-body">
                            <div class="gauge-arc-wrap">
                                <svg class="gauge-svg" viewBox="0 0 160 90">
                                    <path class="gauge-track" d="M 15 80 A 65 65 0 0 1 145 80" />
                                    <path class="gauge-fill" id="yaw-fill" d="M 15 80 A 65 65 0 0 1 145 80" />
                                    <line class="gauge-needle" id="yaw-needle" x1="80" y1="80" x2="80" y2="20" />
                                </svg>
                                <div class="gauge-value" id="yaw-value">+0.0°</div>
                            </div>
                        </div>
                    </div>

                    <div class="gauge-card" id="gauge-pitch">
                        <div class="gauge-header">
                            <span class="gauge-title">PITCH 俯仰角</span>
                            <span class="gauge-limits">[-30° ~ +45°]</span>
                        </div>
                        <div class="gauge-body">
                            <div class="gauge-arc-wrap">
                                <svg class="gauge-svg" viewBox="0 0 160 90">
                                    <path class="gauge-track" d="M 15 80 A 65 65 0 0 1 145 80" />
                                    <path class="gauge-fill" id="pitch-fill" d="M 15 80 A 65 65 0 0 1 145 80" />
                                    <line class="gauge-needle" id="pitch-needle" x1="80" y1="80" x2="80" y2="20" />
                                </svg>
                                <div class="gauge-value" id="pitch-value">+0.0°</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 交互操控区：虚拟摇杆 + 八向微调面板 -->
                <div class="controls-row">
                    <!-- 虚拟摇杆 -->
                    <div class="joystick-card">
                        <div class="joystick-label">2-DOF 虚拟摇杆</div>
                        <div class="joystick-pad" id="joystick-pad">
                            <div class="joystick-crosshair"></div>
                            <div class="joystick-thumb" id="joystick-thumb"></div>
                        </div>
                    </div>

                    <!-- 点动微调方向键盘 -->
                    <div class="jog-dpad-card">
                        <div class="step-selector">
                            <span class="step-label">步长:</span>
                            <button class="step-btn" data-step="0.5">0.5°</button>
                            <button class="step-btn" data-step="1.0">1.0°</button>
                            <button class="step-btn active" data-step="2.0">2.0°</button>
                            <button class="step-btn" data-step="5.0">5.0°</button>
                        </div>
                        <div class="dpad-grid">
                            <div></div>
                            <button class="dpad-btn" id="jog-up" title="Pitch + (向上抬头)">▲</button>
                            <div></div>
                            <button class="dpad-btn" id="jog-left" title="Yaw - (向左偏航)">◀</button>
                            <button class="dpad-btn center-btn" id="jog-center" title="一键安全回中 (0°, 0°)">🎯</button>
                            <button class="dpad-btn" id="jog-right" title="Yaw + (向右偏航)">▶</button>
                            <div></div>
                            <button class="dpad-btn" id="jog-down" title="Pitch - (向下低头)">▼</button>
                            <div></div>
                        </div>
                    </div>
                </div>

                <!-- 战术动作按键栏 -->
                <div class="action-buttons-row">
                    <button class="hud-btn btn-mode" id="btn-toggle-mode">
                        <span class="btn-icon">⚡</span> 模式: <strong id="mode-text">AUTO</strong>
                    </button>
                    <button class="hud-btn btn-laser" id="btn-toggle-laser">
                        <span class="btn-icon">🔴</span> 激光: <strong id="laser-text">OFF</strong>
                    </button>
                    <button class="hud-btn btn-center" id="btn-center">
                        <span class="btn-icon">⌖</span> 安全归中
                    </button>
                    <button class="hud-btn btn-reset" id="btn-reset">
                        <span class="btn-icon">↺</span> 复位 IDLE
                    </button>
                </div>
            </div>
        `;
    }

    bindEvents() {
        // 步长切换
        const stepBtns = this.container.querySelectorAll('.step-btn');
        stepBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                stepBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.selectedStep = parseFloat(btn.dataset.step) || 2.0;
                this.playFeedback('click');
            });
        });

        // D-Pad 点动微调
        this.container.querySelector('#jog-up').addEventListener('click', () => {
            this.sendJog(0, this.selectedStep);
        });
        this.container.querySelector('#jog-down').addEventListener('click', () => {
            this.sendJog(0, -this.selectedStep);
        });
        this.container.querySelector('#jog-left').addEventListener('click', () => {
            this.sendJog(-this.selectedStep, 0);
        });
        this.container.querySelector('#jog-right').addEventListener('click', () => {
            this.sendJog(this.selectedStep, 0);
        });
        this.container.querySelector('#jog-center').addEventListener('click', () => {
            this.centerGimbal();
        });

        // 动作按键
        this.container.querySelector('#btn-center').addEventListener('click', () => {
            this.centerGimbal();
        });
        this.container.querySelector('#btn-reset').addEventListener('click', () => {
            this.resetSystem();
        });
        this.container.querySelector('#btn-toggle-mode').addEventListener('click', () => {
            this.toggleMode();
        });
        this.container.querySelector('#btn-toggle-laser').addEventListener('click', () => {
            this.toggleLaser();
        });

        // 虚拟摇杆交互
        this.initJoystick();
    }

    initJoystick() {
        const pad = this.container.querySelector('#joystick-pad');
        const thumb = this.container.querySelector('#joystick-thumb');
        if (!pad || !thumb) return;

        let isDragging = false;
        let padRect = null;
        let padRadius = 50;

        const updatePosition = (clientX, clientY) => {
            if (!padRect) padRect = pad.getBoundingClientRect();
            const cx = padRect.left + padRect.width / 2;
            const cy = padRect.top + padRect.height / 2;
            let dx = clientX - cx;
            let dy = clientY - cy;

            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist > padRadius) {
                dx = (dx / dist) * padRadius;
                dy = (dy / dist) * padRadius;
            }

            thumb.style.transform = `translate(${dx}px, ${dy}px)`;

            // 归一化输入 [-1.0 ~ +1.0]
            const normX = dx / padRadius;
            const normY = -dy / padRadius; // 上推为正(Pitch+)
            return { normX, normY };
        };

        const resetThumb = () => {
            isDragging = false;
            thumb.style.transform = 'translate(0px, 0px)';
        };

        pad.addEventListener('mousedown', (e) => {
            isDragging = true;
            padRect = pad.getBoundingClientRect();
            updatePosition(e.clientX, e.clientY);
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const { normX, normY } = updatePosition(e.clientX, e.clientY);
            // 阻尼节流下发
            if (Math.abs(normX) > 0.2 || Math.abs(normY) > 0.2) {
                const deltaYaw = normX * this.selectedStep;
                const deltaPitch = normY * this.selectedStep;
                this.sendJog(deltaYaw, deltaPitch, true);
            }
        });

        window.addEventListener('mouseup', resetThumb);

        // 触屏支持
        pad.addEventListener('touchstart', (e) => {
            isDragging = true;
            padRect = pad.getBoundingClientRect();
            const touch = e.touches[0];
            updatePosition(touch.clientX, touch.clientY);
        }, { passive: true });

        window.addEventListener('touchmove', (e) => {
            if (!isDragging) return;
            const touch = e.touches[0];
            const { normX, normY } = updatePosition(touch.clientX, touch.clientY);
            if (Math.abs(normX) > 0.2 || Math.abs(normY) > 0.2) {
                this.sendJog(normX * this.selectedStep, normY * this.selectedStep, true);
            }
        }, { passive: true });

        window.addEventListener('touchend', resetThumb);
    }

    async sendJog(deltaYaw, deltaPitch, isJoystick = false) {
        try {
            if (!isJoystick) this.playFeedback('beep');
            const res = await Api.controlServoStep(deltaYaw, deltaPitch);
            if (res && res.data) {
                this.updateAngles(res.data.applied_yaw, res.data.applied_pitch);
            }
        } catch (err) {
            console.error('[Gimbal] Jog error:', err);
        }
    }

    async centerGimbal() {
        try {
            this.playFeedback('center');
            const res = await Api.centerGimbal();
            this.updateAngles(0.0, 0.0);
        } catch (err) {
            console.error('[Gimbal] Center error:', err);
        }
    }

    async toggleMode() {
        const currentMode = this.container.querySelector('#mode-text').textContent;
        const targetMode = currentMode === 'AUTO' ? 'MANUAL' : 'AUTO';
        try {
            this.playFeedback('beep');
            const res = await Api.setMode(targetMode);
            this.updateMode(res?.data?.mode || targetMode);
        } catch (err) {
            console.error('[Gimbal] Toggle mode error:', err);
        }
    }

    async toggleLaser() {
        const isCurrentlyOn = this.container.querySelector('#laser-text').textContent === 'ACTIVE';
        const targetState = !isCurrentlyOn;
        try {
            this.playFeedback(targetState ? 'laser_on' : 'click');
            const res = await Api.controlLaser(targetState, true);
            this.updateLaser(res?.data?.is_on);
        } catch (err) {
            console.error('[Gimbal] Toggle laser error:', err);
        }
    }

    async resetSystem() {
        try {
            this.playFeedback('beep');
            await Api.resetSystem();
            this.updateAngles(0.0, 0.0);
        } catch (err) {
            console.error('[Gimbal] Reset error:', err);
        }
    }

    updateTelemetry(telemetry) {
        if (!telemetry) return;
        const servo = telemetry.servo || {};
        const status = telemetry.status || {};
        const laser = telemetry.laser || {};

        this.updateAngles(servo.yaw, servo.pitch);
        this.updateMode(status.control_mode);
        this.updateLaser(laser.is_on);
    }

    updateAngles(yaw, pitch) {
        if (yaw !== undefined && yaw !== null) {
            this.currentYaw = Number(yaw);
            const yawEl = this.container.querySelector('#yaw-value');
            if (yawEl) yawEl.textContent = `${this.currentYaw > 0 ? '+' : ''}${this.currentYaw.toFixed(1)}°`;

            // 更新表盘指针 (Yaw: -90°~+90° 映射到 SVG 角度 -60° ~ +60°)
            const needle = this.container.querySelector('#yaw-needle');
            if (needle) {
                const rot = (this.currentYaw / 90) * 60;
                needle.style.transform = `rotate(${rot}deg)`;
                needle.style.transformOrigin = '80px 80px';
            }
        }

        if (pitch !== undefined && pitch !== null) {
            this.currentPitch = Number(pitch);
            const pitchEl = this.container.querySelector('#pitch-value');
            if (pitchEl) pitchEl.textContent = `${this.currentPitch > 0 ? '+' : ''}${this.currentPitch.toFixed(1)}°`;

            // 更新表盘指针 (Pitch: -30°~+45° 映射到 SVG 角度 -40° ~ +60°)
            const needle = this.container.querySelector('#pitch-needle');
            if (needle) {
                const rot = (this.currentPitch / 45) * 50;
                needle.style.transform = `rotate(${rot}deg)`;
                needle.style.transformOrigin = '80px 80px';
            }
        }
    }

    updateMode(mode) {
        const modeText = this.container.querySelector('#mode-text');
        const btn = this.container.querySelector('#btn-toggle-mode');
        if (!modeText || !btn) return;
        modeText.textContent = mode || 'AUTO';
        if (mode === 'MANUAL') {
            btn.classList.add('mode-manual');
        } else {
            btn.classList.remove('mode-manual');
        }
    }

    updateLaser(isOn) {
        const laserText = this.container.querySelector('#laser-text');
        const btn = this.container.querySelector('#btn-toggle-laser');
        if (!laserText || !btn) return;
        laserText.textContent = isOn ? 'ACTIVE' : 'OFF';
        if (isOn) {
            btn.classList.add('laser-active');
        } else {
            btn.classList.remove('laser-active');
        }
    }
}
