"""Desktop drag release and screen-edge motion, independent of Qt."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def for_screen(cls, screen: tuple[int, int, int, int], size: tuple[int, int]) -> Bounds:
        x, y, width, height = screen
        return cls(x, y, max(x, x + width - size[0]), max(y, y + height - size[1]))

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        return min(max(x, self.left), self.right), min(max(y, self.top), self.bottom)

    def snap(self, x: float, y: float, distance: float = 24) -> tuple[float, float]:
        x, y = self.clamp(x, y)
        edge_x = min((self.left, self.right), key=lambda edge: abs(x - edge))
        edge_y = min((self.top, self.bottom), key=lambda edge: abs(y - edge))
        return (edge_x if abs(x - edge_x) <= distance else x,
                edge_y if abs(y - edge_y) <= distance else y)


class DragTrail:
    def __init__(self) -> None:
        self.samples: deque[tuple[float, float, float]] = deque(maxlen=40)
        self.last_moved: float | None = None

    def add(self, now: float, x: float, y: float) -> None:
        if self.samples and now <= self.samples[-1][0]:
            return
        if self.samples and (x, y) != self.samples[-1][1:]:
            self.last_moved = now
        self.samples.append((now, x, y))
        while self.samples and now - self.samples[0][0] > .2:
            self.samples.popleft()

    def velocity(self, now: float) -> tuple[float, float]:
        # A pause before release means placing the pet, even after a fast drag.
        if self.last_moved is None or now - self.last_moved >= .15:
            return 0.0, 0.0
        recent = [sample for sample in self.samples if now - sample[0] <= .15]
        if len(recent) < 2:
            return 0.0, 0.0
        first, last = recent[0], recent[-1]
        span = last[0] - first[0]
        if span < .02:
            return 0.0, 0.0
        vx, vy = (last[1] - first[1]) / span, (last[2] - first[2]) / span
        speed = math.hypot(vx, vy)
        if speed < 420:
            return 0.0, 0.0
        factor = min(1.0, 2200 / speed)
        return vx * factor, vy * factor


@dataclass
class ThrowMotion:
    x: float
    y: float
    vx: float
    vy: float
    bounds: Bounds
    elapsed: float = 0.0
    active: bool = True

    def step(self, seconds: float) -> None:
        if not self.active or not math.isfinite(seconds) or seconds <= 0:
            return
        # A suspended desktop must not produce a large off-screen jump.
        dt = min(.05, seconds)
        self.elapsed += dt
        self.vy += 1150 * dt
        self.vx *= math.exp(-.65 * dt)
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x <= self.bounds.left:
            self.x, self.vx = self.bounds.left, abs(self.vx) * .52
        elif self.x >= self.bounds.right:
            self.x, self.vx = self.bounds.right, -abs(self.vx) * .52
        if self.y <= self.bounds.top:
            self.y, self.vy = self.bounds.top, abs(self.vy) * .45
        elif self.y >= self.bounds.bottom:
            self.y = self.bounds.bottom
            self.vy = -abs(self.vy) * .4 if abs(self.vy) > 90 else 0
            self.vx *= math.exp(-7 * dt)
        if (self.y >= self.bounds.bottom and abs(self.vx) < 12 and self.vy == 0) or self.elapsed >= 8:
            self.active = False
            self.vx = self.vy = 0
