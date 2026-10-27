"""Verify enhancement preserves transparency, detail bounds and preferences."""
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from runtime.frame_renderer import render_frame
from runtime.layout_store import load_layout, normalise_layout, save_layout


class FrameRendererTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "frame.png"
        image = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        for x in range(3, 9):
            for y in range(3, 9):
                image.putpixel((x, y), (80, 100, 120, 255 if x > 3 else 96))
        image.save(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_bright_mode_lifts_midtones_without_changing_alpha(self):
        original = render_frame(self.path, "original")
        enhanced = render_frame(self.path, "bright")
        for x in range(12):
            for y in range(12):
                self.assertEqual(original.pixelColor(x, y).alpha(), enhanced.pixelColor(x, y).alpha())
        self.assertGreater(enhanced.pixelColor(6, 6).red(), original.pixelColor(6, 6).red())
        self.assertLess(enhanced.pixelColor(6, 6).red(), 105)

    def test_upscaling_keeps_transparent_padding_and_clean_edges(self):
        image = render_frame(self.path, "natural", 2)
        self.assertEqual((image.width(), image.height()), (24, 24))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(12, 12).alpha(), 255)
        # Premultiplied interpolation must not turn a flat-color edge black.
        for x in range(24):
            pixel = image.pixelColor(x, 12)
            if 40 < pixel.alpha() < 220:
                self.assertGreater(pixel.red(), 65)

    def test_original_mode_retains_native_pixels(self):
        image = render_frame(self.path, "original", 2)
        self.assertEqual(image.width(), 12)
        self.assertEqual(image.pixelColor(6, 6).getRgb(), (80, 100, 120, 255))

    def test_profile_persists_and_invalid_values_fall_back(self):
        path = Path(self.temporary.name) / "layout.json"
        save_layout(path, {"renderProfile": "natural", "scale": 0.8})
        self.assertEqual(load_layout(path)["renderProfile"], "natural")
        self.assertEqual(load_layout(path)["scale"], 0.8)
        self.assertEqual(normalise_layout({"renderProfile": "invalid"})["renderProfile"], "bright")

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            render_frame(self.path, "invalid")
