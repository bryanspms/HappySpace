import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

import main
from src.controller import DisplayController
from src.detector import CommercialDetector
from src.player import CalmingVideoPlayer


class DetectorTests(unittest.TestCase):
    @patch("src.detector.time.monotonic")
    def test_demo_timing_is_independent_of_frame_count(self, clock):
        clock.return_value = 100
        detector = CommercialDetector()
        for now, expected in [
            (100, (False, None)),
            (109.99, (False, None)),
            (110, (True, 10)),
            (115, (True, 5)),
            (119.9, (True, 1)),
            (120, (False, None)),
            (130, (True, 10)),
        ]:
            with self.subTest(now=now):
                clock.return_value = now
                self.assertEqual(detector.analyze_frame(None), expected)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.detector = Mock()
        self.controller = DisplayController(self.detector)

    def test_manual_toggle_has_no_countdown(self):
        self.assertEqual(self.controller.selection(None), (False, None))
        self.controller.handle_key(ord("m"))
        self.assertEqual(self.controller.selection(None), (True, None))
        self.controller.handle_key(ord("m"))
        self.assertEqual(self.controller.selection(None), (False, None))
        self.detector.analyze_frame.assert_not_called()

    def test_demo_can_be_enabled_disabled_and_overridden(self):
        self.detector.analyze_frame.return_value = (True, 3)
        self.controller.handle_key(ord("d"))
        self.detector.reset.assert_called_once()
        self.assertEqual(self.controller.selection("frame"), (True, 3))
        self.controller.handle_key(ord("m"))
        self.assertEqual(self.controller.selection(None), (False, None))
        self.assertFalse(self.controller.demo_enabled)
        self.controller.handle_key(ord("d"))
        self.controller.handle_key(ord("d"))
        self.assertEqual(self.controller.selection(None), (False, None))

    def test_explicit_controls_are_idempotent_and_override_demo(self):
        self.controller.set_demo(True)
        self.controller.set_demo(True)
        self.detector.reset.assert_called_once()
        self.controller.select_manual(True)
        self.assertEqual(self.controller.selection(None), (True, None))
        self.assertFalse(self.controller.demo_enabled)
        self.controller.select_manual(True)
        self.assertEqual(self.controller.selection(None), (True, None))
        self.controller.set_demo(False)
        self.assertEqual(self.controller.selection(None), (True, None))

    @patch("src.controller.time.monotonic")
    def test_timed_playback_duration_and_expiration(self, clock):
        for duration in (30, 60, 90, 120):
            with self.subTest(duration=duration):
                clock.return_value = 100
                self.controller.set_demo(True)
                self.controller.select_timed(duration)
                self.assertFalse(self.controller.demo_enabled)
                self.assertEqual(self.controller.selection(None), (True, duration))
                clock.return_value = 100 + duration - 0.1
                self.assertEqual(self.controller.selection(None), (True, 1))
                clock.return_value = 100 + duration
                self.assertEqual(self.controller.selection(None), (False, None))
                self.assertFalse(self.controller.is_commercial)

    @patch("src.controller.time.monotonic")
    def test_timed_playback_restarts_and_manual_controls_override(self, clock):
        clock.return_value = 100
        self.controller.select_timed(30)
        clock.return_value = 120
        self.controller.select_timed(60)
        self.assertEqual(self.controller.selection(None), (True, 60))
        clock.return_value = 131
        self.assertEqual(self.controller.selection(None), (True, 49))
        self.controller.select_manual(True)
        self.assertEqual(self.controller.selection(None), (True, None))
        clock.return_value = 200
        self.assertEqual(self.controller.selection(None), (True, None))
        self.controller.select_timed(30)
        self.controller.handle_key(ord("m"))
        self.assertEqual(self.controller.selection(None), (False, None))
        self.controller.select_timed(30)
        self.controller.handle_key(ord("d"))
        self.assertTrue(self.controller.demo_enabled)
        self.assertIsNone(self.controller.timed_until)


