import queue
import logging
try:
    import sounddevice as sd
except ImportError:
    sd = None

logger = logging.getLogger("App")

class AudioCapture:
    def __init__(self, config_audio):
        self.config = config_audio
        self.fs = self.config.get("sample_rate", 16000)
        self.channels = self.config.get("channels", 2)
        self.blocksize = self.config.get("blocksize", 1024)
        self.dtype = self.config.get("dtype", "int16")
        
        # 有界队列，防止主循环消费慢导致内存泄漏
        self.q = queue.Queue(maxsize=10)
        self.stream = None
        
    def _audio_callback(self, indata, frames, time_info, status):
        """音频采集底层的回调，严禁在此做 FFT/重型计算"""
        if status:
            logger.debug(f"Audio status: {status}")
        try:
            # 放入拷贝数据，以防底层 buffer 被复写
            self.q.put_nowait(indata.copy())
        except queue.Full:
            # 队列满时丢弃最旧的数据包
            try:
                self.q.get_nowait()
                self.q.put_nowait(indata.copy())
            except queue.Empty:
                pass
                
    def start(self):
        if not sd:
            logger.error("sounddevice module not found. Audio stream disabled.")
            return False
            
        logger.info(f"Starting audio stream: {self.fs}Hz, {self.channels}ch")
        try:
            self.stream = sd.InputStream(
                samplerate=self.fs,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=self._audio_callback
            )
            self.stream.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            return False
            
    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            logger.info("Audio stream stopped.")
            
    def get_latest_block(self, block=True, timeout=None):
        """主线程调用此方法获取最新音频块"""
        try:
            return self.q.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

