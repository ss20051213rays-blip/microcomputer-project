import threading
import time
import logging
from dataclasses import dataclass

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import mediapipe as mp
except ImportError:
    mp = None

logger = logging.getLogger("App")

@dataclass
class VisionObservation:
    timestamp_mono: float
    face_found: bool
    dx_px: float
    bbox: tuple  # (x, y, w, h)
    confidence: float
    fps: float

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
            
        logger.info(f"Opening camera {self.device_index} with OpenCV backend...")
        self.cap = cv2.VideoCapture(self.device_index)
        
        if not self.cap.isOpened():
            logger.error(f"Failed to open camera /dev/video{self.device_index}!")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True
        
    def _capture_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning("Camera read failed or dropped frame.")
                time.sleep(0.1)
                continue
                
            with self.lock:
                self.latest_frame = frame
                
            time.sleep(1.0 / (self.fps * 2))
                
    def get_latest_frame(self):
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

class FaceDetector:
    def __init__(self, config_camera):
        self.config = config_camera
        self.camera_cx = self.config.get("camera_cx", self.config.get("width", 320) / 2)
        self.min_confidence = self.config.get("min_detection_confidence", 0.5)
        self.detector_type = self.config.get("detector", "mediapipe").lower()
        
        self.mp_face_detection = None
        self.face_detection = None
        self.face_cascade = None
        
        if self.detector_type == "mediapipe":
            if not mp:
                logger.warning("MediaPipe not installed. Falling back to Haar Cascade.")
                self.detector_type = "haar"
            else:
                self.mp_face_detection = mp.solutions.face_detection
                self.face_detection = self.mp_face_detection.FaceDetection(
                    model_selection=0, # 0 for short-range (<2m), 1 for full-range (5m)
                    min_detection_confidence=self.min_confidence
                )
                logger.info("Initialized MediaPipe Face Detection (BlazeFace).")
                
        if self.detector_type == "haar":
            cascade_path = self.config.get("haar_cascade", "haarcascade_frontalface_default.xml")
            # Try to load cascade from cv2 data path
            if cv2:
                full_path = cv2.data.haarcascades + cascade_path
                self.face_cascade = cv2.CascadeClassifier(full_path)
                if self.face_cascade.empty():
                    logger.error(f"Failed to load Haar cascade from {full_path}")
                else:
                    logger.info("Initialized OpenCV Haar Cascade Face Detection.")
            
        self.frames_processed = 0
        self.start_time = time.time()
        self.current_fps = 0.0

    def _update_fps(self):
        self.frames_processed += 1
        now = time.time()
        elapsed = now - self.start_time
        if elapsed > 1.0:
            self.current_fps = self.frames_processed / elapsed
            self.start_time = now
            self.frames_processed = 0

    def process_frame(self, frame) -> VisionObservation:
        self._update_fps()
        now_mono = time.monotonic()
        
        if frame is None:
            return VisionObservation(now_mono, False, 0.0, (0,0,0,0), 0.0, self.current_fps)
            
        h, w, _ = frame.shape
        best_face = None
        
        if self.detector_type == "mediapipe" and self.face_detection:
            # MediaPipe expects RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_detection.process(rgb_frame)
            
            if results.detections:
                # Find face with highest confidence or largest area
                best_det = max(results.detections, key=lambda d: d.score[0])
                bboxC = best_det.location_data.relative_bounding_box
                xmin = int(bboxC.xmin * w)
                ymin = int(bboxC.ymin * h)
                width = int(bboxC.width * w)
                height = int(bboxC.height * h)
                conf = best_det.score[0]
                best_face = (xmin, ymin, width, height, conf)
                
        elif self.detector_type == "haar" and self.face_cascade:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # scaleFactor and minNeighbors tuned for speed
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(30, 30))
            if len(faces) > 0:
                # Pick largest face
                best_rect = max(faces, key=lambda rect: rect[2] * rect[3])
                fx, fy, fw, fh = best_rect
                best_face = (fx, fy, fw, fh, 1.0)
                
        if best_face:
            fx, fy, fw, fh, conf = best_face
            center_x = fx + fw / 2.0
            # 计算像素偏差：左侧为人脸偏左 (dx < 0)，右侧为人脸偏右 (dx > 0)
            dx = center_x - self.camera_cx
            
            return VisionObservation(
                timestamp_mono=now_mono,
                face_found=True,
                dx_px=float(dx),
                bbox=(fx, fy, fw, fh),
                confidence=float(conf),
                fps=self.current_fps
            )
            
        return VisionObservation(now_mono, False, 0.0, (0,0,0,0), 0.0, self.current_fps)

    def close(self):
        if self.face_detection:
            self.face_detection.close()

class VisionPipeline:
    """
    视觉综合管线 (阶段四/五)
    管理相机后台取流线程与人脸检测，提供最新单帧观测 (VisionObservation)。
    支持 dry_run 模式以供脱机状态机模拟。
    """
    def __init__(self, config_camera, dry_run=False):
        self.config = config_camera
        self.dry_run = dry_run
        self.fps = self.config.get("detect_fps", 15)
        
        self.capture = None
        self.detector = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.latest_obs = None
        self._mock_obs = None
        self.last_heartbeat = time.monotonic()
        
    def set_mock_observation(self, obs: VisionObservation):
        """用于脱机测试注入模拟视觉结果"""
        with self.lock:
            self._mock_obs = obs
            
    def start(self):
        if self.dry_run:
            logger.info("视觉管线 (M4) 处于 DRY-RUN 模式。")
            self.running = True
            return True
            
        self.capture = CameraCapture(self.config)
        if not self.capture.start():
            logger.error("启动 CameraCapture 失败。")
            return False
            
        self.detector = FaceDetector(self.config)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("视觉管线 (M4) 已启动。")
        return True
        
    def _loop(self):
        while self.running:
            self.last_heartbeat = time.monotonic()
            frame = self.capture.get_latest_frame()
            if frame is not None:
                obs = self.detector.process_frame(frame)
                with self.lock:
                    self.latest_obs = obs
            else:
                with self.lock:
                    if self.latest_obs is None:
                        self.latest_obs = VisionObservation(
                            timestamp_mono=time.monotonic(),
                            face_found=False,
                            dx_px=0.0,
                            bbox=(0, 0, 0, 0),
                            confidence=0.0,
                            fps=0.0
                        )
            time.sleep(1.0 / (self.fps * 1.5))
            
    def get_latest_observation(self) -> VisionObservation:
        with self.lock:
            if self._mock_obs is not None:
                return self._mock_obs
            return self.latest_obs
            
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        if self.capture:
            self.capture.stop()
            self.capture = None
        if self.detector:
            self.detector.close()
            self.detector = None
        logger.info("视觉管线已停止。")

