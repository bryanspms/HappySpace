import argparse
import json
import sys
from pathlib import Path

import cv2

from src.capture import VideoCapture
from src.controller import DisplayController
from src.detector import CommercialDetector
from src.player import CalmingVideoPlayer


def load_config(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def run(config_path):
    config = load_config(config_path)
    video_path = config_path.parent / config["calming_video_path"]
    capture = VideoCapture(config["capture_device_id"])
    player = None
    try:
        player = CalmingVideoPlayer(
            video_path,
            config.get("timer_font_scale", 1.0),
            config.get("timer_color", [255, 255, 255]),
        )
        controller = DisplayController(CommercialDetector())

        cv2.namedWindow("Happy Space", cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty(
            "Happy Space", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
        )
        print("Live feed active. m: toggle video, d: toggle demo, q: quit.")

        previous_selection = False
        while True:
            ret, live_frame = capture.read_frame()
            if not ret:
                raise RuntimeError("Could not read from the capture device.")

            use_calming_video, remaining = controller.selection(live_frame)
            if use_calming_video != previous_selection:
                if use_calming_video:
                    player.reset()
                    print("Switching to calming video.")
                else:
                    print("Returning to live video.")
                previous_selection = use_calming_video

            frame = player.get_frame(remaining) if use_calming_video else live_frame
            cv2.imshow("Happy Space", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            controller.handle_key(key)
    finally:
        capture.release()
        if player is not None:
            player.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Happy Space video prototype")
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).resolve().with_name("config.json"),
        help="configuration file (video paths are relative to this file)",
    )
    args = parser.parse_args()
    try:
        run(args.config.resolve())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, cv2.error) as error:
        print(f"Happy Space error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
