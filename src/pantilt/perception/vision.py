import threading
import time
import logging
from dataclasses import dataclass
import numpy as np

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
    dy_px: float = 0.0          # 俯仰垂直偏差 (像素)
    target_id: int = -1         # 检出的目标 ID (如 ArUco 标记 ID)

    @property
    def target_found(self) -> bool:
        """目标存在别名（兼容 ArUco 靶标与人脸）"""
        return self.face_found

class CameraCapture:
    def __init__(self, config_camera):
        self.config = config_camera
        self.width = self.config.get("width", 640)
        self.height = self.config.get("height", 400)
        self.fps = self.config.get("detect_fps", 120)
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

        logger.info(f"Opening camera {self.device_index} with OpenCV backend ({self.width}x{self.height} @ {self.fps}fps)...")
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
                time.sleep(0.01)
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
    """
    视觉目标检测器 (支持 ArUco 工业靶标与人脸检测双模式)
    """
    def __init__(self, config_camera):
        self.config = config_camera
        self.target_mode = self.config.get("target_mode", "aruco").lower()
        self.camera_cx = float(self.config.get("camera_cx", self.config.get("width", 640) / 2))
        self.camera_cy = float(self.config.get("camera_cy", self.config.get("height", 400) / 2))
        self.min_confidence = self.config.get("min_detection_confidence", 0.5)
        self.detector_type = self.config.get("detector", "mediapipe").lower()

        # ArUco 参数初始化
        self.aruco_cfg = self.config.get("aruco", {})
        self.aruco_dict_name = self.aruco_cfg.get("dictionary", "DICT_4X4_50")
        self.target_ids = set(self.aruco_cfg.get("target_ids", [10, 11, 12, 13, 14, 15, 16, 17]))
        self.aruco_detector_bundle = None

        if self.target_mode == "aruco":
            if cv2 and hasattr(cv2, "aruco"):
                dict_attr = getattr(cv2.aruco, self.aruco_dict_name, cv2.aruco.DICT_4X4_50)
                aruco_dict = cv2.aruco.getPredefinedDictionary(dict_attr)
                if hasattr(cv2.aruco, "ArucoDetector"):
                    params = cv2.aruco.DetectorParameters()
                    detector = cv2.aruco.ArucoDetector(aruco_dict, params)
                    self.aruco_detector_bundle = (detector, aruco_dict)
                else:
                    params = cv2.aruco.DetectorParameters_create()
                    self.aruco_detector_bundle = ((aruco_dict, params), aruco_dict)
                logger.info(f"Initialized OpenCV ArUco Detector ({self.aruco_dict_name}, Target IDs={self.target_ids}).")
            else:
                logger.warning("cv2.aruco not available. ArUco detection disabled.")

        # 人脸检测参数初始化
        self.mp_face_detection = None
        self.face_detection = None
        self.face_cascade = None

        if self.target_mode == "face":
            if self.detector_type == "mediapipe":
                if not mp:
                    logger.warning("MediaPipe not installed. Falling back to Haar Cascade.")
                    self.detector_type = "haar"
                else:
                    self.mp_face_detection = mp.solutions.face_detection
                    self.face_detection = self.mp_face_detection.FaceDetection(
                        model_selection=0,
                        min_detection_confidence=self.min_confidence
                    )
                    logger.info("Initialized MediaPipe Face Detection (BlazeFace).")

            if self.detector_type == "haar":
                cascade_path = self.config.get("haar_cascade", "haarcascade_frontalface_default.xml")
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
            return VisionObservation(now_mono, False, 0.0, (0, 0, 0, 0), 0.0, self.current_fps, dy_px=0.0)

        # 兼容单通道灰度图像（如 OV9281 原始单色图）与 BGR 图像
        is_gray = (len(frame.shape) == 2 or frame.shape[2] == 1)
        h = frame.shape[0]
        w = frame.shape[1]

        # ── 模式 1: ArUco 工业靶标高精检测 ──
        if self.target_mode == "aruco" and self.aruco_detector_bundle:
            gray = frame if is_gray else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detector, aruco_dict = self.aruco_detector_bundle
            if hasattr(cv2.aruco, "ArucoDetector"):
                corners, ids, _ = detector.detectMarkers(gray)
            else:
                aruco_dict, params = detector
                corners, ids, _ = cv2.aruco.detectMarkers(gray, aruco_dict, parameters=params)

            if ids is not None and len(ids) > 0:
                for idx, marker_id in enumerate(ids.flatten()):
                    if marker_id in self.target_ids:
                        pts = corners[idx][0]
                        cx = float(np.mean(pts[:, 0]))
                        cy = float(np.mean(pts[:, 1]))
                        dx = cx - self.camera_cx
                        dy = cy - self.camera_cy
                        xmin = int(np.min(pts[:, 0]))
                        ymin = int(np.min(pts[:, 1]))
                        bw = int(np.max(pts[:, 0]) - xmin)
                        bh = int(np.max(pts[:, 1]) - ymin)
                        return VisionObservation(
                            timestamp_mono=now_mono,
                            face_found=True,
                            dx_px=float(dx),
                            bbox=(xmin, ymin, bw, bh),
                            confidence=1.0,
                            fps=self.current_fps,
                            dy_px=float(dy),
                            target_id=int(marker_id)
                        )
            return VisionObservation(now_mono, False, 0.0, (0, 0, 0, 0), 0.0, self.current_fps, dy_px=0.0)

        # ── 模式 2: 人脸检测 ──
        best_face = None
        if self.detector_type == "mediapipe" and self.face_detection:
            rgb_frame = frame if not is_gray else cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            if not is_gray and frame.shape[2] == 3:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_detection.process(rgb_frame)
            if results.detections:
                best_det = max(results.detections, key=lambda d: d.score[0])
                bboxC = best_det.location_data.relative_bounding_box
                xmin = int(bboxC.xmin * w)
                ymin = int(bboxC.ymin * h)
                width = int(bboxC.width * w)
                height = int(bboxC.height * h)
                conf = best_det.score[0]
                best_face = (xmin, ymin, width, height, conf)
        elif self.detector_type == "haar" and self.face_cascade:
            gray = frame if is_gray else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(30, 30))
            if len(faces) > 0:
                best_rect = max(faces, key=lambda rect: rect[2] * rect[3])
                fx, fy, fw, fh = best_rect
                best_face = (fx, fy, fw, fh, 1.0)

        if best_face:
            fx, fy, fw, fh, conf = best_face
            center_x = fx + fw / 2.0
            center_y = fy + fh / 2.0
            dx = center_x - self.camera_cx
            dy = center_y - self.camera_cy
            return VisionObservation(
                timestamp_mono=now_mono,
                face_found=True,
                dx_px=float(dx),
                bbox=(fx, fy, fw, fh),
                confidence=float(conf),
                fps=self.current_fps,
                dy_px=float(dy)
            )

        return VisionObservation(now_mono, False, 0.0, (0, 0, 0, 0), 0.0, self.current_fps, dy_px=0.0)

    def close(self):
        if self.face_detection:
            self.face_detection.close()

class VisionPipeline:
    """
    视觉综合管线 (阶段四/五)
    管理相机后台取流线程与目标检测，提供最新单帧观测 (VisionObservation)。
    支持 dry_run 模式以供脱机状态机模拟。
    """
    def __init__(self, config_camera, dry_run=False):
        self.config = config_camera
        self.dry_run = dry_run
        self.fps = self.config.get("detect_fps", 120)

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
                            fps=0.0,
                            dy_px=0.0
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
