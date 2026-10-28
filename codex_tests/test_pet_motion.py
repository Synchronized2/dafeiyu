"""Physics outcomes for gravity and free throws, including saved preferences."""
import math
from pathlib import Path
import tempfile
import unittest

from runtime.layout_store import load_layout, normalise_layout, save_layout
from runtime.pet_motion import Bounds, ThrowMotion


class ThrowPhysicsTests(unittest.TestCase):
    def test_gravity_stays_enabled_for_existing_layouts_and_invalid_values(self):
        for value in ({}, {'gravityEnabled': None}, {'gravityEnabled': 'false'}, {'gravityEnabled': 0}):
            self.assertTrue(normalise_layout(value)['gravityEnabled'])
        self.assertTrue(ThrowMotion(100, 100, 0, 0, Bounds(0, 0, 500, 500)).gravity_enabled)

    def test_gravity_preference_survives_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'layout.json'
            for enabled in (False, True):
                save_layout(path, {'gravityEnabled': enabled})
                self.assertIs(load_layout(path)['gravityEnabled'], enabled)

    def test_horizontal_free_throw_does_not_fall_and_stops_in_midair(self):
        motion = ThrowMotion(200, 200, 420, 0, Bounds(0, 0, 10000, 10000), gravity_enabled=False)
        for _ in range(600):
            motion.step(.016)
            self.assertEqual(motion.y, 200)
            if not motion.active:
                break
        self.assertFalse(motion.active)
        self.assertGreater(motion.x, 200)
        self.assertEqual((motion.vx, motion.vy), (0, 0))
        self.assertLess(motion.elapsed, 8)

    def test_free_throw_keeps_direction_and_damps_both_axes(self):
        motion = ThrowMotion(500, 500, 600, -300, Bounds(0, 0, 10000, 10000), gravity_enabled=False)
        for _ in range(30):
            previous_speed = math.hypot(motion.vx, motion.vy)
            motion.step(.016)
            self.assertAlmostEqual(motion.vx / motion.vy, -2)
            self.assertLess(math.hypot(motion.vx, motion.vy), previous_speed)
        self.assertLess(motion.y, 500)

    def test_free_throw_bounces_on_every_edge_even_at_low_speed(self):
        cases = [(1, 150, -100, 0, 'vx', 1), (299, 150, 100, 0, 'vx', -1),
                 (150, 1, 0, -50, 'vy', 1), (150, 299, 0, 50, 'vy', -1)]
        for x, y, vx, vy, axis, sign in cases:
            with self.subTest(axis=axis, sign=sign):
                motion = ThrowMotion(x, y, vx, vy, Bounds(0, 0, 300, 300), gravity_enabled=False)
                motion.step(.05)
                self.assertGreater(getattr(motion, axis) * sign, 0)
                for _ in range(600):
                    motion.step(.016)
                    self.assertTrue(0 <= motion.x <= 300 and 0 <= motion.y <= 300)
                self.assertFalse(motion.active)

    def test_gravity_throw_falls_and_settles_on_floor(self):
        motion = ThrowMotion(300, 200, 500, -400, Bounds(0, 0, 1000, 800))
        for _ in range(600):
            motion.step(.016)
            if not motion.active:
                break
        self.assertFalse(motion.active)
        self.assertEqual(motion.y, 800)
        self.assertEqual((motion.vx, motion.vy), (0, 0))

    def test_free_throw_does_not_jump_after_desktop_suspend(self):
        motion = ThrowMotion(500, 500, 200, 200, Bounds(0, 0, 10000, 10000), gravity_enabled=False)
        motion.step(120)
        self.assertLess(motion.x - 500, 11)
        self.assertLess(motion.y - 500, 11)


if __name__ == '__main__':
    unittest.main()
