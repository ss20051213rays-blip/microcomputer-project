import threading
import time
import logging
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from pantilt.domain.types import VisionObservation
from pantilt.infrastructure.paths import resolve_path

logger = logging.getLogger("App")

class CameraCapture:
    def __init__(self, config_camera):
        self.config = config_camera
        self.width = self.config.get("width", 640)
        self.height = self.config.get("height", 400)
        self.fps = self.config.get("detect_fps", 120)
        output_fps = float(self.config.get("capture_output_fps", 0))
        self.output_period = 1.0 / output_fps if output_fps > 0 else 0.0
        self.device_index = self.config.get("device_index", 0)

        self.cap = None
        self.running = False
        self.latest_frame = None
        self.latest_frame_mono = None
        self.frame_ready = threading.Condition()
        self.thread = None

    def start(self):
        if not cv2:
            logger.error("cv2 (OpenCV) not installed. Camera stream disabled.")
            return False

        backend_name = str(self.config.get("backend", "opencv")).lower()
        v4l2_backend = getattr(cv2, "CAP_V4L2", None)
        if backend_name in ("v4l2", "linux-v4l2") and v4l2_backend is not None:
            logger.info(f"Opening camera {self.device_index} with V4L2 backend ({self.width}x{self.height} @ {self.fps}fps)...")
            self.cap = cv2.VideoCapture(self.device_index, v4l2_backend)
            if not self.cap.isOpened():
                logger.warning("V4L2 backend could not open camera; falling back to OpenCV auto backend.")
                self.cap.release()
                self.cap = cv2.VideoCapture(self.device_index)
        else:
            logger.info(f"Opening camera {self.device_index} with OpenCV backend ({self.width}x{self.height} @ {self.fps}fps)...")
            self.cap = cv2.VideoCapture(self.device_index)

        if not self.cap.isOpened():
            logger.error(f"Failed to open camera /dev/video{self.device_index}!")
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        if self.output_period > 0 and self.cap.getBackendName() == "V4L2":
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

        self.latest_frame = None
        self.latest_frame_mono = None
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True

    def _capture_loop(self):
        next_output = 0.0
        while self.running:
            if self.output_period > 0:
                ret = self.cap.grab()
                captured_at = time.monotonic()
                if ret and captured_at < next_output:
                    continue
                if ret:
                    ret, frame = self.cap.retrieve()
            else:
                ret, frame = self.cap.read()
                captured_at = time.monotonic()
            if not ret:
                logger.warning("Camera read failed or dropped frame.")
                time.sleep(0.01)
                continue

            frame.setflags(write=False)
            with self.frame_ready:
                self.latest_frame = frame
                self.latest_frame_mono = captured_at
                self.frame_ready.notify_all()

            next_output = captured_at + self.output_period
            if not self.output_period:
                time.sleep(1.0 / (self.fps * 2))

    def get_latest_frame(self):
        return self.get_latest_frame_sample()[0]

    def get_latest_frame_sample(self, *, copy=True):
        """返回同一次实际采集的画面与时间戳。"""
        with self.frame_ready:
            frame, captured_at = self.latest_frame, self.latest_frame_mono
        return (frame.copy() if copy and frame is not None else frame), captured_at

    def wait_for_frame(self, after, timeout=0.2):
        with self.frame_ready:
            if self.frame_ready.wait_for(
                lambda: not self.running or self.latest_frame_mono != after,
                timeout=timeout,
            ) and self.running:
                return self.latest_frame, self.latest_frame_mono
        return None, None

    def stop(self):
        with self.frame_ready:
            self.running = False
            self.frame_ready.notify_all()
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info("Camera stopped.")

