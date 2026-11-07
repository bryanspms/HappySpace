import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.settings import VideoSettings


class VideoSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.assets = root / "assets"
        self.assets.mkdir()
        (self.assets / "fish.mp4").write_bytes(b"video")
        (self.assets / "fire.MP4").write_bytes(b"video")
        (self.assets / "notes.txt").write_text("not video")
        self.path = root / ".happyspace-settings" / "config.json"
        self.settings = VideoSettings(self.assets, self.path)

    def test_file_list_and_persistence_across_restart(self):
        self.assertEqual(self.settings.videos(), ["fire.MP4", "fish.mp4"])
        self.assertEqual(self.settings.snapshot(), ({"mode": "default"}, 0))
        with patch.object(VideoSettings, "check_video") as check:
            self.settings.save({"mode": "file", "file": "fish.mp4"})
        check.assert_called_once_with(self.assets / "fish.mp4")
        self.assertEqual(json.loads(self.path.read_text()),
                         {"mode": "file", "file": "fish.mp4"})
        restored = VideoSettings(self.assets, self.path)
        self.assertEqual(restored.snapshot()[0], {"mode": "file", "file": "fish.mp4"})
        self.assertEqual(restored.path_for(restored.snapshot()[0], Path("default")),
                         self.assets / "fish.mp4")

    def test_random_selects_from_current_files_at_each_boundary(self):
        self.settings.save({"mode": "random"})
        restored = VideoSettings(self.assets, self.path)
        choice, _ = restored.snapshot()
        with patch("src.settings.random.choice", side_effect=["fish.mp4", "fire.MP4"]):
            self.assertEqual(restored.path_for(choice, None), self.assets / "fish.mp4")
            self.assertEqual(restored.path_for(choice, None), self.assets / "fire.MP4")

    def test_invalid_missing_and_outside_files_rejected(self):
        outside = self.assets.parent / "outside.mp4"
        outside.write_bytes(b"video")
        (self.assets / "link.mp4").symlink_to(outside)
        for value in [
            {"mode": "file", "file": "../outside.mp4"},
            {"mode": "file", "file": "link.mp4"},
            {"mode": "file", "file": "missing.mp4"},
            {"mode": "file", "file": []},
            {"mode": "random", "file": "fish.mp4"},
            {"mode": "unknown"}, [],
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.settings.save(value)
        self.assertFalse(self.path.exists())

    def test_no_videos_and_removed_selection_report_errors(self):
        (self.assets / "fish.mp4").unlink()
        (self.assets / "fire.MP4").unlink()
        with self.assertRaisesRegex(ValueError, "No MP4"):
            self.settings.save({"mode": "random"})
        self.path.parent.mkdir()
        self.path.write_text('{"mode":"file","file":"fish.mp4"}')
        with self.assertRaisesRegex(ValueError, "Choose an MP4"):
            VideoSettings(self.assets, self.path)

    def test_save_failure_does_not_change_live_or_persisted_setting(self):
        self.settings.save({"mode": "random"})
        with patch("src.settings.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.settings.save({"mode": "random"})
        self.assertEqual(self.settings.snapshot(), ({"mode": "random"}, 1))
        self.assertEqual(json.loads(self.path.read_text()), {"mode": "random"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unplayable_file_does_not_save(self):
        with self.assertRaisesRegex(ValueError, "Could not (open|read) video"):
            self.settings.save({"mode": "file", "file": "fish.mp4"})
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
