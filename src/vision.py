import threading
import time
import logging

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger("App")

class CameraCapture:
    def __init__(self, config_camera):
        self.config = config_camera
        self.width = self.config.get("width", 320)
        self.height = self.config.get("height", 240)
        self.fps = self.config.get("detect_fps", 15)
        self.device_index = self.config.get("device_index", 0)
        
        self.cap = None
        self.running = False
        self.latest_frame = None
        self.lock = threading.Lock()
        self.thread = None
        
    def start(self):
        if not cv2:
            logger.error("cv2 (OpenCV) not installed. Camera stream disabled.")
            return False
            
        logger.info(f"Opening camera {self.device_index} with OpenCV backend (Fallback)...")
        # 若需使用 Picamera2，这里未来可引入并做判断。基础主线先跑通 OpenCV。
        self.cap = cv2.VideoCapture(self.device_index)
        
        if not self.cap.isOpened():
            logger.error(f"Failed to open camera /dev/video{self.device_index}!")
            return False
            
        # 设置分辨率和帧率
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True
        
    def _capture_loop(self):
        """独立取流线程，确保存放在 latest_frame 中的总是最新帧，防积压导致延迟"""
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning("Camera read failed or dropped frame.")
                time.sleep(0.1)
                continue
                
            with self.lock:
                self.latest_frame = frame
                
            # 略微睡眠释放 GIL
            time.sleep(1.0 / (self.fps * 2))
                
    def get_latest_frame(self):
        """主线程调用获取最新帧，丢弃过期旧帧"""
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None
            
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info("Camera stopped.")

