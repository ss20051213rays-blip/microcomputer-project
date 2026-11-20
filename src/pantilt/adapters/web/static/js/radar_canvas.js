/**
 * 视口 2: 空间声学定位极坐标雷达画板 (Canvas 2D)
 * 渲染 180° 半球极坐标扫描盘、GCC-PHAT 测向波束指针、置信度扇形、
 * 拍手突发声源波纹扩散动画及左右声道立体声 VU 跳动电平柱。
 */

export class RadarCanvasRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');

        this.telemetry = null;
        this.sweepAngle = -Math.PI / 2; // 扫描线当前弧度
        this.sweepSpeed = 2.2;          // 弧度/秒

        // 突发事件扩散波纹动画列表: [{ angleDeg, radius, maxRadius, alpha, time }]
        this.ripples = [];

        // 立体声 VU 电平平滑缓存
        this.leftLevel = 0;
        this.rightLevel = 0;
        this.peakLeft = 0;
        this.peakRight = 0;

        this.initResize();
        this.startLoop();
    }

    initResize() {
        const resize = () => {
            const rect = this.canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            this.canvas.width = rect.width * dpr;
            this.canvas.height = rect.height * dpr;
            this.width = rect.width;
            this.height = rect.height;
        };
        window.addEventListener('resize', resize);
        resize();
    }

    updateTelemetry(telemetry) {
        this.telemetry = telemetry;
        const audio = telemetry?.audio || {};

        // 模拟/更新 VU 电平跳动
        const rms = Number(audio.energy_rms || 0);
        const theta = Number(audio.theta_deg || 0);

        // 左右声道能量分配 (负偏向左，正偏向右)
        let lTarget = rms * (theta < 0 ? 1.4 : 0.7);
        let rTarget = rms * (theta > 0 ? 1.4 : 0.7);
        lTarget = Math.min(1.0, Math.max(0.05, lTarget + Math.random() * 0.05));
        rTarget = Math.min(1.0, Math.max(0.05, rTarget + Math.random() * 0.05));

        this.leftLevel += (lTarget - this.leftLevel) * 0.4;
        this.rightLevel += (rTarget - this.rightLevel) * 0.4;
        this.peakLeft = Math.max(this.peakLeft * 0.96, this.leftLevel);
        this.peakRight = Math.max(this.peakRight * 0.96, this.rightLevel);
    }

    triggerAcousticRipple(event) {
        const theta = Number(event?.theta_deg || 0);
        this.ripples.push({
            angleDeg: theta,
            radius: 10,
            maxRadius: 130,
            alpha: 1.0,
            color: '#00ff9d',
        });
    }

    startLoop() {
        let lastTime = performance.now();
        const render = (now) => {
            const dt = (now - lastTime) / 1000;
            lastTime = now;

            this.sweepAngle += this.sweepSpeed * dt;
            if (this.sweepAngle > Math.PI * 1.5) {
                this.sweepAngle = -Math.PI / 2;
            }

            this.draw(dt);
            requestAnimationFrame(render);
        };
        requestAnimationFrame(render);
    }

    draw(dt) {
        const ctx = this.ctx;
        const dpr = window.devicePixelRatio || 1;
        const w = this.width;
        const h = this.height;
        if (!w || !h) return;

        ctx.save();
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, w, h);

        const cx = w / 2;
        const cy = h * 0.72; // 雷达锚定于下方，展开上半球 180°
        const maxR = Math.min(w * 0.42, h * 0.6);

        // 1. 绘制极坐标同心半圆与方位射线
        this.drawPolarGrid(ctx, cx, cy, maxR);

        // 2. 绘制连续扫描波束 (Phosphor Sweep)
        this.drawSweepTrail(ctx, cx, cy, maxR);

        // 3. 绘制声源突发波纹 (Acoustic Ripples)
        this.updateAndDrawRipples(ctx, cx, cy, maxR, dt);

        // 4. 绘制 GCC-PHAT 测向指针与置信度扇面
        this.drawDoaPointer(ctx, cx, cy, maxR);

        // 5. 绘制左右声道立体声 VU 电平柱
        this.drawStereoVUMeters(ctx, w, h);

        // 6. 绘制声学状态徽标与数值读数
        this.drawTelemetryOverlay(ctx, w, h);

        ctx.restore();
    }

    drawPolarGrid(ctx, cx, cy, maxR) {
        ctx.save();
        ctx.strokeStyle = 'rgba(0, 243, 255, 0.18)';
        ctx.lineWidth = 1;

        // 同心半圆弧 (25%, 50%, 75%, 100%)
        const rings = [0.25, 0.5, 0.75, 1.0];
        for (const ring of rings) {
            ctx.beginPath();
            ctx.arc(cx, cy, maxR * ring, Math.PI, 0);
            ctx.stroke();
        }

        // 基准地平线
        ctx.beginPath();
        ctx.moveTo(cx - maxR - 15, cy);
        ctx.lineTo(cx + maxR + 15, cy);
        ctx.stroke();

        // 方位射线: -90°, -60°, -30°, 0°, +30°, +60°, +90°
        const angles = [-90, -60, -30, 0, 30, 60, 90];
        ctx.fillStyle = 'rgba(0, 243, 255, 0.55)';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';

        for (const deg of angles) {
            const rad = ((deg - 90) * Math.PI) / 180;
            const x1 = cx + Math.cos(rad) * (maxR * 0.2);
            const y1 = cy + Math.sin(rad) * (maxR * 0.2);
            const x2 = cx + Math.cos(rad) * maxR;
            const y2 = cy + Math.sin(rad) * maxR;

            ctx.strokeStyle = deg === 0 ? 'rgba(0, 255, 157, 0.4)' : 'rgba(0, 243, 255, 0.15)';
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();

            // 标注角度文字
            const tx = cx + Math.cos(rad) * (maxR + 14);
            const ty = cy + Math.sin(rad) * (maxR + 14);
            ctx.fillText(`${deg > 0 ? '+' : ''}${deg}°`, tx, ty + 3);
        }

        ctx.restore();
    }

    drawSweepTrail(ctx, cx, cy, maxR) {
        ctx.save();
        // 限制在半圆视口内
        ctx.beginPath();
        ctx.arc(cx, cy, maxR, Math.PI, 0);
        ctx.lineTo(cx, cy);
        ctx.closePath();
        ctx.clip();

        // 仅在扫描线在 -PI 到 0 范围内时显示荧光渐变扇区
        const normAngle = ((this.sweepAngle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
        // 上半圆对应 3PI/2 附近与 PI 附近
        const trailWidth = 0.45; // 渐变扇区宽度(弧度)

        const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
        gradient.addColorStop(0, 'rgba(0, 255, 157, 0.3)');
        gradient.addColorStop(1, 'rgba(0, 255, 157, 0.02)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, maxR, this.sweepAngle - trailWidth, this.sweepAngle);
        ctx.closePath();
        ctx.fill();

        // 扫描前锋高亮线
        ctx.strokeStyle = 'rgba(0, 255, 157, 0.8)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(this.sweepAngle) * maxR, cy + Math.sin(this.sweepAngle) * maxR);
        ctx.stroke();

        ctx.restore();
    }

    updateAndDrawRipples(ctx, cx, cy, maxR, dt) {
        ctx.save();
        for (let i = this.ripples.length - 1; i >= 0; i--) {
            const r = this.ripples[i];
            r.radius += 110 * dt;
            r.alpha -= 0.65 * dt;

            if (r.alpha <= 0 || r.radius >= maxR) {
                this.ripples.splice(i, 1);
                continue;
            }

            const rad = ((r.angleDeg - 90) * Math.PI) / 180;
            const rx = cx + Math.cos(rad) * r.radius;
            const ry = cy + Math.sin(rad) * r.radius;

            ctx.strokeStyle = `rgba(0, 255, 157, ${r.alpha})`;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(rx, ry, 10 + r.radius * 0.15, 0, Math.PI * 2);
            ctx.stroke();

            // 靶点脉冲
            ctx.fillStyle = `rgba(0, 255, 157, ${r.alpha * 0.6})`;
            ctx.beginPath();
            ctx.arc(rx, ry, 4, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();
    }

    drawDoaPointer(ctx, cx, cy, maxR) {
        const audio = this.telemetry?.audio;
        if (!audio || !audio.event_detected) return;

        const theta = Number(audio.theta_deg || 0);
        const conf = Number(audio.confidence || 0);
        const method = audio.method || 'gcc_phat';

        ctx.save();
        const rad = ((theta - 90) * Math.PI) / 180;
        const color = method === 'energy_diff' ? '#ffaa00' : '#00ff9d';

        // 1. 置信度扇形区间 (置信度越低，扇面越宽)
        const fanHalfRad = Math.max(0.04, (1.0 - conf) * 0.35);
        ctx.fillStyle = method === 'energy_diff'
            ? 'rgba(255, 170, 0, 0.15)'
            : 'rgba(0, 255, 157, 0.2)';
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, maxR * 0.95, rad - fanHalfRad, rad + fanHalfRad);
        ctx.closePath();
        ctx.fill();

        // 2. 指向波束主轴
        ctx.strokeStyle = color;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        const px = cx + Math.cos(rad) * maxR * 0.95;
        const py = cy + Math.sin(rad) * maxR * 0.95;
        ctx.lineTo(px, py);
        ctx.stroke();

        // 3. 顶端箭头/目标光斑
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px, py, 5, 0, Math.PI * 2);
        ctx.fill();

        // 4. 指针文字指示
        ctx.font = 'bold 11px monospace';
        ctx.textAlign = theta >= 0 ? 'left' : 'right';
        ctx.fillStyle = color;
        ctx.fillText(`DOA ${theta > 0 ? '+' : ''}${theta.toFixed(1)}° (${Math.round(conf * 100)}%)`, px + (theta >= 0 ? 8 : -8), py - 6);

        ctx.restore();
    }

    drawStereoVUMeters(ctx, w, h) {
        ctx.save();
        const barW = 14;
        const barH = h * 0.5;
        const bottomY = h * 0.72;

        const meters = [
            { label: 'CH0 (L)', x: 18, val: this.leftLevel, peak: this.peakLeft },
            { label: 'CH1 (R)', x: w - 32, val: this.rightLevel, peak: this.peakRight },
        ];

        for (const m of meters) {
            // 背景槽
            ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
            ctx.fillRect(m.x, bottomY - barH, barW, barH);
            ctx.strokeStyle = 'rgba(0, 243, 255, 0.2)';
            ctx.lineWidth = 1;
            ctx.strokeRect(m.x, bottomY - barH, barW, barH);

            // 填充柱 (分段色阶：绿 -> 橙 -> 红)
            const filledH = Math.min(barH, Math.max(0, m.val * barH));
            const grad = ctx.createLinearGradient(0, bottomY, 0, bottomY - barH);
            grad.addColorStop(0.0, '#00ff9d');
            grad.addColorStop(0.7, '#ffaa00');
            grad.addColorStop(1.0, '#ff3344');

            ctx.fillStyle = grad;
            ctx.fillRect(m.x + 1, bottomY - filledH, barW - 2, filledH);

            // Peak Hold 线
            const peakY = bottomY - Math.min(barH, m.peak * barH);
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(m.x, peakY);
            ctx.lineTo(m.x + barW, peakY);
            ctx.stroke();

            // 标签
            ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(m.label, m.x + barW / 2, bottomY + 14);
        }

        ctx.restore();
    }

    drawTelemetryOverlay(ctx, w, h) {
        ctx.save();
        const audio = this.telemetry?.audio || {};
        const method = audio.method || 'IDLE';
        const isDegraded = method === 'energy_diff';
        const rms = Number(audio.energy_rms || 0).toFixed(3);
        const theta = Number(audio.theta_deg || 0).toFixed(1);
        const side = String(audio.side || 'NONE').toUpperCase();

        // 顶部声学状态指示牌
        ctx.fillStyle = 'rgba(10, 14, 20, 0.8)';
        ctx.fillRect(w / 2 - 120, 12, 240, 26);
        ctx.strokeStyle = isDegraded ? '#ffaa00' : 'rgba(0, 243, 255, 0.3)';
        ctx.lineWidth = 1;
        ctx.strokeRect(w / 2 - 120, 12, 240, 26);

        ctx.font = 'bold 11px monospace';
        ctx.textAlign = 'center';
        ctx.fillStyle = isDegraded ? '#ffaa00' : '#00f3ff';
        const statusText = `DOA: ${theta}° [${side}] | ${method.toUpperCase()} | RMS: ${rms}`;
        ctx.fillText(statusText, w / 2, 29);

        ctx.restore();
    }
}
