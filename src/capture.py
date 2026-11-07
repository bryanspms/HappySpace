import cv2


class VideoCapture:
    def __init__(self, device_id=0):
        self.cap = cv2.VideoCapture(device_id)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"Could not open capture device {device_id!r}.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

    def read_frame(self):
        return self.cap.read()

    def release(self):
        self.cap.release()