class FaceDetector:
    """人脸检测器，默认使用已在 OV9281 灰度画面上验证过的 YuNet。"""
    def __init__(self, config_camera):
        self.config = config_camera
        self.target_mode = self.config.get("target_mode", "face").lower()
        self.camera_cx = float(self.config.get("camera_cx", self.config.get("width", 640) / 2))
        self.camera_cy = float(self.config.get("camera_cy", self.config.get("height", 400) / 2))
        self.min_confidence = float(self.config.get("min_detection_confidence", 0.5))
        self.detector_type = self.config.get("detector", "yunet").lower()
        self.detection_width = int(self.config.get("detection_width", 320))
        self.detection_height = int(self.config.get("detection_height", 200))
        self.smoothing_alpha = float(self.config.get("face_smoothing_alpha", 0.6))
        self.max_target_jump_px = float(self.config.get("face_max_jump_px", 160.0))
        self.target_lost_reset_frames = max(1, int(self.config.get("target_lost_reset_frames", 5)))
        self._target_center = None
        self._lost_frames = 0

        self.aruco_cfg = self.config.get("aruco", {})
        self.aruco_dict_name = self.aruco_cfg.get("dictionary", "DICT_4X4_50")
        self.target_ids = set(self.aruco_cfg.get("target_ids", [10, 11, 12, 13, 14, 15, 16, 17]))
        self.aruco_detector_bundle = None
        if self.target_mode == "aruco" and cv2:
            if hasattr(cv2, "aruco"):
                dict_attr = getattr(cv2.aruco, self.aruco_dict_name, cv2.aruco.DICT_4X4_50)
                aruco_dict = cv2.aruco.getPredefinedDictionary(dict_attr)
                if hasattr(cv2.aruco, "ArucoDetector"):
                    detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
                    self.aruco_detector_bundle = (detector, aruco_dict)
                else:
                    self.aruco_detector_bundle = ((aruco_dict, cv2.aruco.DetectorParameters_create()), aruco_dict)
                logger.info("Initialized OpenCV ArUco detector (%s).", self.aruco_dict_name)
            else:
                logger.warning("cv2.aruco unavailable; ArUco detection disabled.")

        self.mp_face_detection = None
        self.face_detection = None
        self.face_cascade = None
        self.yunet = None
        if self.target_mode == "face":
            if self.detector_type == "yunet":
                model = resolve_path(self.config.get("yunet_model", "assets/models/face_detection_yunet_2023mar.onnx"))
                if cv2 and hasattr(cv2, "FaceDetectorYN") and model.is_file():
                    try:
                        self.yunet = cv2.FaceDetectorYN.create(
                            str(model), "", (self.detection_width, self.detection_height),
                            self.min_confidence,
                            float(self.config.get("yunet_nms_threshold", 0.3)),
                            int(self.config.get("yunet_top_k", 5000)),
                        )
                        logger.info("Initialized YuNet face detector from %s.", model)
                    except Exception as exc:
                        logger.warning("YuNet initialization failed (%s); falling back to Haar.", exc)
                        self.detector_type = "haar"
                else:
                    logger.warning("YuNet/model unavailable; falling back to Haar Cascade.")
                    self.detector_type = "haar"

            if self.detector_type == "mediapipe":
                try:
                    from mediapipe import solutions
                except ImportError:
                    logger.warning("MediaPipe not installed; falling back to Haar Cascade.")
                    self.detector_type = "haar"
                else:
                    self.mp_face_detection = solutions.face_detection
                    self.face_detection = self.mp_face_detection.FaceDetection(
                        model_selection=0, min_detection_confidence=self.min_confidence
                    )
                    logger.info("Initialized MediaPipe Face Detection (BlazeFace).")

            if self.detector_type == "haar" and cv2:
                cascade_path = self.config.get("haar_cascade", "haarcascade_frontalface_default.xml")
                cv2_data = getattr(cv2, "data", None)
                default_path = (cv2_data.haarcascades + cascade_path) if cv2_data else cascade_path
                full_path = str(self.config.get("haar_cascade_path") or default_path)
                self.face_cascade = cv2.CascadeClassifier(full_path)
                if self.face_cascade.empty():
                    logger.error("Failed to load Haar cascade from %s", full_path)
                else:
                    logger.info("Initialized OpenCV Haar Cascade Face Detection.")

        self.frames_processed = 0
        self.start_time = time.monotonic()
        self.current_fps = 0.0

    def _update_fps(self):
        self.frames_processed += 1
        now = time.monotonic()
        elapsed = now - self.start_time
        if elapsed > 1.0:
            self.current_fps = self.frames_processed / elapsed
            self.start_time = now
            self.frames_processed = 0

    def _no_face(self, now_mono):
        self._lost_frames += 1
        if self._lost_frames >= self.target_lost_reset_frames:
            self._target_center = None
        return VisionObservation(now_mono, False, 0.0, (0, 0, 0, 0), 0.0, self.current_fps, dy_px=0.0)

    def _observation_for_candidates(self, candidates, now_mono, frame_width=None, frame_height=None):
        """裁剪越界框，再按最大脸初始化、距离门限续锁并平滑中心。"""
        frame_width = int(frame_width or self.config.get("width", 640))
        frame_height = int(frame_height or self.config.get("height", 400))
        clipped = []
        for x, y, width, height, confidence in candidates:
            x0 = max(0, min(frame_width, int(x)))
            y0 = max(0, min(frame_height, int(y)))
            x1 = max(0, min(frame_width, int(x + width)))
            y1 = max(0, min(frame_height, int(y + height)))
            if x1 > x0 and y1 > y0:
                clipped.append((x0, y0, x1 - x0, y1 - y0, confidence))
        if not clipped:
            return self._no_face(now_mono)

        if self._target_center is None:
            selected = max(clipped, key=lambda item: item[2] * item[3])
        else:
            px, py = self._target_center
            nearby = [item for item in clipped
                      if ((item[0] + item[2] / 2.0 - px) ** 2
                          + (item[1] + item[3] / 2.0 - py) ** 2) ** 0.5 <= self.max_target_jump_px]
            if not nearby:
                return self._no_face(now_mono)
            selected = min(nearby, key=lambda item:
                           (item[0] + item[2] / 2.0 - px) ** 2
                           + (item[1] + item[3] / 2.0 - py) ** 2)

        x, y, width, height, confidence = selected
        raw_center = (x + width / 2.0, y + height / 2.0)
        if self._target_center is None:
            center = raw_center
        else:
            alpha = self.smoothing_alpha
            center = (alpha * raw_center[0] + (1.0 - alpha) * self._target_center[0],
                      alpha * raw_center[1] + (1.0 - alpha) * self._target_center[1])
        self._target_center = center
        self._lost_frames = 0
        return VisionObservation(
            timestamp_mono=now_mono, face_found=True,
            dx_px=float(center[0] - self.camera_cx),
            bbox=(int(x), int(y), int(width), int(height)),
            confidence=float(confidence), fps=self.current_fps,
            dy_px=float(center[1] - self.camera_cy),
        )

    def process_frame(self, frame, captured_at=None) -> VisionObservation:
        self._update_fps()
        now_mono = time.monotonic() if captured_at is None else captured_at

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

        # ── 模式 2: 人脸检测，统一还原到原始帧坐标 ──
        candidates = []
        if self.detector_type == "yunet" and self.yunet:
            detector_frame = cv2.resize(frame, (self.detection_width, self.detection_height))
            if is_gray:
                detector_frame = cv2.cvtColor(detector_frame, cv2.COLOR_GRAY2BGR)
            _, faces = self.yunet.detect(detector_frame)
            if faces is not None:
                scale_x, scale_y = w / self.detection_width, h / self.detection_height
                for face in faces:
                    x, y, fw, fh = face[:4]
                    candidates.append((int(x * scale_x), int(y * scale_y),
                                       int(fw * scale_x), int(fh * scale_y), float(face[14])))
        elif self.detector_type == "mediapipe" and self.face_detection:
            rgb_frame = frame if not is_gray else cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            if not is_gray and frame.shape[2] == 3:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_detection.process(rgb_frame)
            if results.detections:
                for detection in results.detections:
                    box = detection.location_data.relative_bounding_box
                    candidates.append((int(box.xmin * w), int(box.ymin * h),
                                       int(box.width * w), int(box.height * h),
                                       float(detection.score[0])))
        elif self.detector_type == "haar" and self.face_cascade:
            gray = frame if is_gray else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(30, 30))
            candidates.extend((int(x), int(y), int(fw), int(fh), 1.0) for x, y, fw, fh in faces)

        return self._observation_for_candidates(candidates, now_mono, frame_width=w, frame_height=h)

    def close(self):
        if self.face_detection:
            self.face_detection.close()

