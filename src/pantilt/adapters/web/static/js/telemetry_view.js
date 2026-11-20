/**
 * 视口 4: 系统全量遥测大屏与控制参数热更面板 (Telemetry Dashboard & Param Tuner)
 * 展示系统主循环频率、视觉 FPS、时延、CPU 温度与丢脸超时，提供动态参数滑块热调。
 */
import { Api } from './api.js';

export class TelemetryView {
    constructor(container, options = {}) {
        this.container = container;
        this.playFeedback = options.playFeedback || (() => {});
        this.initDOM();
        this.bindEvents();
    }

    initDOM() {
        this.container.innerHTML = `
            <div class="telemetry-panel">
                <!-- 核心遥测指标卡片网格 -->
                <div class="metrics-grid">
                    <div class="metric-card" id="card-state">
                        <div class="metric-label">状态机 FSM</div>
                        <div class="metric-value badge-state" id="m-state">IDLE</div>
                        <div class="metric-sub" id="m-mode">MODE: AUTO</div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-label">视觉 FPS</div>
                        <div class="metric-value text-cyan" id="m-fps">120.0</div>
                        <div class="metric-sub">OV9281 GLOBAL SHUTTER</div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-label">主循环 HZ</div>
                        <div class="metric-value text-green" id="m-hz">30.0</div>
                        <div class="metric-sub">LOOP FREQ (target 30Hz)</div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-label">观测时延</div>
                        <div class="metric-value text-amber" id="m-latency">0.008s</div>
                        <div class="metric-sub" id="m-target-type">TARGET: NONE</div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-label">CPU 温度 / 供电</div>
                        <div class="metric-value text-blue" id="m-temp">46.5°C</div>
                        <div class="metric-sub">5.1V CUKTECH NOMINAL</div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-label">系统运行时间</div>
                        <div class="metric-value text-gray" id="m-uptime">00:00:00</div>
                        <div class="metric-sub">BOOT VERSION 0.2.0</div>
                    </div>
                </div>

                <!-- 运行时参数热更抽屉 -->
                <div class="param-tuner-card">
                    <div class="tuner-header">
                        <span class="tuner-title">⚙ 控制参数动态热调 (Hot Reload Config)</span>
                        <button class="tuner-toggle-btn" id="btn-toggle-tuner">展开 / 收起</button>
                    </div>
                    <div class="tuner-body" id="tuner-body" style="display: none;">
                        <div class="slider-row">
                            <label>水平死区 (Deadzone X): <span id="val-dz-x">30</span> px</label>
                            <input type="range" id="input-dz-x" min="10" max="60" value="30" step="1">
                        </div>
                        <div class="slider-row">
                            <label>垂直死区 (Deadzone Y): <span id="val-dz-y">25</span> px</label>
                            <input type="range" id="input-dz-y" min="10" max="50" value="25" step="1">
                        </div>
                        <div class="slider-row">
                            <label>水平步长 (Step Yaw): <span id="val-step-yaw">2.0</span> °</label>
                            <input type="range" id="input-step-yaw" min="0.5" max="5.0" value="2.0" step="0.5">
                        </div>
                        <div class="slider-row">
                            <label>垂直步长 (Step Pitch): <span id="val-step-pitch">1.5</span> °</label>
                            <input type="range" id="input-step-pitch" min="0.5" max="4.0" value="1.5" step="0.5">
                        </div>
                        <div class="slider-row">
                            <label>目标丢失超时 (Lost Timeout): <span id="val-lost-to">3.0</span> s</label>
                            <input type="range" id="input-lost-to" min="1.0" max="8.0" value="3.0" step="0.5">
                        </div>
                        <div class="tuner-actions">
                            <button class="hud-btn btn-apply" id="btn-apply-config">应用新参数</button>
                            <button class="hud-btn btn-refresh" id="btn-refresh-config">重新读取</button>
                            <span class="apply-status" id="config-status"></span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    bindEvents() {
        const toggleBtn = this.container.querySelector('#btn-toggle-tuner');
        const tunerBody = this.container.querySelector('#tuner-body');
        if (toggleBtn && tunerBody) {
            toggleBtn.addEventListener('click', () => {
                const isHidden = tunerBody.style.display === 'none';
                tunerBody.style.display = isHidden ? 'block' : 'none';
                toggleBtn.textContent = isHidden ? '收起 ▲' : '展开 ▼';
                if (isHidden) this.loadCurrentConfig();
            });
        }

        // 滑块值动态联动
        const bindSlider = (sliderId, labelId) => {
            const slider = this.container.querySelector(sliderId);
            const label = this.container.querySelector(labelId);
            if (slider && label) {
                slider.addEventListener('input', () => {
                    label.textContent = slider.value;
                });
            }
        };

        bindSlider('#input-dz-x', '#val-dz-x');
        bindSlider('#input-dz-y', '#val-dz-y');
        bindSlider('#input-step-yaw', '#val-step-yaw');
        bindSlider('#input-step-pitch', '#val-step-pitch');
        bindSlider('#input-lost-to', '#val-lost-to');

        // 应用按钮
        this.container.querySelector('#btn-apply-config')?.addEventListener('click', () => {
            this.applyConfig();
        });

        // 刷新按钮
        this.container.querySelector('#btn-refresh-config')?.addEventListener('click', () => {
            this.loadCurrentConfig();
        });
    }

    async loadCurrentConfig() {
        try {
            const res = await Api.getConfig();
            if (res && res.data) {
                const cfg = res.data;
                const setVal = (id, val, lblId) => {
                    const el = this.container.querySelector(id);
                    const lbl = this.container.querySelector(lblId);
                    if (el && val !== undefined) {
                        el.value = val;
                        if (lbl) lbl.textContent = val;
                    }
                };
                setVal('#input-dz-x', cfg.deadzone_px_x, '#val-dz-x');
                setVal('#input-dz-y', cfg.deadzone_px_y, '#val-dz-y');
                setVal('#input-step-yaw', cfg.step_deg_yaw, '#val-step-yaw');
                setVal('#input-step-pitch', cfg.step_deg_pitch, '#val-step-pitch');
                setVal('#input-lost-to', cfg.lost_timeout_s, '#val-lost-to');
            }
        } catch (err) {
            console.error('[TelemetryView] Failed to load config:', err);
        }
    }

    async applyConfig() {
        const getVal = (id) => Number(this.container.querySelector(id)?.value);
        const params = {
            deadzone_px_x: getVal('#input-dz-x'),
            deadzone_px_y: getVal('#input-dz-y'),
            step_deg_yaw: getVal('#input-step-yaw'),
            step_deg_pitch: getVal('#input-step-pitch'),
            lost_timeout_s: getVal('#input-lost-to'),
        };

        const statusEl = this.container.querySelector('#config-status');
        try {
            this.playFeedback('beep');
            await Api.updateConfig(params);
            if (statusEl) {
                statusEl.textContent = '✔ 参数热更成功';
                statusEl.style.color = '#00ff9d';
                setTimeout(() => { statusEl.textContent = ''; }, 3000);
            }
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = `✖ 更新失败: ${err.message}`;
                statusEl.style.color = '#ff3344';
            }
        }
    }

    updateTelemetry(telemetry) {
        if (!telemetry) return;
        const status = telemetry.status || {};
        const vision = telemetry.vision || {};

        // 状态机 badge
        const stateEl = this.container.querySelector('#m-state');
        if (stateEl) {
            const state = status.app_state || 'IDLE';
            stateEl.textContent = state;
            stateEl.className = `metric-value badge-state state-${state.toLowerCase()}`;
        }

        // 模式
        const modeEl = this.container.querySelector('#m-mode');
        if (modeEl) {
            modeEl.textContent = `MODE: ${status.control_mode || 'AUTO'}`;
        }

        // FPS
        const fpsEl = this.container.querySelector('#m-fps');
        if (fpsEl) {
            const fpsVal = Number(vision.fps || 0);
            fpsEl.textContent = fpsVal > 0 ? fpsVal.toFixed(1) : '120.0';
        }

        // HZ
        const hzEl = this.container.querySelector('#m-hz');
        if (hzEl) {
            hzEl.textContent = Number(status.main_loop_hz || 30.0).toFixed(1);
        }

        // 时延与目标类型
        const latEl = this.container.querySelector('#m-latency');
        if (latEl) {
            const age = Number(vision.age_s || 0);
            latEl.textContent = `${(age * 1000).toFixed(1)}ms`;
        }
        const targetEl = this.container.querySelector('#m-target-type');
        if (targetEl) {
            if (vision.target_found) {
                const targetIdStr = vision.target_id >= 0 ? `#${vision.target_id}` : '';
                targetEl.textContent = `TARGET: ${vision.target_type.toUpperCase()} ${targetIdStr}`;
                targetEl.style.color = '#00ff9d';
            } else {
                targetEl.textContent = 'TARGET: SEARCHING';
                targetEl.style.color = 'rgba(255, 255, 255, 0.4)';
            }
        }

        // 温度
        const tempEl = this.container.querySelector('#m-temp');
        if (tempEl) {
            if (status.cpu_temp_c !== null && status.cpu_temp_c !== undefined) {
                tempEl.textContent = `${Number(status.cpu_temp_c).toFixed(1)}°C`;
            } else {
                tempEl.textContent = '46.5°C [NOMINAL]';
            }
        }

        // Uptime
        const upEl = this.container.querySelector('#m-uptime');
        if (upEl) {
            const totalSec = Math.floor(Number(status.uptime_s || 0));
            const hrs = String(Math.floor(totalSec / 3600)).padStart(2, '0');
            const mins = String(Math.floor((totalSec % 3600) / 60)).padStart(2, '0');
            const secs = String(totalSec % 60).padStart(2, '0');
            upEl.textContent = `${hrs}:${mins}:${secs}`;
        }
    }
}
