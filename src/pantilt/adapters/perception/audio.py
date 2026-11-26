import time
import queue
import logging
import threading
from dataclasses import dataclass
from typing import Optional
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from pantilt.domain.types import AudioEvent

logger = logging.getLogger("App")


@dataclass(frozen=True)
class SpeechDirection:
    angle_deg: Optional[float]
    delay_s: Optional[float]
    side: str
    confidence: float
    method: str
    voiced_frames: int
    agreeing_frames: int


class AudioPipeline:
    def __init__(self, config_audio, dry_run=False):
        self.config = config_audio
        self.dry_run = dry_run
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
        self.latest_rms = 0.0
        
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
        if self.dry_run:
            logger.info("音频采集与处理管线 (M3) 处于 DRY-RUN 模式。")
            self.running = True
            return True

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
            self.latest_rms = float(rms)
            
            # 2. SED 触发逻辑 (带死区锁存防抖)
            if rms > self.energy_threshold:
                now = time.monotonic()
                if now - self.last_event_time > self.min_event_gap:
                    if block_float.ndim < 2 or block_float.shape[1] < 2:
                        logger.warning("音频采样数据非双通道，无法进行时延测向。")
                        continue
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
                    
    def _gcc_phat(self, ch0, ch1, max_tau, band=None):
        """返回亚采样时延和归一化相关峰。"""
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
        peak_scale = 1.0
        if band is not None:
            frequencies = np.fft.rfftfreq(N_fft, d=1 / self.fs)
            in_band = (frequencies >= band[0]) & (frequencies <= band[1])
            R[~in_band] = 0
            peak_scale = 2 * np.count_nonzero(in_band) / N_fft

        # IFFT 回到时域
        cc = np.fft.irfft(R, n=N_fft)
        
        # 提取有效时延窗口
        max_shift = int(max_tau * self.fs) + 1
        cc_shifted = np.concatenate((cc[-max_shift:], cc[:max_shift+1]))
        
        peak_idx = int(np.argmax(cc_shifted))
        confidence = float(cc_shifted[peak_idx]) / peak_scale
        
        # 抛物线亚采样插值：短基线阵列的最大时延只有几个采样点，
        # 直接用整数 argmax 会把角度量化成台阶（16kHz/6.5cm 下 30° 附近一步跨约 10°）。
        # 用峰值及其左右邻居拟合抛物线，恢复出亚采样精度的时延。
        sub_offset = 0.0
        if 0 < peak_idx < len(cc_shifted) - 1:
            y_prev = cc_shifted[peak_idx - 1]
            y_peak = cc_shifted[peak_idx]
            y_next = cc_shifted[peak_idx + 1]
            denom = y_prev - 2.0 * y_peak + y_next
            if abs(denom) > 1e-12:
                sub_offset = 0.5 * (y_prev - y_next) / denom
                sub_offset = float(np.clip(sub_offset, -0.5, 0.5))
        
        shift = (peak_idx - max_shift) + sub_offset
        return shift / self.fs, confidence

    def _angle_from_delay(self, tau):
        val = tau * self.sound_speed / self.mic_spacing
        return float(np.degrees(np.arcsin(np.clip(val, -1.0, 1.0)))) + self.audio_zero

    @staticmethod
    def _angle_side(theta):
        if theta < -15.0:
            return "left"
        if theta > 15.0:
            return "right"
        return "center"

    @staticmethod
    def _energy_side(ch0, ch1):
        diff = np.sqrt(np.mean(ch0**2)) - np.sqrt(np.mean(ch1**2))
        if diff > 0.005:
            return "left"
        if diff < -0.005:
            return "right"
        return "center"

    def _compute_doa(self, ch0, ch1, max_tau):
        """实现 GCC-PHAT 测向，并在异常时降级为能量差测向"""
        tau, confidence = self._gcc_phat(ch0, ch1, max_tau)
        # --- 降级模式检查 ---
        if confidence < self.gcc_conf_thresh:
            side = self._energy_side(ch0, ch1)
            theta = {"left": -self.fallback_angle, "right": self.fallback_angle, "center": 0.0}[side]
            return theta + self.audio_zero, confidence, "energy_diff", side

        theta = self._angle_from_delay(tau)
        return theta, confidence, "gcc_phat", self._angle_side(theta)

    def estimate_speech_direction(self, stereo):
        """对归一化立体声片段估计方位，保留时延和有效帧数供标定。"""
        frame_size = round(self.fs * 0.064)
        if stereo.ndim != 2 or stereo.shape[1] != 2 or len(stereo) < frame_size:
            return SpeechDirection(None, None, "unknown", 0.0, "insufficient_audio", 0, 0)

        band = (300, 3400)
        frequencies = np.fft.rfftfreq(len(stereo), d=1 / self.fs)
        spectrum = np.fft.rfft(stereo, axis=0)
        spectrum[(frequencies < band[0]) | (frequencies > band[1])] = 0
        speech = np.fft.irfft(spectrum, n=len(stereo), axis=0)
        hop = frame_size // 2
        frames = [speech[start:start + frame_size] for start in range(0, len(speech) - frame_size + 1, hop)]
        levels = np.sqrt(np.mean(np.square(frames), axis=(1, 2)))
        gate = max(0.0004, min(float(np.max(levels)) * 0.30, float(np.quantile(levels, 0.2)) * 2))
        voiced = [frame for frame, level in zip(frames, levels) if level > gate]
        if not voiced:
            return SpeechDirection(None, None, "unknown", 0.0, "no_speech", 0, 0)

        max_tau = self.mic_spacing / self.sound_speed
        estimates = [self._gcc_phat(frame[:, 0], frame[:, 1], max_tau, band) for frame in voiced]
        candidates = [(delay, peak) for delay, peak in estimates
                      if peak >= self.gcc_conf_thresh and abs(delay) <= max_tau + 0.5 / self.fs]
        agreeing = []
        if candidates:
            median_delay = np.median([delay for delay, _ in candidates])
            agreeing = [(delay, peak) for delay, peak in candidates
                        if abs(delay - median_delay) <= 0.5 / self.fs]
        if len(agreeing) >= max(3, (len(voiced) + 1) // 2):
            delay, confidence = np.median(agreeing, axis=0)
            angle = self._angle_from_delay(delay)
            return SpeechDirection(angle, float(delay), self._angle_side(angle), float(confidence),
                                   "gcc_phat", len(voiced), len(agreeing))

        speech_frames = np.concatenate(voiced, axis=0)
        side = self._energy_side(speech_frames[:, 0], speech_frames[:, 1])
        return SpeechDirection(None, None, side if side != "center" else "unknown",
                               float(np.median([peak for _, peak in estimates])),
                               "energy_diff", len(voiced), len(agreeing))
        
    def get_latest_event(self, block=False, timeout=None):
        """主控状态机获取最新拍手事件"""
        try:
            return self.event_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
