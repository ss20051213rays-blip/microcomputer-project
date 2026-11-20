/**
 * REST API 异步客户端 (原生 Fetch 实现)
 * 封装与后端 WebRuntimeServer 的全量 HTTP 接口通信。
 */

const API_BASE = '';

async function request(url, options = {}) {
    const defaultHeaders = {
        'Accept': 'application/json',
    };
    if (options.body && typeof options.body === 'object') {
        options.body = JSON.stringify(options.body);
        defaultHeaders['Content-Type'] = 'application/json';
    }
    const response = await fetch(API_BASE + url, {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers,
        },
    });
    if (!response.ok) {
        let errMessage = `HTTP ${response.status} ${response.statusText}`;
        try {
            const errData = await response.json();
            if (errData && errData.message) {
                errMessage = errData.message;
            }
        } catch (_) {}
        throw new Error(errMessage);
    }
    return response.json();
}

export const Api = {
    // 宏观状态与全量遥测快照
    getStatus: () => request('/api/status'),
    getTelemetry: () => request('/api/telemetry'),

    // 控制参数与日志
    getConfig: () => request('/api/config'),
    updateConfig: (params) => request('/api/config', {
        method: 'POST',
        body: { params },
    }),
    getLogs: (limit = 50) => request(`/api/logs?limit=${limit}`),

    // 云台与执行器控制
    controlServoStep: (deltaYaw, deltaPitch) => request('/api/control/servo', {
        method: 'POST',
        body: {
            mode: 'step',
            delta_yaw: parseFloat(deltaYaw),
            delta_pitch: parseFloat(deltaPitch),
        },
    }),

    controlServoAbsolute: (yaw, pitch) => request('/api/control/servo', {
        method: 'POST',
        body: {
            mode: 'absolute',
            yaw: yaw !== null ? parseFloat(yaw) : undefined,
            pitch: pitch !== null ? parseFloat(pitch) : undefined,
        },
    }),

    centerGimbal: () => request('/api/control/center', {
        method: 'POST',
        body: {},
    }),

    controlLaser: (enable, forceOverride = false) => request('/api/control/laser', {
        method: 'POST',
        body: {
            enable: Boolean(enable),
            force_override: Boolean(forceOverride),
        },
    }),

    setMode: (mode) => request('/api/control/mode', {
        method: 'POST',
        body: { mode: String(mode).toUpperCase() },
    }),

    resetSystem: () => request('/api/control/reset', {
        method: 'POST',
        body: {},
    }),
};
