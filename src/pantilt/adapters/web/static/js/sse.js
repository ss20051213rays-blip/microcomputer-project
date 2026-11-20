/**
 * Server-Sent Events (SSE) 事件流监听与管理
 * 建立与 /api/stream/events 的长连接，解包遥测数据、突发声学事件与实时日志。
 */

export class SSEClient {
    constructor(options = {}) {
        this.url = options.url || '/api/stream/events';
        this.onTelemetry = options.onTelemetry || (() => {});
        this.onAcoustic = options.onAcoustic || (() => {});
        this.onStateChange = options.onStateChange || (() => {});
        this.onAlert = options.onAlert || (() => {});
        this.onLog = options.onLog || (() => {});
        this.onStatusChange = options.onStatusChange || (() => {});

        this.eventSource = null;
        this.connected = false;
        this.reconnectTimer = null;
        this.pollTimer = null;
        this.reconnectDelay = 2000;
    }

    start() {
        this.connect();
    }

    connect() {
        if (this.eventSource) {
            try { this.eventSource.close(); } catch (_) {}
        }

        this.onStatusChange('connecting');

        try {
            this.eventSource = new EventSource(this.url);

            this.eventSource.onopen = () => {
                this.connected = true;
                this.onStatusChange('connected');
                this.stopPollingFallback();
            };

            this.eventSource.addEventListener('telemetry', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.onTelemetry(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse telemetry:', err);
                }
            });

            this.eventSource.addEventListener('acoustic', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.onAcoustic(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse acoustic event:', err);
                }
            });

            this.eventSource.addEventListener('state_change', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.onStateChange(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse state_change event:', err);
                }
            });

            this.eventSource.addEventListener('alert', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.onAlert(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse alert event:', err);
                }
            });

            this.eventSource.addEventListener('log', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.onLog(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse log event:', err);
                }
            });

            this.eventSource.onerror = (err) => {
                this.connected = false;
                this.onStatusChange('disconnected');
                try { this.eventSource.close(); } catch (_) {}
                this.eventSource = null;
                this.scheduleReconnect();
                this.startPollingFallback();
            };
        } catch (err) {
            this.connected = false;
            this.onStatusChange('error');
            this.scheduleReconnect();
            this.startPollingFallback();
        }
    }

    scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, this.reconnectDelay);
    }

    startPollingFallback() {
        if (this.pollTimer) return;
        // 若 SSE 长连接意外断开，降级为 2Hz REST 轮询以保底界面遥测不冻结
        this.pollTimer = setInterval(async () => {
            try {
                const res = await fetch('/api/telemetry');
                if (res.ok) {
                    const payload = await res.json();
                    if (payload && payload.data) {
                        this.onTelemetry(payload.data);
                    }
                }
            } catch (_) {}
        }, 500);
    }

    stopPollingFallback() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }

    stop() {
        this.stopPollingFallback();
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.eventSource) {
            try { this.eventSource.close(); } catch (_) {}
            this.eventSource = null;
        }
        this.connected = false;
        this.onStatusChange('disconnected');
    }
}
