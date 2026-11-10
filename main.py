import argparse
import json
import sys
from pathlib import Path

import cv2

from src.capture import VideoCapture
from src.controller import DisplayController
from src.detector import CommercialDetector
from src.player import CalmingVideoPlayer
from src.settings import VideoSettings
from src.web_remote import RemoteState, WebRemote, read_password


def load_config(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def run(config_path, web_address=None, web_password=None):
    config = load_config(config_path)
    video_path = config_path.parent / config["calming_video_path"]
    settings = VideoSettings(
        Path(__file__).resolve().parent / "assets",
        config_path.parent / ".happyspace-settings" / config_path.name,
    )
    choice, settings_revision = settings.snapshot()
    initial_video = settings.path_for(choice, video_path)
    device_id = config["capture_device_id"]
    if isinstance(device_id, str):
        device_id = config_path.parent / device_id
    capture = VideoCapture(device_id)
    player = None
    remote = None
    try:
        player = CalmingVideoPlayer(
            initial_video,
            config.get("timer_font_scale", 1.0),
            config.get("timer_color", [255, 255, 255]),
        )
        if choice["mode"] == "random":
            player.next_video = lambda: settings.path_for(settings.snapshot()[0], video_path)
        controller = DisplayController(CommercialDetector())

        cv2.namedWindow("Happy Space", cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty(
            "Happy Space", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
        )
        remote_state = None
        if web_address is not None:
            remote_state = RemoteState(settings)
            remote_state.update(controller)
            remote = WebRemote(web_address, web_password, remote_state)
            remote.start()
            print(f"Web remote listening on {web_address[0]}:{remote.server.server_port}.")
        print("Live feed active. m: toggle video, d: toggle demo, q or Esc: quit.")

        previous_selection = False
        while True:
            ret, live_frame = capture.read_frame()
            if not ret:
                raise RuntimeError("Could not read from the capture device.")

            if remote_state is not None:
                remote_state.apply_commands(controller)
            choice, revision = settings.snapshot()
            if revision != settings_revision:
                player.switch(settings.path_for(choice, video_path))
                player.next_video = (
                    lambda: settings.path_for(settings.snapshot()[0], video_path)
                ) if choice["mode"] == "random" else None
                settings_revision = revision
            use_calming_video, remaining = controller.selection(live_frame)
            if remote_state is not None:
                remote_state.update(controller)
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
            if key in (ord("q"), 27):
                break
            controller.handle_key(key)
    finally:
        if remote is not None:
            remote.close()
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
    parser.add_argument("--web", action="store_true", help="enable the local web remote")
    parser.add_argument("--web-bind", default="0.0.0.0", help="web listen address (default: all IPv4 interfaces)")
    parser.add_argument("--web-port", type=int, default=8080, help="web listen port (default: 8080)")
    parser.add_argument("--web-password-file", type=Path, help="file containing the web remote password")
    args = parser.parse_args()
    if args.web and args.web_password_file is None:
        parser.error("--web requires --web-password-file")
    if not 1 <= args.web_port <= 65535:
        parser.error("--web-port must be between 1 and 65535")
    try:
        password = read_password(args.web_password_file) if args.web else None
        address = (args.web_bind, args.web_port) if args.web else None
        run(args.config.resolve(), address, password)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, cv2.error) as error:
        print(f"Happy Space error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
