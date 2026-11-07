import json
import os
import random
import tempfile
import threading
from pathlib import Path

import cv2


class VideoSettings:
    def __init__(self, assets_dir, settings_path):
        self.assets_dir = Path(assets_dir).resolve()
        self.settings_path = Path(settings_path)
        self.lock = threading.Lock()
        self.revision = 0
        self.choice = {"mode": "default"}
        try:
            file = self.settings_path.open(encoding="utf-8")
        except FileNotFoundError:
            pass
        else:
            with file:
                self.choice = self.validate(json.load(file))

    def videos(self):
        if not self.assets_dir.is_dir():
            raise ValueError(f"Video folder does not exist: {self.assets_dir}")
        return sorted(
            (path.name for path in self.assets_dir.iterdir()
             if path.suffix.lower() == ".mp4" and path.is_file()
             and path.resolve().parent == self.assets_dir),
            key=str.casefold,
        )

    def validate(self, value):
        if not isinstance(value, dict):
            raise ValueError("Invalid video setting.")
        mode = value.get("mode")
        if mode == "random" and set(value) == {"mode"}:
            if not self.videos():
                raise ValueError("No MP4 videos found in the assets folder.")
            return {"mode": "random"}
        if mode == "file" and set(value) == {"mode", "file"}:
            name = value["file"]
            if not isinstance(name, str) or name not in self.videos():
                raise ValueError("Choose an MP4 file from the assets folder.")
            return {"mode": "file", "file": name}
        raise ValueError("Invalid video setting.")

    def snapshot(self):
        with self.lock:
            return dict(self.choice), self.revision

    def save(self, value):
        with self.lock:
            choice = self.validate(value)
            if choice["mode"] == "file":
                self.check_video(self.assets_dir / choice["file"])
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.settings_path.parent,
                    prefix=".settings-", delete=False
                ) as file:
                    temporary = Path(file.name)
                    json.dump(choice, file)
                    file.write("\n")
                os.replace(temporary, self.settings_path)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            self.choice = choice
            self.revision += 1

    @staticmethod
    def check_video(path):
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ValueError(f"Could not open video: {path.name}")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(f"Could not read video: {path.name}")
        finally:
            capture.release()

    def path_for(self, choice, default_path):
        if choice["mode"] == "default":
            return default_path
        if choice["mode"] == "random":
            videos = self.videos()
            if not videos:
                raise ValueError("No MP4 videos found in the assets folder.")
            return self.assets_dir / random.choice(videos)
        self.validate(choice)
        return self.assets_dir / choice["file"]
