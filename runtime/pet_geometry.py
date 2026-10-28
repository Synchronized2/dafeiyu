"""Keep the character anchored while its status card changes size."""

from __future__ import annotations


def position_window(
    pet_position: tuple[int, int],
    pet_size: tuple[int, int],
    window_size: tuple[int, int],
    screen: tuple[int, int, int, int] | None,
    card_height: int = 0,
    visible_rect: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Return window x/y and pet x/y, clamping the pet only at screen edges.

    Put the card below the pet when there is no room above it. Clamping the
    container must never rewrite a valid character position.
    """
    pet_x, pet_y = pet_position
    pet_width, pet_height = pet_size
    width, height = window_size
    center_offset = (width - pet_width) // 2
    top_offset = height - pet_height - 8
    if screen is None:
        return pet_x - center_offset, pet_y - top_offset, pet_x, pet_y

    left, top, screen_width, screen_height = screen
    vx, vy, vw, vh = visible_rect or (0, 0, pet_width, pet_height)
    pet_x = min(max(pet_x, left - vx), max(left - vx, left + screen_width - vx - vw))
    pet_y = min(max(pet_y, top - vy), max(top - vy, top + screen_height - vy - vh))
    if card_height and pet_y - card_height - 26 < top:
        top_offset = 8
    window_x = min(max(pet_x - center_offset, left - vx),
                   max(left - vx, left + screen_width - width + pet_width - vx - vw))
    window_y = min(max(pet_y - top_offset, top - vy),
                   max(top - vy, top + screen_height - height + pet_height - vy - vh))
    return window_x, window_y, pet_x, pet_y


def bubble_top(pet_y: int, pet_height: int, card_height: int, window_height: int) -> int:
    above = pet_y - card_height - 19
    desired = above if above >= 7 else pet_y + pet_height + 19
    return min(max(desired, 7), max(7, window_height - card_height - 7))


def panel_position(
    size: tuple[int, int],
    screen: tuple[int, int, int, int],
    avoid: tuple[int, int, int, int],
    anchor: tuple[int, int],
) -> tuple[int, int]:
    """Fit a control panel on screen, preferring space beside the pet/card."""
    width, height = size
    left, top, screen_width, screen_height = screen
    ax, ay, aw, ah = avoid
    x, y = anchor
    gap, margin = 12, 8

    def clamp(px: int, py: int) -> tuple[int, int]:
        return (min(max(px, left + margin), max(left + margin, left + screen_width - width - margin)),
                min(max(py, top + margin), max(top + margin, top + screen_height - height - margin)))

    candidates = [clamp(ax - width - gap, y), clamp(ax + aw + gap, y),
                  clamp(x, ay - height - gap), clamp(x, ay + ah + gap), clamp(x, y)]

    def score(point: tuple[int, int]) -> tuple[int, int]:
        px, py = point
        overlap = (max(0, min(px + width, ax + aw) - max(px, ax)) *
                   max(0, min(py + height, ay + ah) - max(py, ay)))
        return overlap, (px - x) ** 2 + (py - y) ** 2

    return min(candidates, key=score)
