"""Conservative color enhancement and alpha-safe resampling of pet frames."""
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

PROFILES = {"bright", "natural", "original"}


def render_frame(path: Path, profile: str, factor: float = 1.0) -> QImage:
    if profile not in PROFILES:
        raise ValueError(f"Unknown render profile: {profile}")
    with Image.open(path) as source:
        image = source.convert("RGBA")
    if profile == "original":
        factor = 1.0
    else:
        alpha = image.getchannel("A")
        rgb = image.convert("RGB")
        if profile == "bright":
            # Lift midtones gently; retain black/white endpoints and original alpha.
            lut = [round(255 * (v / 255) ** 0.91) for v in range(256)]
            rgb = rgb.point(lut * 3)
            rgb = ImageEnhance.Color(rgb).enhance(1.04)
        detail = rgb.filter(ImageFilter.UnsharpMask(radius=0.7, percent=65, threshold=3))
        # Never sharpen transparent boundaries or the soft outer shadow.
        interior = alpha.point(lambda v: 255 if v >= 250 else 0)
        image = Image.composite(detail, rgb, interior)
        image.putalpha(alpha)
        factor = max(1.0, min(3.0, factor))
    raw = image.tobytes()
    result = QImage(raw, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()
    if factor != 1.0:
        # Qt's SIMD scaling avoids expensive per-frame Python-side resampling.
        result = result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        result = result.scaled(round(image.width * factor), round(image.height * factor),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return result
