import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.controller import DisplayController
from src.settings import VideoSettings
from src.web_remote import RemoteState, WebRemote, read_password


PASSWORD = "a-strong-password"


class WebRemoteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        assets = root / "assets"
        assets.mkdir()
        (assets / "fireplace.mp4").write_bytes(b"video")
        self.settings = VideoSettings(assets, root / "settings.json")
        self.state = RemoteState(self.settings)
        self.controller = DisplayController(Mock())
        self.state.update(self.controller)
        self.remote = WebRemote(("127.0.0.1", 0), PASSWORD, self.state)
        self.remote.start()
        self.addCleanup(self.remote.close)
        self.port = self.remote.server.server_port

    def request(self, method, path, body=None, password=PASSWORD, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = dict(headers or {})
        if password is not None:
            request_headers["Authorization"] = "Bearer " + password
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_page_and_authentication(self):
        status, page = self.request("GET", "/", password=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Happy Space remote", page)
        self.assertEqual(self.request("GET", "/api/status", password=None)[0], 401)
        self.assertEqual(self.request("GET", "/api/status", password="wrong")[0], 401)
        self.assertEqual(self.request("POST", "/api/command", '{"command":"live"}',
                                      password="wrong")[0], 401)
        self.assertTrue(self.state.commands.empty())

    def test_logo_and_icon_are_served_without_exposing_other_assets(self):
        status, page = self.request("GET", "/", password=None)
        self.assertEqual(status, 200)
        self.assertIn(b'/happy-space-logo.png', page)
        self.assertIn(b'/happy-space-icon.png', page)
        for path in ("/happy-space-logo.png", "/happy-space-icon.png"):
            with self.subTest(path=path):
                status, image = self.request("GET", path, password=None)
                self.assertEqual(status, 200)
                self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.request("GET", "/assets/fishtank.mp4", password=None)[0], 404)

    def test_preview_requires_password_and_a_current_frame(self):
        self.assertEqual(self.request("GET", "/api/preview", password=None)[0], 401)
        self.assertEqual(self.request("GET", "/api/preview", password="wrong")[0], 401)
        self.assertEqual(self.request("GET", "/api/preview")[0], 503)
        with patch("src.web_remote.time.monotonic", return_value=100):
            self.state.update_frame(np.full((720, 1280, 3), (10, 80, 200), dtype=np.uint8))
            code, data = self.request("GET", "/api/preview")
        self.assertEqual(code, 200)
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape, (360, 640, 3))
        np.testing.assert_allclose(image[0, 0], [10, 80, 200], atol=3)
        with patch("src.web_remote.time.monotonic", return_value=106):
            self.assertEqual(self.request("GET", "/api/preview")[0], 503)

    def test_preview_encoding_failure_is_reported(self):
        self.state.update_frame(np.zeros((10, 10, 3), dtype=np.uint8))
        with patch("src.web_remote.cv2.imencode", return_value=(False, None)):
            code, data = self.request("GET", "/api/preview")
        self.assertEqual(code, 500)
        self.assertEqual(json.loads(data)["error"], "Could not encode preview")

    def test_preview_response_headers(self):
        self.state.update_frame(np.zeros((10, 10, 3), dtype=np.uint8))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", "/api/preview",
                               headers={"Authorization": "Bearer " + PASSWORD})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "image/jpeg")
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertIn("img-src 'self' blob:",
                          response.getheader("Content-Security-Policy"))
            response.read()
        finally:
            connection.close()

    def test_commands_update_controller_and_status(self):
        for command, selection, demo in [
            ("calming", "calming", False),
            ("calming", "calming", False),
            ("demo-on", "live", True),
            ("demo-off", "live", False),
            ("calming", "calming", False),
            ("live", "live", False),
        ]:
            with self.subTest(command=command):
                code, _ = self.request("POST", "/api/command",
                                       json.dumps({"command": command}))
                self.assertEqual(code, 202)
                self.state.apply_commands(self.controller)
                self.state.update(self.controller)
                code, body = self.request("GET", "/api/status")
                state = json.loads(body)
                self.assertEqual(code, 200)
                self.assertEqual(state["selection"], selection)
                self.assertEqual(state["demo"], demo)
                self.assertLess(state["age_seconds"], 5)

    def test_bad_requests_and_full_queue_are_reported(self):
        for body in ['bad json', '{}', '{"command":[]}', '{"command":"quit"}']:
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/command", body)[0], 400)
        self.assertEqual(self.request("POST", "/api/command", "x" * 257)[0], 400)
        self.assertEqual(self.request("POST", "/api/command", "{}",
                                      headers={"Content-Type": "text/plain"})[0], 415)
        for _ in range(self.state.commands.maxsize):
            self.state.commands.put_nowait("live")
        self.assertEqual(self.request("POST", "/api/command",
                                      '{"command":"live"}')[0], 503)

    def test_status_tracks_keyboard_control(self):
        self.controller.handle_key(ord("m"))
        self.state.update(self.controller)
        _, body = self.request("GET", "/api/status")
        self.assertEqual(json.loads(body)["selection"], "calming")

    def test_settings_are_authenticated_and_persisted(self):
        self.assertEqual(self.request("GET", "/api/settings", password=None)[0], 401)
        self.assertEqual(self.request("POST", "/api/settings", '{"mode":"random"}',
                                      password="wrong")[0], 401)
        self.assertFalse(self.settings.settings_path.exists())
        code, data = self.request("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data),
                         {"video": {"mode": "default"}, "videos": ["fireplace.mp4"]})
        code, _ = self.request("POST", "/api/settings", '{"mode":"random"}')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.settings.settings_path.read_text()),
                         {"mode": "random"})
        code, data = self.request("GET", "/api/settings")
        self.assertEqual(json.loads(data)["video"], {"mode": "random"})
        self.assertEqual(self.request("POST", "/api/settings",
                                      '{"mode":"file","file":"../outside.mp4"}')[0], 400)
        self.assertEqual(self.settings.snapshot()[0], {"mode": "random"})


class PasswordTests(unittest.TestCase):
    def test_password_file_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            for value in ("short", "twelve-letters-é", "x" * 257):
                with self.subTest(value=value):
                    path.write_text(value, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_password(path)
            path.write_text(PASSWORD + "\n", encoding="utf-8")
            self.assertEqual(read_password(path), PASSWORD)


if __name__ == "__main__":
    unittest.main()
