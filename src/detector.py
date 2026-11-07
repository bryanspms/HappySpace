import math
import time


class CommercialDetector:
    """Simulate a break for testing; this does not analyze the input."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.started_at = time.monotonic()

    def analyze_frame(self, frame):
        elapsed = (time.monotonic() - self.started_at) % 15
        if elapsed < 10:
            return False, None
        return True, math.ceil(15 - elapsed)