class VisionPipeline:
    """
    视觉综合管线 (阶段四/五)
    管理相机后台取流线程与目标检测，提供最新单帧观测 (VisionObservation)。
    支持 dry_run 模式以供脱机状态机模拟。
    """
    def __init__(self, config_camera, dry_run=False, start_active=True):
        self.config = config_camera
        self.dry_run = dry_run
        self.inference_fps = float(self.config.get("inference_fps", 0))
        self.idle_inference_fps = float(self.config.get("idle_inference_fps", self.inference_fps))
        self._tracking_active = start_active
        self._inference_wake = threading.Event()

        self.capture = None
        self.detector = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.latest_obs = None
        self.latest_detected_frame = None
        self._mock_obs = None
        self.last_heartbeat = time.monotonic()

    def set_mock_observation(self, obs: VisionObservation):
        """用于脱机测试注入模拟视觉结果"""
        with self.lock:
            self._mock_obs = obs

    def set_tracking_active(self, active):
        if self._tracking_active != active:
            self._tracking_active = active
            self._inference_wake.set()

    def start(self):
        if self.dry_run:
            logger.info("视觉管线 (M4) 处于 DRY-RUN 模式。")
            self.running = True
            return True

        opencv_threads = int(self.config.get("opencv_threads", 0))
        if cv2 is not None and opencv_threads > 0:
            # OpenCV 的线程设置作用于进程，在启动取流和 Web 之前应用。
            cv2.setNumThreads(opencv_threads)

        self.capture = CameraCapture(self.config)
        if not self.capture.start():
            logger.error("启动 CameraCapture 失败。")
            return False

        self.detector = FaceDetector(self.config)
        with self.lock:
            self.latest_obs = None
            self.latest_detected_frame = None
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("视觉管线 (M4) 已启动。")
        return True

    def _loop(self):
        last_capture_mono = None
        last_inference_started = None
        while True:
            self._inference_wake.clear()
            if not self.running:
                break
            now = self.last_heartbeat = time.monotonic()
            fps = self.inference_fps if self._tracking_active else self.idle_inference_fps
            if fps > 0 and last_inference_started is not None:
                delay = last_inference_started + 1.0 / fps - now
                if delay > 0:
                    self._inference_wake.wait(delay)
                    continue

            frame, captured_at = self.capture.wait_for_frame(last_capture_mono)
            if not self.running:
                break
            if frame is not None:
                last_inference_started = time.monotonic()
                obs = self.detector.process_frame(frame, captured_at)
                last_capture_mono = captured_at
                with self.lock:
                    self.latest_obs = obs
                    self.latest_detected_frame = frame
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

    def get_latest_frame(self):
        """获取最新原始图像帧（用于视频推流与本地监视）。"""
        if self.capture:
            return self.capture.get_latest_frame()
        return None

    def get_latest_frame_sample(self):
        """共享只读的最新画面与采集时间，用于视频编码。"""
        capture = self.capture
        return capture.get_latest_frame_sample(copy=False) if capture else (None, None)

    def get_latest_detection(self):
        """本地预览使用同一次推理的图像和识别框。"""
        with self.lock:
            return self.latest_detected_frame, self.latest_obs

    def get_latest_observation(self) -> VisionObservation:
        with self.lock:
            if self._mock_obs is not None:
                return self._mock_obs
            return self.latest_obs

    def stop(self):
        self.running = False
        self._inference_wake.set()
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