class PlayerTests(unittest.TestCase):
    @patch("src.player.cv2.VideoCapture")
    def test_repeated_video_endings_loop_same_video(self, video_capture):
        capture = video_capture.return_value
        capture.isOpened.return_value = True
        capture.read.side_effect = [(False, None), (True, "frame"),
                                    (False, None), (True, "frame")]
        player = CalmingVideoPlayer("first.mp4")
        self.assertEqual(player.get_frame(None), "frame")
        self.assertEqual(player.get_frame(None), "frame")
        self.assertEqual(player.video_path, "first.mp4")
        self.assertEqual(capture.set.call_args_list,
                         [call(cv2.CAP_PROP_POS_FRAMES, 0)] * 2)
        video_capture.assert_called_once_with("first.mp4")
        player.release()
        capture.release.assert_called_once()

    @patch("src.player.cv2.VideoCapture")
    def test_failed_switch_preserves_original_capture(self, video_capture):
        first, bad = Mock(), Mock()
        first.isOpened.return_value = True
        bad.isOpened.return_value = False
        video_capture.side_effect = [first, bad]
        player = CalmingVideoPlayer("first.mp4")
        with self.assertRaisesRegex(RuntimeError, "Could not open"):
            player.switch("bad.mp4")
        bad.release.assert_called_once()
        first.release.assert_not_called()
        self.assertEqual(player.video_path, "first.mp4")
        player.release()

    @patch("src.player.cv2.VideoCapture")
    def test_loops_and_releases_video(self, video_capture):
        capture = video_capture.return_value
        capture.isOpened.return_value = True
        capture.read.side_effect = [(False, None), (True, "frame")]
        player = CalmingVideoPlayer("video.mp4")
        self.assertEqual(player.get_frame(None), "frame")
        capture.set.assert_called_once()
        player.release()
        capture.release.assert_called_once()

    @patch("src.player.cv2.VideoCapture")
    def test_unreadable_video_raises_instead_of_showing_placeholder(self, video_capture):
        capture = video_capture.return_value
        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        player = CalmingVideoPlayer("video.mp4")
        with self.assertRaisesRegex(RuntimeError, "Could not read calming video"):
            player.get_frame(None)

    @patch("src.player.cv2.VideoCapture")
    def test_reopens_when_seeking_after_end_of_file_fails(self, video_capture):
        first, reopened = Mock(), Mock()
        first.isOpened.return_value = reopened.isOpened.return_value = True
        first.read.return_value = (False, None)
        reopened.read.return_value = (True, "frame")
        video_capture.side_effect = [first, reopened]
        player = CalmingVideoPlayer("video.mp4")
        self.assertEqual(player.get_frame(None), "frame")
        first.release.assert_called_once()
        player.release()
        reopened.release.assert_called_once()

    @patch("src.player.cv2.VideoCapture")
    def test_open_failure_releases_handle(self, video_capture):
        capture = video_capture.return_value
        capture.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Could not open calming video"):
            CalmingVideoPlayer("missing.mp4")
        capture.release.assert_called_once()


