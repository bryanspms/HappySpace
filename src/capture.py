import time

import cv2


class VideoCapture:
    def __init__(self, device_id=0):
        # A path (str or Path) simulates live input with a looping video file.
        self.is_file = not isinstance(device_id, int)
        self.cap = cv2.VideoCapture(str(device_id) if self.is_file else device_id)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"Could not open capture device {device_id!r}.")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
        self._frame_delay = 1.0 / (self.cap.get(cv2.CAP_PROP_FPS) or 30) if self.is_file else 0
        self._next_frame_time = 0.0

    def read_frame(self):
        if not self.is_file:
            return self.cap.read()
        # Pace file playback to its frame rate, like a live source.
        now = time.monotonic()
        if now < self._next_frame_time:
            time.sleep(self._next_frame_time - now)
        self._next_frame_time = max(now, self._next_frame_time) + self._frame_delay
        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
        return ret, frame

    def release(self):
        self.cap.release()
