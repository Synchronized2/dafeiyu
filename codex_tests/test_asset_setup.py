"""Check downloaded archives cannot write unexpected files or escape the repo."""
import importlib.util
import io
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fetch_assets", ROOT / "scripts/fetch-assets.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class AssetSetupTests(unittest.TestCase):
    def validate(self, names, expected):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name in names:
                archive.writestr(name, b"frame")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            return fetch.validate_entries(archive, expected)

    def test_accepts_exact_animation_set(self):
        self.assertEqual(len(self.validate(["assets/pet/a.webp", "ASSET_LICENSE.md"],
                                          {"assets/pet/a.webp"})), 1)

    def test_rejects_missing_or_unexpected_frames(self):
        for names in ([], ["assets/pet/b.webp"]):
            with self.assertRaises(ValueError):
                self.validate(names, {"assets/pet/a.webp"})

    def test_rejects_path_traversal_and_absolute_paths(self):
        for name in ("../outside", "/outside", "assets/pet/../../outside", "C:/outside", "assets\\pet\\a.webp"):
            with self.assertRaises(ValueError):
                self.validate([name], set())
