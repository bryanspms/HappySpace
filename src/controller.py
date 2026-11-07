class DisplayController:
    """Choose between the live feed and the replacement video."""

    def __init__(self, detector):
        self.detector = detector
        self.demo_enabled = False
        self.is_commercial = False

    def selection(self, frame):
        if self.demo_enabled:
            self.is_commercial, remaining = self.detector.analyze_frame(frame)
            return self.is_commercial, remaining
        return self.is_commercial, None

    def handle_key(self, key):
        if key == ord("m"):
            self.demo_enabled = False
            self.is_commercial = not self.is_commercial
        elif key == ord("d"):
            self.demo_enabled = not self.demo_enabled
            self.is_commercial = False
            if self.demo_enabled:
                self.detector.reset()
