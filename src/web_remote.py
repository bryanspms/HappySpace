import hmac
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import cv2


PAGE = (Path(__file__).with_name("remote.html")).read_bytes()
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
IMAGES = {
    "/happy-space-logo.png": (ASSET_DIR / "happy-space-logo.png").read_bytes(),
    "/happy-space-icon.png": (ASSET_DIR / "happy-space-icon.png").read_bytes(),
}
COMMANDS = {"live", "calming", "demo-on", "demo-off"}
PREVIEW_MAX_AGE = 5
PREVIEW_MAX_WIDTH = 640


class RemoteState:
    def __init__(self, settings=None):
        self.settings = settings
        self.commands = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.status = {"selection": "live", "demo": False, "updated": 0.0}
        self.frame = None
        self.frame_updated = 0.0

    def update(self, controller):
        with self.lock:
            self.status = {
                "selection": "calming" if controller.is_commercial else "live",
                "demo": controller.demo_enabled,
                "updated": time.monotonic(),
            }

    def snapshot(self):
        with self.lock:
            return {
                "selection": self.status["selection"],
                "demo": self.status["demo"],
                "age_seconds": round(time.monotonic() - self.status["updated"], 1),
            }

    def update_frame(self, frame):
        with self.lock:
            self.frame = frame
            self.frame_updated = time.monotonic()

    def preview_frame(self):
        with self.lock:
            if self.frame is None or time.monotonic() - self.frame_updated > PREVIEW_MAX_AGE:
                return None
            return self.frame.copy()

    def apply_commands(self, controller):
        for _ in range(self.commands.maxsize):
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            if command == "live":
                controller.select_manual(False)
            elif command == "calming":
                controller.select_manual(True)
            elif command == "demo-on":
                controller.set_demo(True)
            elif command == "demo-off":
                controller.set_demo(False)


def read_password(path):
    password = path.read_text(encoding="utf-8").strip()
    if not 12 <= len(password) <= 256 or not all(32 <= ord(c) <= 126 for c in password):
        raise ValueError("Web password must be 12-256 printable ASCII characters.")
    return password


class RemoteServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, password, state):
        super().__init__(address, RemoteHandler)
        self.password = password.encode("utf-8")
        self.state = state


class RemoteHandler(BaseHTTPRequestHandler):
    server: RemoteServer

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, _format, *_args):
        # Never log request targets or credentials.
        return

    def respond(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, code, value):
        self.respond(code, json.dumps(value).encode("utf-8"))

    def authorized(self):
        value = self.headers.get("Authorization", "")
        try:
            supplied = value.removeprefix("Bearer ").encode("utf-8")
        except UnicodeError:
            return False
        return value.startswith("Bearer ") and hmac.compare_digest(
            supplied, self.server.password
        )

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.respond(200, PAGE, "text/html; charset=utf-8")
        elif path in IMAGES:
            self.respond(200, IMAGES[path], "image/png")
        elif path == "/api/status":
            if not self.authorized():
                self.json_response(401, {"error": "Invalid password"})
                return
            self.json_response(200, self.server.state.snapshot())
        elif path == "/api/preview":
            if not self.authorized():
                self.json_response(401, {"error": "Invalid password"})
                return
            frame = self.server.state.preview_frame()
            if frame is None:
                self.json_response(503, {"error": "Preview unavailable or stale"})
                return
            try:
                height, width = frame.shape[:2]
                if width > PREVIEW_MAX_WIDTH:
                    frame = cv2.resize(
                        frame, (PREVIEW_MAX_WIDTH, max(1, round(height * PREVIEW_MAX_WIDTH / width))),
                        interpolation=cv2.INTER_AREA,
                    )
                success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            except cv2.error:
                self.json_response(500, {"error": "Could not encode preview"})
                return
            if not success:
                self.json_response(500, {"error": "Could not encode preview"})
                return
            self.respond(200, encoded.tobytes(), "image/jpeg")
        elif path == "/api/settings":
            if not self.authorized():
                self.json_response(401, {"error": "Invalid password"})
                return
            settings = self.server.state.settings
            if settings is None:
                self.json_response(503, {"error": "Settings unavailable"})
                return
            try:
                choice, _ = settings.snapshot()
                self.json_response(200, {"video": choice, "videos": settings.videos()})
            except (OSError, ValueError) as error:
                self.json_response(500, {"error": str(error)})
        else:
            self.json_response(404, {"error": "Not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in {"/api/command", "/api/settings"}:
            self.json_response(404, {"error": "Not found"})
            return
        if not self.authorized():
            self.json_response(401, {"error": "Invalid password"})
            return
        if self.headers.get_content_type() != "application/json":
            self.json_response(415, {"error": "Expected JSON"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.json_response(400, {"error": "Invalid content length"})
            return
        if not 0 < length <= 4096:
            self.json_response(400, {"error": "Invalid content length"})
            return
        try:
            data = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.json_response(400, {"error": "Invalid JSON"})
            return
        if path == "/api/settings":
            settings = self.server.state.settings
            if settings is None:
                self.json_response(503, {"error": "Settings unavailable"})
                return
            try:
                settings.save(data)
            except ValueError as error:
                self.json_response(400, {"error": str(error)})
                return
            except OSError as error:
                self.json_response(500, {"error": f"Could not save settings: {error}"})
                return
            self.json_response(200, {"saved": True})
            return
        if length > 256:
            self.json_response(400, {"error": "Invalid content length"})
            return
        if (not isinstance(data, dict) or not isinstance(data.get("command"), str)
                or data["command"] not in COMMANDS):
            self.json_response(400, {"error": "Invalid command"})
            return
        try:
            self.server.state.commands.put_nowait(data["command"])
        except queue.Full:
            self.json_response(503, {"error": "Command queue is full"})
            return
        self.json_response(202, {"accepted": True})


class WebRemote:
    def __init__(self, address, password, state):
        self.server = RemoteServer(address, password, state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join()
        self.server.server_close()