class RandomPlaybackIntegrationTests(unittest.TestCase):
    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", side_effect=[ord("m"), -1, ord("q")])
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("src.player.cv2.VideoCapture")
    @patch("main.VideoCapture")
    def test_random_video_loops_until_break_ends(
        self, capture_type, video_capture, named_window, set_window_property,
        imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        initial, selected = Mock(), Mock()
        initial.isOpened.return_value = selected.isOpened.return_value = True
        selected.read.side_effect = [(False, None), (True, "calm"),
                                     (False, None), (True, "calm")]
        video_capture.side_effect = [initial, selected]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first.mp4", "second.mp4", "sample_input.mp4"):
                (root / name).touch()
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_device_id": 0, "calming_video_path": "."
            }))
            with patch("src.settings.random.choice",
                       side_effect=["first.mp4", "second.mp4"]) as pick:
                main.run(config)
            self.assertEqual(pick.call_count, 2)
            self.assertEqual(video_capture.call_args_list,
                             [call(str(root / "first.mp4")),
                              call(str(root / "second.mp4"))])
            self.assertEqual(selected.set.call_args_list,
                             [call(cv2.CAP_PROP_POS_FRAMES, 0)] * 2)
            self.assertEqual(imshow.call_args_list,
                             [call("Happy Space", "live"),
                              call("Happy Space", "calm"),
                              call("Happy Space", "calm")])

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", side_effect=[ord("m"), ord("q")])
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    def test_explicit_config_video_plays_without_random_selection(
        self, capture_type, player_type, named_window, set_window_property,
        imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixed.MP4").touch()
            (root / "other.mp4").touch()
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_device_id": 0, "calming_video_path": "fixed.MP4"
            }))
            with patch("src.settings.random.choice") as pick:
                main.run(config)
            pick.assert_not_called()
            player_type.assert_called_once_with(root / "fixed.MP4",
                                                1.0, [255, 255, 255])
            player_type.return_value.reset.assert_called_once()
            player_type.return_value.switch.assert_not_called()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", side_effect=[ord("m"), ord("q")])
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    def test_saved_random_overrides_explicit_config_video(
        self, capture_type, player_type, named_window, set_window_property,
        imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("fixed.mp4", "other.mp4"):
                (root / name).touch()
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_device_id": 0, "calming_video_path": str(root / "fixed.mp4")
            }))
            settings_dir = root / ".happyspace-settings"
            settings_dir.mkdir()
            (settings_dir / config.name).write_text('{"mode":"random"}')
            with patch("src.settings.random.choice",
                       side_effect=["fixed.mp4", "other.mp4"]):
                main.run(config)
            player_type.return_value.switch.assert_called_once_with(root / "other.mp4")

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    def test_configured_folder_selects_video_at_each_transition(
        self, capture_type, player_type, named_window, set_window_property,
        imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = root / "my-videos"
            videos.mkdir()
            for name in ("first.mp4", "second.MP4", "sample_input.mp4"):
                (videos / name).touch()
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_device_id": 0, "calming_video_path": "my-videos"
            }))
            player = player_type.return_value
            actions = iter([lambda: ord("m"), lambda: ord("m"),
                            lambda: ord("m"), lambda: ord("q")])
            wait_key.side_effect = lambda _: next(actions)()
            with patch("src.settings.random.choice",
                       side_effect=["first.mp4", "second.MP4",
                                    "first.mp4"]) as pick:
                main.run(config)
            player_type.assert_called_once_with(videos / "first.mp4",
                                                1.0, [255, 255, 255])
            self.assertEqual(player.switch.call_args_list,
                             [call(videos / "second.MP4"),
                              call(videos / "first.mp4")])
            self.assertNotIn("next_video", player.__dict__)
            for args in pick.call_args_list:
                self.assertEqual(args.args[0], ["first.mp4", "second.MP4"])

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", side_effect=[ord("m"), ord("q")])
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    def test_saved_fixed_selection_is_preserved(
        self, capture_type, player_type, named_window, set_window_property,
        imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = root / "videos"
            videos.mkdir()
            (videos / "fixed.mp4").touch()
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_device_id": 0, "calming_video_path": "videos"
            }))
            settings_dir = root / ".happyspace-settings"
            settings_dir.mkdir()
            (settings_dir / config.name).write_text(
                json.dumps({"mode": "file", "file": "fixed.mp4"})
            )
            main.run(config)
            player_type.assert_called_once_with(videos / "fixed.mp4",
                                                1.0, [255, 255, 255])
            player_type.return_value.reset.assert_called_once()
            player_type.return_value.switch.assert_not_called()


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        videos = patch("src.settings.VideoSettings.videos",
                       return_value=["fireplace.mp4", "fishtank.mp4"])
        check_video = patch("src.settings.VideoSettings.check_video")
        videos.start()
        check_video.start()
        self.addCleanup(videos.stop)
        self.addCleanup(check_video.stop)

    @patch("src.controller.time.monotonic")
    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_timed_web_command_shows_countdown_then_returns_to_live(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows, clock,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        player_type.return_value.get_frame.return_value = "calm"
        from src.web_remote import WebRemote
        servers = []

        def make_remote(address, password, state):
            server = WebRemote(address, password, state)
            servers.append(server)
            return server

        def send_timed():
            connection = http.client.HTTPConnection(
                "127.0.0.1", servers[0].server.server_port, timeout=5
            )
            try:
                connection.request("POST", "/api/command",
                                   json.dumps({"command": "timed", "seconds": 30}),
                                   {"Authorization": "Bearer a-strong-password",
                                    "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 202)
                response.read()
            finally:
                connection.close()
            return -1

        def advance(now, key):
            clock.return_value = now
            return key

        clock.return_value = 100
        actions = iter([send_timed, lambda: advance(129.9, -1),
                        lambda: advance(130, -1), lambda: ord("q")])
        wait_key.side_effect = lambda _: next(actions)()
        with patch("main.WebRemote", side_effect=make_remote):
            main.run(Path("/project/config.json"), ("127.0.0.1", 0),
                     "a-strong-password")
        self.assertEqual(imshow.call_args_list, [
            call("Happy Space", "live"), call("Happy Space", "calm"),
            call("Happy Space", "calm"), call("Happy Space", "live"),
        ])
        self.assertEqual(player_type.return_value.get_frame.call_args_list,
                         [call(30), call(1)])

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_preview_follows_displayed_live_and_calming_frames(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        live = np.full((20, 30, 3), (20, 40, 60), dtype=np.uint8)
        calm = np.full((20, 30, 3), (100, 120, 140), dtype=np.uint8)
        capture_type.return_value.read_frame.return_value = (True, live)
        player_type.return_value.get_frame.return_value = calm
        from src.web_remote import WebRemote

        servers = []
        def make_remote(address, password, state):
            server = WebRemote(address, password, state)
            servers.append(server)
            return server

        def check_preview(expected, key):
            connection = http.client.HTTPConnection(
                "127.0.0.1", servers[0].server.server_port, timeout=5
            )
            try:
                connection.request("GET", "/api/preview",
                                   headers={"Authorization": "Bearer a-strong-password"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                image = cv2.imdecode(np.frombuffer(response.read(), dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
                np.testing.assert_allclose(image[0, 0], expected, atol=3)
            finally:
                connection.close()
            return key

        wait_key.side_effect = [
            lambda: check_preview([20, 40, 60], ord("m")),
            lambda: check_preview([100, 120, 140], ord("q")),
        ]
        actions = wait_key.side_effect
        wait_key.side_effect = lambda _: next(actions)()
        with patch("main.WebRemote", side_effect=make_remote):
            main.run(Path("/project/config.json"), ("127.0.0.1", 0),
                     "a-strong-password")

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.WebRemote")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_quit_keys_release_all_resources(
        self, load_config, capture_type, player_type, web_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        for key in (ord("q"), 27):
            with self.subTest(key=key):
                capture_type.reset_mock()
                player_type.reset_mock()
                web_type.reset_mock()
                destroy_windows.reset_mock()
                wait_key.reset_mock()
                wait_key.return_value = key
                capture_type.return_value.read_frame.return_value = (True, "live")
                main.run(Path("/project/config.json"), ("127.0.0.1", 8080),
                         "password12345")
                wait_key.assert_called_once_with(1)
                capture_type.return_value.release.assert_called_once()
                player_type.return_value.release.assert_called_once()
                web_type.return_value.close.assert_called_once()
                destroy_windows.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_remote_setting_is_saved_and_applied_on_next_frame(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        from src.web_remote import WebRemote

        servers = []
        capture_type.return_value.read_frame.return_value = (True, "live")

        def make_remote(address, password, state):
            server = WebRemote(address, password, state)
            servers.append(server)
            return server

        def save_setting():
            connection = http.client.HTTPConnection(
                "127.0.0.1", servers[0].server.server_port, timeout=5
            )
            try:
                connection.request(
                    "POST", "/api/settings",
                    json.dumps({"mode": "file", "file": "fishtank.mp4"}),
                    {"Authorization": "Bearer a-strong-password",
                     "Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
            finally:
                connection.close()
            return -1

        actions = [save_setting, ord("q")]
        wait_key.side_effect = lambda _: actions.pop(0)() if len(actions) == 2 else actions.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            with patch("main.WebRemote", side_effect=make_remote):
                main.run(config, ("127.0.0.1", 0), "a-strong-password")
            setting_path = config.parent / ".happyspace-settings" / config.name
            self.assertEqual(json.loads(setting_path.read_text()),
                             {"mode": "file", "file": "fishtank.mp4"})
        player_type.return_value.switch.assert_called_once_with(
            config.parent / "fishtank.mp4"
        )

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey")
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_web_command_changes_display_on_next_frame(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        player_type.return_value.get_frame.return_value = "calm"
        from src.web_remote import WebRemote

        servers = []

        def make_remote(address, password, state):
            server = WebRemote(address, password, state)
            servers.append(server)
            return server

        def send_command():
            connection = http.client.HTTPConnection(
                "127.0.0.1", servers[0].server.server_port, timeout=5
            )
            try:
                connection.request("POST", "/api/command",
                                   json.dumps({"command": "calming"}),
                                   {"Authorization": "Bearer a-strong-password",
                                    "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 202)
                response.read()
            finally:
                connection.close()
            return -1

        def wait_for_key(_):
            action = wait_key.side_effects.pop(0)
            return action() if callable(action) else action

        wait_key.side_effects = [send_command, ord("q")]
        wait_key.side_effect = wait_for_key
        with patch("main.WebRemote", side_effect=make_remote):
            main.run(Path("/project/config.json"), ("127.0.0.1", 0),
                     "a-strong-password")
        self.assertEqual(imshow.call_args_list,
                         [call("Happy Space", "live"), call("Happy Space", "calm")])
        player_type.return_value.reset.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", return_value=ord("q"))
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.WebRemote")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_web_remote_starts_and_stops_with_application(
        self, load_config, capture_type, player_type, web_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (True, "live")
        main.run(Path("/project/config.json"), ("127.0.0.1", 8080), "password12345")
        web_type.return_value.start.assert_called_once()
        web_type.return_value.close.assert_called_once()
        capture_type.return_value.release.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.WebRemote")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_web_remote_stops_if_capture_fails(
        self, load_config, capture_type, player_type, web_type, named_window,
        set_window_property, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (False, None)
        with self.assertRaisesRegex(RuntimeError, "Could not read from the capture"):
            main.run(Path("/project/config.json"), ("127.0.0.1", 8080),
                     "password12345")
        web_type.return_value.close.assert_called_once()
        capture_type.return_value.release.assert_called_once()
        player_type.return_value.release.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.waitKey", side_effect=[ord("m"), ord("m"), ord("q")])
    @patch("main.cv2.imshow")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config")
    def test_manual_switching_and_cleanup(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, imshow, wait_key, destroy_windows,
    ):
        load_config.return_value = {
            "capture_device_id": 0,
            "calming_video_path": "assets/video.mp4",
        }
        capture = capture_type.return_value
        capture.read_frame.return_value = (True, "live")
        player = player_type.return_value
        player.get_frame.return_value = "calm"

        main.run(Path("/project/config.json"))

        player_type.assert_called_once_with(
            Path("/project/assets/video.mp4"), 1.0, [255, 255, 255]
        )
        self.assertEqual(
            imshow.call_args_list,
            [call("Happy Space", "live"), call("Happy Space", "calm"),
             call("Happy Space", "live")],
        )
        player.get_frame.assert_called_once_with(None)
        player.reset.assert_called_once()
        player.switch.assert_not_called()
        capture.release.assert_called_once()
        player.release.assert_called_once()
        destroy_windows.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.CalmingVideoPlayer", side_effect=RuntimeError("bad video"))
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "missing.mp4"
    })
    def test_capture_is_released_when_player_initialization_fails(
        self, load_config, capture_type, player_type, destroy_windows
    ):
        with self.assertRaisesRegex(RuntimeError, "bad video"):
            main.run(Path("/project/config.json"))
        capture_type.return_value.release.assert_called_once()
        destroy_windows.assert_called_once()

    @patch("main.cv2.destroyAllWindows")
    @patch("main.cv2.setWindowProperty")
    @patch("main.cv2.namedWindow")
    @patch("main.CalmingVideoPlayer")
    @patch("main.VideoCapture")
    @patch("main.load_config", return_value={
        "capture_device_id": 0, "calming_video_path": "video.mp4"
    })
    def test_capture_read_failure_releases_resources(
        self, load_config, capture_type, player_type, named_window,
        set_window_property, destroy_windows,
    ):
        capture_type.return_value.read_frame.return_value = (False, None)
        with self.assertRaisesRegex(RuntimeError, "Could not read from the capture"):
            main.run(Path("/project/config.json"))
        capture_type.return_value.release.assert_called_once()
        player_type.return_value.release.assert_called_once()
        destroy_windows.assert_called_once()


if __name__ == "__main__":
    unittest.main()
