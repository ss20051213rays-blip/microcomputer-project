"""人脸目标选择、跳脸门控与 EMA 平滑测试。"""

import numpy as np

import pantilt.adapters.perception.vision as vision_module
from pantilt.adapters.perception.vision import CameraCapture, FaceDetector, VisionPipeline


def detector(**overrides):
    config = {
        "target_mode": "face",
        "detector": "haar",  # 这些测试直接验证目标管理，不依赖 OpenCV 模型
        "camera_cx": 320,
        "camera_cy": 200,
        "face_smoothing_alpha": 0.5,
        "face_max_jump_px": 100,
        "target_lost_reset_frames": 2,
    }
    config.update(overrides)
    return FaceDetector(config)


def test_camera_capture_uses_configured_v4l2_backend(monkeypatch):
    calls = []

    class FakeCapture:
        def isOpened(self):
            return True

        def set(self, *_args):
            return True

        def read(self):
            return False, None

        def release(self):
            pass

    class FakeCV2:
        CAP_V4L2 = 200
        CAP_PROP_FRAME_WIDTH = 3
        CAP_PROP_FRAME_HEIGHT = 4
        CAP_PROP_FPS = 5

        @staticmethod
        def VideoCapture(*args):
            calls.append(args)
            return FakeCapture()

    monkeypatch.setattr(vision_module, "cv2", FakeCV2)
    camera = CameraCapture({"backend": "v4l2", "device_index": 0})
    assert camera.start()
    camera.stop()
    assert calls == [(0, FakeCV2.CAP_V4L2)]


def test_camera_capture_falls_back_when_v4l2_is_unavailable(monkeypatch):
    calls = []

    class FakeCapture:
        def __init__(self, opened):
            self.opened = opened

        def isOpened(self):
            return self.opened

        def set(self, *_args):
            return True

        def read(self):
            return False, None

        def release(self):
            pass

    class FakeCV2:
        CAP_V4L2 = 200
        CAP_PROP_FRAME_WIDTH = 3
        CAP_PROP_FRAME_HEIGHT = 4
        CAP_PROP_FPS = 5

        @staticmethod
        def VideoCapture(*args):
            calls.append(args)
            return FakeCapture(opened=len(calls) > 1)

    monkeypatch.setattr(vision_module, "cv2", FakeCV2)
    camera = CameraCapture({"backend": "v4l2", "device_index": 0})
    assert camera.start()
    camera.stop()
    assert calls == [(0, FakeCV2.CAP_V4L2), (0,)]


def test_initial_target_is_largest_face_then_tracks_nearest():
    subject = detector()
    first = subject._observation_for_candidates(
        [(50, 50, 30, 30, 0.8), (200, 150, 80, 80, 0.95)], 1.0
    )
    assert first.face_found
    assert first.bbox == (200, 150, 80, 80)
    assert first.dx_px == -80.0

    # 新出现一张面积更大的脸，但原目标更近，避免跳脸。
    second = subject._observation_for_candidates(
        [(205, 150, 80, 80, 0.9), (20, 40, 180, 180, 0.99)], 1.1
    )
    assert second.face_found
    assert second.bbox == (205, 150, 80, 80)
    assert second.dx_px == -77.5  # 原目标中心 240 -> 新中心 245，alpha=0.5


def test_distant_face_is_gated_until_old_target_resets():
    subject = detector()
    subject._observation_for_candidates([(200, 150, 40, 40, 0.9)], 1.0)
    first_miss = subject._observation_for_candidates([(10, 10, 40, 40, 0.9)], 1.1)
    assert not first_miss.face_found
    second_miss = subject._observation_for_candidates([(10, 10, 40, 40, 0.9)], 1.2)
    assert not second_miss.face_found  # 第二次丢失清锁，但本帧不跳到陌生目标
    reacquired = subject._observation_for_candidates([(10, 10, 40, 40, 0.9)], 1.3)
    assert reacquired.face_found


def test_out_of_frame_boxes_are_clipped():
    subject = detector()
    observation = subject._observation_for_candidates([(-12, -5, 158, 159, 0.8)], 1.0)
    assert observation.face_found
    assert observation.bbox == (0, 0, 146, 154)


def test_yunet_processes_small_gray_frame_and_restores_coordinates(monkeypatch):
    class FakeYunet:
        def setInputSize(self, size):
            self.input_size = size

        def detect(self, frame):
            assert frame.shape == (200, 320, 3)
            return 1, np.array([[10, 20, 30, 40] + [0.0] * 10 + [0.95]], dtype=np.float32)

    class FakeFactory:
        @staticmethod
        def create(_model, _config, size, *_args):
            assert size == (320, 200)
            return FakeYunet()

    class FakeCV2:
        FaceDetectorYN = FakeFactory
        COLOR_GRAY2BGR = 1

        @staticmethod
        def cvtColor(frame, _code):
            return np.zeros((*frame.shape, 3), dtype=np.uint8)

        @staticmethod
        def resize(frame, size):
            return np.zeros((size[1], size[0], *frame.shape[2:]), dtype=np.uint8)

    monkeypatch.setattr(vision_module, "cv2", FakeCV2)
    subject = FaceDetector({
        "target_mode": "face", "detector": "yunet",
        "yunet_model": "assets/models/face_detection_yunet_2023mar.onnx",
        "width": 640, "height": 400, "camera_cx": 320, "camera_cy": 200,
        "detection_width": 320, "detection_height": 200,
    })
    observation = subject.process_frame(np.zeros((400, 640), dtype=np.uint8))
    assert observation.face_found
    assert observation.bbox == (20, 40, 60, 80)
    assert abs(observation.confidence - 0.95) < 1e-5


def test_repeated_camera_frame_does_not_refresh_tracking_observation():
    frame = np.zeros((400, 640), dtype=np.uint8)
    pipeline = VisionPipeline({})
    samples = iter([(frame, 1.0), (None, None), (frame, 1.1), (None, None)])
    timestamps = []
    requests = []

    class FakeCamera:
        def wait_for_frame(self, after):
            requests.append(after)
            sample = next(samples)
            if len(timestamps) == 2:
                pipeline.running = False
            return sample

    class FakeDetector:
        def process_frame(self, _frame, captured_at):
            timestamps.append(captured_at)
            return captured_at

    pipeline.capture = FakeCamera()
    pipeline.detector = FakeDetector()
    pipeline.running = True
    pipeline._loop()
    assert timestamps == [1.0, 1.1]
    assert requests == [None, 1.0, 1.0, 1.1]
    assert pipeline.get_latest_observation() == 1.1


def test_capture_returns_new_samples_and_shares_only_read_only_frames():
    camera = CameraCapture({})
    camera.running = True
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    frame.setflags(write=False)
    with camera.frame_ready:
        camera.latest_frame, camera.latest_frame_mono = frame, 2.0
    assert camera.wait_for_frame(1.0, timeout=0)[0] is frame
    assert camera.wait_for_frame(2.0, timeout=0) == (None, None)
    assert camera.get_latest_frame_sample(copy=False)[0] is frame
    writable = camera.get_latest_frame()
    writable[0, 0] = 42
    assert not frame.any()
