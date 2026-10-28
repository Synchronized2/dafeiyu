"""User-visible geometry, bounds and persistence for desktop interactions."""
import math
from pathlib import Path
import tempfile
import unittest

from runtime.layout_store import load_layout, normalise_layout, save_layout
from runtime.pet_behavior import WanderMotion, head_crop, nearest_screen_index, perch_side, perch_edge, perched_position
from runtime.pet_motion import Bounds
from runtime.pet_geometry import position_window


class DesktopGeometryTests(unittest.TestCase):
    def test_four_edge_detection_and_nearest_corner(self):
        bounds = Bounds(-200, -100, 800, 700)
        for point, expected in (((-195, 200), 'left'), ((795, 200), 'right'),
                                ((300, -95), 'top'), ((300, 695), 'bottom'),
                                ((-190, -98), 'top'), ((-198, -98), 'left')):
            self.assertEqual(perch_edge(*point, (200, 260), bounds), expected)
        self.assertIsNone(perch_edge(300, 300, (200, 260), bounds))
        self.assertIsNone(perch_edge(300, -80, (200, 40), bounds))

    def test_perched_heads_align_to_all_edges_of_negative_monitor(self):
        screen = (-1920, -1080, 1920, 1080)
        visible = (8, 12, 96, 120)
        for side in ('left', 'right', 'top', 'bottom'):
            x, y = perched_position(side, (-1000, -500), visible, screen)
            if side == 'left':
                self.assertEqual(x + visible[0], -1920)
            elif side == 'right':
                self.assertEqual(x + visible[0] + visible[2], 0)
            elif side == 'top':
                self.assertEqual(y + visible[1], -1080)
            else:
                self.assertEqual(y + visible[1] + visible[3], 0)
            self.assertTrue(-1920 <= x + visible[0] <= -visible[2])
            self.assertTrue(-1080 <= y + visible[1] <= -visible[3])

    def test_top_and_bottom_edges_survive_layout_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'layout.json'
            for edge in ('top', 'bottom'):
                save_layout(path, dict(perchedEdge=edge, perchScale=1.37, petX=-500, petY=-50))
                layout = load_layout(path)
                self.assertEqual(layout['perchedEdge'], edge)
                self.assertEqual(layout['perchScale'], 1.37)

    def test_transparent_padding_can_pass_screen_edge_without_clipping_body(self):
        screen = (-1920, 0, 1920, 1080)
        visible = (200, 40, 260, 290)
        for desired, expected in ((-10000, -2120), (10000, -460)):
            wx, wy, px, py = position_window((desired, 300), (640, 360), (690, 460),
                                             screen, 67, visible_rect=visible)
            self.assertEqual(px, expected)
            self.assertTrue(0 <= px - wx <= 50)
            self.assertTrue(0 <= py - wy <= 100)
            self.assertGreaterEqual(px + visible[0], -1920)
            self.assertLessEqual(px + visible[0] + visible[2], 0)

    def test_monitors_left_and_above_primary_keep_negative_coordinates(self):
        screens = [(-1920, 0, 1920, 1080), (0, 0, 1536, 864), (0, -900, 1600, 900)]
        self.assertEqual(nearest_screen_index((-400, 200), screens), 0)
        self.assertEqual(nearest_screen_index((1200, 300), screens), 1)
        self.assertEqual(nearest_screen_index((500, -100), screens), 2)

    def test_mixed_dpi_island_gap_uses_nearest_display(self):
        screens = [(0, 0, 1536, 864), (1920, 0, 1280, 720)]
        self.assertEqual(nearest_screen_index((1800, 300), screens), 1)
        self.assertEqual(nearest_screen_index((1600, 300), screens), 0)
        self.assertIsNone(nearest_screen_index((0, 0), []))

    def test_perching_follows_nearest_side_and_scales_threshold(self):
        bounds = Bounds(-1920, 0, -400, 800)
        self.assertEqual(perch_side(-1910, 400, bounds), 'left')
        self.assertEqual(perch_side(-410, 400, bounds), 'right')
        self.assertIsNone(perch_side(-1000, 400, bounds))
        self.assertIsNone(perch_side(-1890, 80, bounds))
        self.assertEqual(perch_side(-1905, 80, bounds), 'left')

    def test_head_crop_stays_inside_existing_source_art(self):
        x, y, width, height = head_crop((100, 0, 412, 344))
        self.assertTrue(100 <= x < x + width <= 512)
        self.assertTrue(0 <= y < y + height <= 344)
        self.assertLess(height, 344 * .6)

    def test_wander_reaches_target_without_vertical_drift_or_overshoot(self):
        motion = WanderMotion(100, 200, 250, Bounds(0, 0, 400, 600))
        for _ in range(1000):
            motion.step(.016)
            self.assertEqual(motion.y, 200)
            self.assertTrue(100 <= motion.x <= 250)
            if not motion.active:
                break
        self.assertFalse(motion.active)
        self.assertEqual(motion.x, 250)

    def test_wander_is_constrained_after_display_resize(self):
        motion = WanderMotion(100, 200, 900, Bounds(0, 0, 180, 150))
        for _ in range(100):
            motion.step(.05)
        self.assertEqual((motion.x, motion.y), (180, 150))
        self.assertFalse(motion.active)

    def test_wander_does_not_jump_after_suspend_and_ignores_invalid_time(self):
        motion = WanderMotion(100, 200, 500, Bounds(0, 0, 1000, 1000))
        for seconds in (0, -1, math.nan, math.inf):
            motion.step(seconds)
            self.assertEqual(motion.x, 100)
        motion.step(3600)
        self.assertLess(motion.x - 100, 4)

    def test_old_layouts_get_enabled_interactions_and_new_preferences_persist(self):
        layout = normalise_layout({})
        for key in ('perchEnabled', 'hoverEnabled', 'wanderEnabled'):
            self.assertTrue(layout[key])
        layout.update(perchEnabled=False, hoverEnabled=False, wanderEnabled=False,
                      perchedEdge='right', displayName='Secondary display', petX=-400, petY=300)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'layout.json'
            save_layout(path, layout)
            self.assertEqual(load_layout(path), layout)


if __name__ == '__main__':
    unittest.main()
