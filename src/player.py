import cv2


class CalmingVideoPlayer:
    def __init__(self, video_path, font_scale=1.0, color=(255, 255, 255)):
        self.video_path = video_path
        self.font_scale = font_scale
        self.color = tuple(color)
        self.cap = cv2.VideoCapture(str(video_path))
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"Could not open calming video: {video_path}")

    def reset(self):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def get_frame(self, time_remaining):
        ret, frame = self.cap.read()
        if not ret:
            self.reset()
            ret, frame = self.cap.read()
        if not ret or frame is None:
            self.cap.release()
            self.cap = cv2.VideoCapture(str(self.video_path))
            if not self.cap.isOpened():
                raise RuntimeError(f"Could not reopen calming video: {self.video_path}")
            ret, frame = self.cap.read()
        if not ret or frame is None:
            raise RuntimeError(f"Could not read calming video: {self.video_path}")

        if time_remaining is not None and time_remaining > 0:
            text = f"Live feed in: {time_remaining}s"
            font = cv2.FONT_HERSHEY_SIMPLEX
            thickness = 2
            height, width = frame.shape[:2]
            (text_width, _), _ = cv2.getTextSize(
                text, font, self.font_scale, thickness
            )
            x = max(0, width - text_width - 30)
            y = max(0, height - 30)
            cv2.putText(frame, text, (x + 2, y + 2), font, self.font_scale,
                        (0, 0, 0), thickness + 1, cv2.LINE_AA)
            cv2.putText(frame, text, (x, y), font, self.font_scale,
                        self.color, thickness, cv2.LINE_AA)
        return frame

    def release(self):
        self.cap.release()
