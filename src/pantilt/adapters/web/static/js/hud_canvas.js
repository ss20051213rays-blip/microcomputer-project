/**
 * 视口 1: 实况战术 HUD 画布渲染器 (Canvas 2D)
 * 采用 60FPS requestAnimationFrame 驱动，在实况视频上叠加十字准星、死区边界、
 * ArUco/人脸识别框、偏差指示向量及激光安全告警浮层。
 */

export class HUDCanvasRenderer {
    constructor(canvas, videoImg) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.videoImg = videoImg;

        // 逻辑分辨率标准 (OV9281 相机基准 640x400)
        this.baseWidth = 640;
        this.baseHeight = 400;

        // 遥测数据缓存
        this.telemetry = null;
        this.crosshairPulse = 0;
        this.animFrameId = null;

        this.initResize();
        this.startLoop();
    }

    initResize() {
        const resize = () => {
            const rect = this.canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            this.canvas.width = rect.width * dpr;
            this.canvas.height = rect.height * dpr;
            this.scaleX = (rect.width * dpr) / this.baseWidth;
            this.scaleY = (rect.height * dpr) / this.baseHeight;
        };
        window.addEventListener('resize', resize);
        resize();
    }

    updateTelemetry(telemetry) {
        this.telemetry = telemetry;
    }

    startLoop() {
        const render = (timestamp) => {
            this.draw(timestamp);
            this.animFrameId = requestAnimationFrame(render);
        };
        this.animFrameId = requestAnimationFrame(render);
    }

    draw(timestamp) {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        if (!w || !h) return;

        ctx.save();
        ctx.clearRect(0, 0, w, h);

        // 坐标系缩放到 640x400 逻辑空间
        ctx.scale(this.scaleX, this.scaleY);

        const cx = this.baseWidth / 2;
        const cy = this.baseHeight / 2;

        const vision = this.telemetry?.vision || {};
        const laser = this.telemetry?.laser || {};
        const isLocked = Boolean(vision.in_deadzone && vision.target_found);
        const isLaserOn = Boolean(laser.is_on);

        // 1. 绘制死区准星矩形 (Deadzone Box)
        this.drawDeadzone(ctx, cx, cy, isLocked);

        // 2. 绘制中心十字动态瞄准准星
        this.drawCrosshair(ctx, cx, cy, timestamp, isLocked, isLaserOn);

        // 3. 绘制目标识别框与偏差矢量
        if (vision.target_found) {
            this.drawTargetBox(ctx, cx, cy, vision, isLocked);
        }

        // 4. 绘制激光指示警示条 (LOCKED - LASER ACTIVE)
        if (isLaserOn) {
            this.drawLaserActiveBanner(ctx, laser, timestamp);
        }

        // 5. 绘制角落战术装饰角标与四向标尺
        this.drawCornerDecorations(ctx);

        ctx.restore();
    }

    drawDeadzone(ctx, cx, cy, isLocked) {
        const dzX = 30; // 默认死区 px
        const dzY = 25;

        ctx.save();
        ctx.strokeStyle = isLocked ? 'rgba(0, 255, 157, 0.6)' : 'rgba(0, 243, 255, 0.25)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(cx - dzX, cy - dzY, dzX * 2, dzY * 2);

        // 死区微型角标
        ctx.fillStyle = isLocked ? '#00ff9d' : 'rgba(0, 243, 255, 0.4)';
        ctx.font = '9px monospace';
        ctx.fillText('DEADZONE ±30px', cx - dzX, cy + dzY + 12);
        ctx.restore();
    }

    drawCrosshair(ctx, cx, cy, timestamp, isLocked, isLaserOn) {
        ctx.save();
        const mainColor = isLaserOn
            ? '#ff3344'
            : (isLocked ? '#00ff9d' : '#00f3ff');

        ctx.strokeStyle = mainColor;
        ctx.lineWidth = 1.5;

        // 中心圆环
        ctx.beginPath();
        ctx.arc(cx, cy, 18, 0, Math.PI * 2);
        ctx.stroke();

        // 旋转外刻度环
        const rot = (timestamp / 1000) * 0.5;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(rot);
        ctx.strokeStyle = isLaserOn ? 'rgba(255, 51, 68, 0.4)' : 'rgba(0, 243, 255, 0.25)';
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 12]);
        ctx.beginPath();
        ctx.arc(0, 0, 28, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();

        // 十字准星射线 (留出空心中心)
        ctx.beginPath();
        // 水平线
        ctx.moveTo(cx - 36, cy);
        ctx.lineTo(cx - 8, cy);
        ctx.moveTo(cx + 8, cy);
        ctx.lineTo(cx + 36, cy);
        // 垂直线
        ctx.moveTo(cx, cy - 36);
        ctx.lineTo(cx, cy - 8);
        ctx.moveTo(cx, cy + 8);
        ctx.lineTo(cx, cy + 36);
        ctx.stroke();

        // 准星中心微点
        ctx.fillStyle = mainColor;
        ctx.beginPath();
        ctx.arc(cx, cy, 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
    }

    drawTargetBox(ctx, cx, cy, vision, isLocked) {
        const bbox = vision.bbox || [0, 0, 0, 0];
        let [x, y, bw, bh] = bbox;
        if (bw <= 0 || bh <= 0) {
            // 根据偏差估算中心
            const tx = cx + (vision.dx_px || 0);
            const ty = cy + (vision.dy_px || 0);
            bw = 60;
            bh = 60;
            x = tx - bw / 2;
            y = ty - bh / 2;
        }

        const tx = x + bw / 2;
        const ty = y + bh / 2;

        ctx.save();
        const boxColor = isLocked ? '#00ff9d' : '#ffaa00';
        ctx.strokeStyle = boxColor;
        ctx.lineWidth = 2;

        // 1. 绘制战术四角括号
        const bLen = Math.min(14, bw / 3);
        // 左上
        ctx.beginPath();
        ctx.moveTo(x, y + bLen); ctx.lineTo(x, y); ctx.lineTo(x + bLen, y);
        // 右上
        ctx.moveTo(x + bw - bLen, y); ctx.lineTo(x + bw, y); ctx.lineTo(x + bw, y + bLen);
        // 左下
        ctx.beginPath();
        ctx.moveTo(x, y + bh - bLen); ctx.lineTo(x, y + bh); ctx.lineTo(x + bLen, y + bh);
        // 右下
        ctx.moveTo(x + bw - bLen, y + bh); ctx.lineTo(x + bw, y + bh); ctx.lineTo(x + bw, y + bh - bLen);
        ctx.stroke();

        // 2. 目标信息标签
        ctx.fillStyle = boxColor;
        ctx.font = 'bold 11px monospace';
        const typeStr = vision.target_type === 'aruco'
            ? `ARUCO #${vision.target_id >= 0 ? vision.target_id : 12}`
            : (vision.target_type === 'face' ? 'FACE TRACK' : 'TARGET');
        const lockStr = isLocked ? ' [LOCKED]' : '';
        ctx.fillText(`${typeStr}${lockStr}`, x, Math.max(14, y - 6));

        // 3. 偏差引导矢量线 (准星中心 -> 目标中心)
        ctx.strokeStyle = isLocked ? 'rgba(0, 255, 157, 0.4)' : 'rgba(255, 170, 0, 0.7)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(tx, ty);
        ctx.stroke();
        ctx.setLineDash([]);

        // 偏差数值气泡
        const dx = Math.round(vision.dx_px || 0);
        const dy = Math.round(vision.dy_px || 0);
        ctx.fillStyle = 'rgba(10, 14, 20, 0.75)';
        ctx.fillRect((cx + tx) / 2 - 2, (cy + ty) / 2 - 12, 80, 16);
        ctx.fillStyle = boxColor;
        ctx.font = '10px monospace';
        ctx.fillText(`Δ(${dx > 0 ? '+' : ''}${dx}, ${dy > 0 ? '+' : ''}${dy})`, (cx + tx) / 2, (cy + ty) / 2);

        ctx.restore();
    }

    drawLaserActiveBanner(ctx, laser, timestamp) {
        ctx.save();
        const w = this.baseWidth;
        const bannerW = 280;
        const bannerH = 28;
        const bx = (w - bannerW) / 2;
        const by = 16;

        // 呼吸脉动红色高亮
        const alpha = 0.85 + 0.15 * Math.sin(timestamp / 120);
        ctx.fillStyle = `rgba(255, 20, 40, ${alpha * 0.9})`;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;

        // 警示框切角多边形
        ctx.beginPath();
        ctx.moveTo(bx + 10, by);
        ctx.lineTo(bx + bannerW - 10, by);
        ctx.lineTo(bx + bannerW, by + bannerH);
        ctx.lineTo(bx, by + bannerH);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // 警示文字
        const contS = Number(laser.continuous_s || 0).toFixed(1);
        const maxS = Number(laser.max_continuous_s || 10.0).toFixed(1);
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`⚡ [LOCKED - LASER ACTIVE: ${contS}s / ${maxS}s]`, w / 2, by + 18);

        ctx.restore();
    }

    drawCornerDecorations(ctx) {
        ctx.save();
        ctx.strokeStyle = 'rgba(0, 243, 255, 0.3)';
        ctx.lineWidth = 1;

        const w = this.baseWidth;
        const h = this.baseHeight;
        const m = 12;
        const len = 20;

        // 4角战术包围框
        ctx.beginPath();
        ctx.moveTo(m, m + len); ctx.lineTo(m, m); ctx.lineTo(m + len, m);
        ctx.moveTo(w - m - len, m); ctx.lineTo(w - m, m); ctx.lineTo(w - m, m + len);
        ctx.moveTo(m, h - m - len); ctx.lineTo(m, h - m); ctx.lineTo(m + len, h - m);
        ctx.moveTo(w - m - len, h - m); ctx.lineTo(w - m, h - m); ctx.lineTo(w - m, h - m - len);
        ctx.stroke();

        ctx.restore();
    }

    destroy() {
        if (this.animFrameId) {
            cancelAnimationFrame(this.animFrameId);
            this.animFrameId = null;
        }
    }
}
