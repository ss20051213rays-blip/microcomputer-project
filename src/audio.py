import time
import queue
import logging
import threading
import numpy as np
from dataclasses import dataclass

try:
    import sounddevice as sd
except ImportError:
    sd = None

logger = logging.getLogger("App")

@dataclass
class AudioEvent:
    timestamp_mono: float
    theta_audio_deg: float
    side: str          # "left", "right", "center"
    confidence: float
    method: str        # "gcc_phat" or "energy_diff"

class AudioPipeline:
    def __init__(self, config_audio):
        self.config = config_audio
        self.fs = self.config.get("sample_rate", 16000)
        self.channels = self.config.get("channels", 2)
        self.blocksize = self.config.get("blocksize", 1024)
        self.dtype = self.config.get("dtype", "int16")
        
        # SED 声音事件检测参数
        self.energy_threshold = self.config.get("energy_threshold", 0.05)
        self.min_event_gap = self.config.get("min_event_gap_ms", 300) / 1000.0
        
        # GCC-PHAT 定位参数
        self.mic_spacing = self.config.get("mic_spacing_m", 0.065)
        self.sound_speed = self.config.get("sound_speed_mps", 343.0)
        self.audio_zero = self.config.get("audio_zero_deg", 0.0)
        self.gcc_conf_thresh = self.config.get("gcc_confidence_threshold", 0.3)
        self.fallback_angle = self.config.get("fallback_angle_deg", 30.0)
        
        # 队列管理
        self.pcm_queue = queue.Queue(maxsize=10)
        self.event_queue = queue.Queue(maxsize=5)
        
        self.stream = None
        self.running = False
        self.process_thread = None
        self.last_event_time = 0.0
        
    def _audio_callback(self, indata, frames, time_info, status):
        """音频硬件采集回调（极轻量），只负责拷贝数据"""
        if status:
            pass # 忽略轻微的 underflow 等
        try:
            self.pcm_queue.put_nowait(indata.copy())
        except queue.Full:
            try:
                self.pcm_queue.get_nowait()
                self.pcm_queue.put_nowait(indata.copy())
            except queue.Empty:
                pass
                
    def start(self):
        if not sd:
            logger.error("sounddevice 模块未安装，无法启动音频流。")
            return False
            
        self.running = True
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()
        
        try:
            self.stream = sd.InputStream(
                samplerate=self.fs,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=self._audio_callback
            )
            self.stream.start()
            logger.info("音频采集与处理管线 (M3) 已启动。")
            return True
        except Exception as e:
            logger.error(f"启动音频流失败: {e}")
            self.running = False
            return False
            
    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.process_thread:
            self.process_thread.join(timeout=1.0)
        logger.info("音频管线已停止。")
        
    def _process_loop(self):
        """音频后台处理线程：计算 RMS -> 阈值触发 -> 计算 GCC-PHAT -> 产生事件"""
        max_tau = self.mic_spacing / self.sound_speed
        
        while self.running:
            try:
                block = self.pcm_queue.get(timeout=0.1)
            except queue.Empty:
                continue
                
            # 1. 计算 RMS (声音能量)
            block_float = block.astype(np.float32) / 32768.0
            rms = np.sqrt(np.mean(block_float**2))
            
            # 2. SED 触发逻辑 (带死区锁存防抖)
            if rms > self.energy_threshold:
                now = time.monotonic()
                if now - self.last_event_time > self.min_event_gap:
                    self.last_event_time = now
                    
                    ch0 = block_float[:, 0]
                    ch1 = block_float[:, 1]
                    
                    # 3. 计算方位角
                    theta, conf, method, side = self._compute_doa(ch0, ch1, max_tau)
                    
                    event = AudioEvent(
                        timestamp_mono=now,
                        theta_audio_deg=theta,
                        side=side,
                        confidence=conf,
                        method=method
                    )
                    
                    try:
                        self.event_queue.put_nowait(event)
                    except queue.Full:
                        pass
                        
                    logger.debug(f"[Audio Trigger] {side} {theta:.1f}° (Conf: {conf:.2f}, {method}, RMS: {rms:.3f})")
                    
    def _compute_doa(self, ch0, ch1, max_tau):
        """实现 GCC-PHAT 测向，并在异常时降级为能量差测向"""
        N = len(ch0)
        # 加窗防止频谱泄露
        window = np.hanning(N)
        s0 = ch0 * window
        s1 = ch1 * window
        
        # FFT (补零避免混叠)
        N_fft = 2 * N
        S0 = np.fft.rfft(s0, n=N_fft)
        S1 = np.fft.rfft(s1, n=N_fft)
        
        # 互功率谱
        R = S0 * np.conj(S1)
        mag = np.abs(R)
        mag[mag < 1e-8] = 1e-8
        R /= mag  # PHAT 权重加权
        
        # IFFT 回到时域
        cc = np.fft.irfft(R, n=N_fft)
        
        # 提取有效时延窗口
        max_shift = int(max_tau * self.fs) + 1
        cc_shifted = np.concatenate((cc[-max_shift:], cc[:max_shift+1]))
        
        shift = np.argmax(cc_shifted) - max_shift
        confidence = float(cc_shifted[shift + max_shift])
        
        # --- 降级模式检查 ---
        if confidence < self.gcc_conf_thresh:
            rms0 = np.sqrt(np.mean(ch0**2))
            rms1 = np.sqrt(np.mean(ch1**2))
            diff = rms0 - rms1
            # 通过能量差判断侧别（极粗糙定位）
            if diff > 0.005:
                side = "left"
                theta = -self.fallback_angle
            elif diff < -0.005:
                side = "right"
                theta = self.fallback_angle
            else:
                side = "center"
                theta = 0.0
            return theta + self.audio_zero, confidence, "energy_diff", side
            
        # --- 正常 GCC-PHAT 模式 ---
        tau = shift / self.fs
        val = tau * self.sound_speed / self.mic_spacing
        
        # 裁剪限制，防止 arcsin 无效域
        val = np.clip(val, -1.0, 1.0)
        theta_rad = np.arcsin(val)
        theta_deg = np.degrees(theta_rad)
        
        # 注意：此处未绝对规定哪边为正，若方向反了请在 default.yaml 修改 audio_zero 或在 app 层适配。
        # 默认假设：左负，右正。
        theta = theta_deg + self.audio_zero
        
        if theta < -15.0:
            side = "left"
        elif theta > 15.0:
            side = "right"
        else:
            side = "center"
            
        return float(theta), confidence, "gcc_phat", side
        
    def get_latest_event(self, block=False, timeout=None):
        """主控状态机获取最新拍手事件"""
        try:
            return self.event_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
