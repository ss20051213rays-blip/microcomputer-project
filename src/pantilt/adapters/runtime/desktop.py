"""显示与识别框同帧的桌面实时画面。"""

from pantilt.adapters.perception.vision import cv2


class DesktopPreview:
    title = "Pan-Tilt Live Camera"

    def __init__(self):
        if cv2 is None:
            raise RuntimeError("桌面预览需要带 HighGUI 的 OpenCV。")
        cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.title, 960, 630)
        self.last_view = None

    def show(self, vision, state="PREVIEW"):
        """画面更新后返回窗口是否仍处于打开状态。"""
        frame, observation = vision.get_latest_detection()
        if frame is not None and observation is not None:
            view = (observation.timestamp_mono, state)
            if view != self.last_view:
                image = frame.copy()
                if image.ndim == 2:
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                if observation.face_found:
                    x, y, width, height = observation.bbox
                    cv2.rectangle(image, (x, y), (x + width, y + height), (40, 220, 40), 2)
                center = (image.shape[1] // 2, image.shape[0] // 2)
                cv2.drawMarker(image, center, (220, 220, 220), cv2.MARKER_CROSS, 16, 1)
                status = "FACE" if observation.face_found else "NO FACE"
                label = f"{state} | {status} | {observation.fps:.1f} FPS"
                cv2.putText(image, label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 240, 240), 1)
                cv2.imshow(self.title, image)
                self.last_view = view
        key = cv2.waitKey(1) & 0xFF
        try:
            visible = cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            visible = False
        return key not in (ord("q"), 27) and visible

    def close(self):
        cv2.destroyAllWindows()
