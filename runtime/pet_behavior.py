"""Qt-free desktop interaction geometry and short, bounded idle walks.

Interaction design reference: Baifanyu-For-Win, MIT; see
docs/interaction-reference.md and assets/community-notices/.
All distances here are logical desktop pixels, never physical display pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

try:
    from .pet_motion import Bounds
except ImportError:
    from pet_motion import Bounds


CARING_WORDS = (
    "忙了一会儿，记得伸伸懒腰呀",
    "喝口水吧，我在这儿陪你",
    "慢慢来，我们一件件完成",
    "眼睛也需要休息一小会儿",
    "今天也有在认真生活呢",
    "有我陪着，休息一下也没关系",
)


def nearest_screen_index(point: tuple[int, int], screens: list[tuple[int, int, int, int]]) -> int | None:
    """Choose the nearest logical monitor, including negative origins and DPI gaps."""
    if not screens:
        return None
    x, y = point

    def distance(rect: tuple[int, int, int, int]) -> float:
        left, top, width, height = rect
        dx = max(left - x, 0, x - (left + width - 1))
        dy = max(top - y, 0, y - (top + height - 1))
        return dx * dx + dy * dy

    return min(range(len(screens)), key=lambda index: distance(screens[index]))


def perch_side(x: float, width: float, bounds: Bounds, scale: float = 1) -> str | None:
    """Only deliberate placement near a side edge perches; throws keep bouncing."""
    threshold = min(56 * scale, width * .25)
    left_distance, right_distance = abs(x - bounds.left), abs(x - bounds.right)
    if min(left_distance, right_distance) > threshold:
        return None
    return "left" if left_distance <= right_distance else "right"


def head_crop(original: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Head band measured on Dafeiyu's existing maid animation, in source pixels."""
    x, y, width, height = original
    return round(x + width * .24), round(y + height * .15), round(width * .56), round(height * .52)


@dataclass
class WanderMotion:
    x: float
    y: float
    target_x: float
    bounds: Bounds
    speed: float = 72
    active: bool = True

    def step(self, seconds: float) -> None:
        if not self.active or not math.isfinite(seconds) or seconds <= 0:
            return
        self.target_x, _ = self.bounds.clamp(self.target_x, self.y)
        remaining = self.target_x - self.x
        distance = min(abs(remaining), self.speed * min(.05, seconds))
        self.x, self.y = self.bounds.clamp(self.x + math.copysign(distance, remaining), self.y)
        if abs(self.target_x - self.x) < .5:
            self.x = self.target_x
            self.active = False
