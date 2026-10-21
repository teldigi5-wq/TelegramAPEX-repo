import os
import tempfile
import unittest
from pathlib import Path

from desktop_media_paths import contained_media_path, is_in_download_tree, safe_media_filename


class MediaFilesystemSafetyTests(unittest.TestCase):
    def test_removes_windows_and_posix_traversal_from_telegram_names(self):
        for raw in ("../../outside.txt", r"..\\..\\outside.txt", r"C:\\Windows\\outside.txt", "/etc/outside.txt"):
            with self.subTest(filename=raw):
                self.assertEqual(safe_media_filename(raw), "outside.txt")

    def test_rejects_reserved_names_and_invalid_characters(self):
        self.assertEqual(safe_media_filename("CON.txt"), "_CON.txt")
        self.assertEqual(safe_media_filename("lecture<>.mp4"), "lecture__.mp4")
        self.assertEqual(safe_media_filename(".."), "telegram_media.bin")
        self.assertLessEqual(len(safe_media_filename("long" * 100 + ".mp4")), 180)

    def test_preview_and_download_paths_never_escape_configured_directory(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("../../private.txt", r"C:\\Windows\\secret.txt", "lecture.mp4"):
                candidate = contained_media_path(root, "videos", name)
                self.assertTrue(is_in_download_tree(root, candidate))
                self.assertEqual(Path(candidate).parent, Path(root) / "videos")
            with self.assertRaises(ValueError):
                contained_media_path(root, "../", "file.txt")

    def test_rejects_symlinked_downloads_to_private_files(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(root) / "videos").mkdir()
            secret = Path(outside) / "secret.txt"
            secret.write_text("not media")
            symlink = Path(root) / "videos" / "trusted.mp4"
            try:
                symlink.symlink_to(secret)
            except (OSError, NotImplementedError) as error:
                self.skipTest(str(error))
            self.assertFalse(is_in_download_tree(root, str(symlink)))
            with self.assertRaises(ValueError):
                contained_media_path(root, "videos", "trusted.mp4")

    def test_known_good_saved_media_is_still_accessible(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "videos"
            folder.mkdir()
            media = folder / "example.mp4"
            media.write_bytes(b"fixture")
            self.assertEqual(contained_media_path(root, "videos", media.name), str(media))
            self.assertTrue(is_in_download_tree(root, str(media)))


if __name__ == "__main__":
    unittest.main()
