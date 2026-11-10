import math
import time


class DisplayController:
    """Choose between the live feed and the replacement video."""

    def __init__(self, detector):
        self.detector = detector
        self.demo_enabled = False
        self.is_commercial = False
        self.timed_until = None

    def selection(self, frame):
        if self.timed_until is not None:
            remaining = self.timed_until - time.monotonic()
            if remaining > 0:
                return True, math.ceil(remaining)
            self.timed_until = None
            self.is_commercial = False
        if self.demo_enabled:
            self.is_commercial, remaining = self.detector.analyze_frame(frame)
            return self.is_commercial, remaining
        return self.is_commercial, None

    def select_manual(self, calming):
        self.demo_enabled = False
        self.timed_until = None
        self.is_commercial = calming

    def select_timed(self, seconds):
        self.demo_enabled = False
        self.is_commercial = True
        self.timed_until = time.monotonic() + seconds

    def set_demo(self, enabled):
        if self.demo_enabled == enabled:
            return
        self.demo_enabled = enabled
        self.timed_until = None
        self.is_commercial = False
        if enabled:
            self.detector.reset()

    def handle_key(self, key):
        if key == ord("m"):
            self.select_manual(not self.is_commercial)
        elif key == ord("d"):
            self.set_demo(not self.demo_enabled)
