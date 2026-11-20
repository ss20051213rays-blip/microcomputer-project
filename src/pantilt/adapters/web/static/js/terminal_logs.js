/**
 * 视口 4: 实时终端滚动日志与等级着色器 (Terminal Logs)
 * 接收 SSE log 事件与 REST 历史日志，按等级着色，提供过滤与自动锁底滚动。
 */

export class TerminalLogs {
    constructor(container, options = {}) {
        this.container = container;
        this.maxLogs = options.maxLogs || 200;
        this.logs = [];
        this.currentFilter = 'ALL';
        this.autoScroll = true;

        this.initDOM();
        this.bindEvents();
    }

    initDOM() {
        this.container.innerHTML = `
            <div class="terminal-card">
                <div class="terminal-header">
                    <div class="terminal-title">
                        <span class="terminal-icon">❯_</span> 系统实时滚动日志终端 (SYSTEM LOGS)
                    </div>
                    <div class="terminal-controls">
                        <div class="filter-group">
                            <button class="filter-btn active" data-filter="ALL">ALL</button>
                            <button class="filter-btn" data-filter="INFO">INFO</button>
                            <button class="filter-btn" data-filter="WARNING">WARN</button>
                            <button class="filter-btn" data-filter="ERROR">ERROR</button>
                        </div>
                        <button class="term-btn" id="btn-toggle-autoscroll" title="锁定自动滚动到最底">锁底: ON</button>
                        <button class="term-btn" id="btn-clear-logs" title="清空当前日志显示">清屏</button>
                    </div>
                </div>
                <div class="terminal-body" id="terminal-body">
                    <div class="log-entry log-info">
                        <span class="log-time">[INIT]</span>
                        <span class="log-badge badge-info">INFO</span>
                        <span class="log-logger">[App]</span>
                        <span class="log-msg">Web 战术 HUD 终端已连接，等待后端日志推流...</span>
                    </div>
                </div>
            </div>
        `;
    }

    bindEvents() {
        // 过滤器按钮
        const filterBtns = this.container.querySelectorAll('.filter-btn');
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentFilter = btn.dataset.filter || 'ALL';
                this.render();
            });
        });

        // 锁底开关
        const scrollBtn = this.container.querySelector('#btn-toggle-autoscroll');
        if (scrollBtn) {
            scrollBtn.addEventListener('click', () => {
                this.autoScroll = !this.autoScroll;
                scrollBtn.textContent = `锁底: ${this.autoScroll ? 'ON' : 'OFF'}`;
                if (this.autoScroll) this.scrollToBottom();
            });
        }

        // 清屏
        this.container.querySelector('#btn-clear-logs')?.addEventListener('click', () => {
            this.logs = [];
            this.render();
        });

        // 用户手动向上滚动时解除锁底
        const bodyEl = this.container.querySelector('#terminal-body');
        if (bodyEl) {
            bodyEl.addEventListener('scroll', () => {
                const isNearBottom = bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight < 30;
                if (!isNearBottom && this.autoScroll) {
                    this.autoScroll = false;
                    if (scrollBtn) scrollBtn.textContent = '锁底: OFF';
                }
            });
        }
    }

    addLog(entry) {
        if (!entry) return;
        const normalized = {
            time: entry.time || (entry.iso_time ? entry.iso_time.split(' ')[1] : new Date().toLocaleTimeString()),
            level: (entry.level || 'INFO').toUpperCase(),
            logger: entry.logger || 'App',
            message: entry.message || '',
        };

        this.logs.push(normalized);
        if (this.logs.length > this.maxLogs) {
            this.logs.shift();
        }

        if (this.shouldDisplay(normalized)) {
            this.appendEntryToDOM(normalized);
            if (this.autoScroll) {
                this.scrollToBottom();
            }
        }
    }

    setInitialLogs(entries) {
        if (!Array.isArray(entries)) return;
        this.logs = entries.map(e => ({
            time: e.iso_time ? e.iso_time.split(' ')[1] : new Date(e.timestamp * 1000).toLocaleTimeString(),
            level: (e.level || 'INFO').toUpperCase(),
            logger: e.logger || 'App',
            message: e.message || '',
        }));
        this.render();
    }

    shouldDisplay(entry) {
        if (this.currentFilter === 'ALL') return true;
        if (this.currentFilter === 'WARNING') {
            return entry.level === 'WARNING' || entry.level === 'WARN';
        }
        return entry.level === this.currentFilter;
    }

    render() {
        const bodyEl = this.container.querySelector('#terminal-body');
        if (!bodyEl) return;
        bodyEl.innerHTML = '';

        const visibleLogs = this.logs.filter(e => this.shouldDisplay(e));
        for (const log of visibleLogs) {
            bodyEl.appendChild(this.createLogNode(log));
        }

        if (this.autoScroll) {
            this.scrollToBottom();
        }
    }

    createLogNode(log) {
        const div = document.createElement('div');
        const lvlClass = `log-${log.level.toLowerCase()}`;
        div.className = `log-entry ${lvlClass}`;

        const timeSpan = document.createElement('span');
        timeSpan.className = 'log-time';
        timeSpan.textContent = `[${log.time}]`;

        const badgeSpan = document.createElement('span');
        badgeSpan.className = `log-badge badge-${log.level.toLowerCase()}`;
        badgeSpan.textContent = log.level;

        const loggerSpan = document.createElement('span');
        loggerSpan.className = 'log-logger';
        loggerSpan.textContent = `[${log.logger}]`;

        const msgSpan = document.createElement('span');
        msgSpan.className = 'log-msg';
        msgSpan.textContent = log.message;

        div.appendChild(timeSpan);
        div.appendChild(badgeSpan);
        div.appendChild(loggerSpan);
        div.appendChild(msgSpan);

        return div;
    }

    appendEntryToDOM(log) {
        const bodyEl = this.container.querySelector('#terminal-body');
        if (!bodyEl) return;
        bodyEl.appendChild(this.createLogNode(log));
    }

    scrollToBottom() {
        const bodyEl = this.container.querySelector('#terminal-body');
        if (bodyEl) {
            bodyEl.scrollTop = bodyEl.scrollHeight;
        }
    }
}
