"""Movement reactions pause actions and reveal the newest task on landing."""
from pathlib import Path
import unittest

from runtime.action_library import load_pet_manifest
from runtime.animation_model import AnimationModel

ROOT = Path(__file__).resolve().parent.parent


class MotionAnimationTests(unittest.TestCase):
    def setUp(self):
        self.model = AnimationModel(load_pet_manifest(ROOT / 'assets' / 'pet-manifest.json'))

    def playback(self):
        m = self.model
        return m.active_clip_name, m.frame_index, m.frame_elapsed_ms

    def manual(self, repeat=True):
        self.assertTrue(self.model.play_manual_action('extra_cube', repeat=repeat))
        self.model.advance(self.model.active_clip.frame_ms * 3 + 7, 100)
        return self.playback()

    def test_drag_throw_and_bounces_resume_manual_at_saved_position(self):
        for repeat in (False, True):
            with self.subTest(repeat=repeat):
                self.setUp()
                saved = self.manual(repeat)
                self.model.play_motion('dragging')
                self.model.play_motion('dragging_release', repeat=False)
                self.model.play_motion('throw_startled')
                duration = len(self.model.active_clip.frames) * self.model.active_clip.frame_ms
                self.model.advance(duration * 3 + 100, 20000)
                self.assertEqual(self.model.active_clip_name, 'throw_startled')
                self.assertFalse(self.model.play_idle_micro())
                self.assertFalse(self.model.play_interaction('head_pat', 20000))
                self.assertFalse(self.model.play_manual_action('extra_dance'))
                self.model.clear_motion()
                self.assertEqual(self.playback(), saved)
                self.assertEqual(self.model.manual_clip_name, 'extra_cube')
                self.assertEqual(self.model.manual_repeat, repeat)
                duration = len(self.model.active_clip.frames) * self.model.active_clip.frame_ms
                self.model.advance(duration, 30000)
                self.assertEqual(self.model.active_clip_name, 'extra_cube' if repeat else self.model.base_clip_name)

    def test_base_animation_resumes_at_saved_position(self):
        self.model.advance(100, 100)
        saved = self.playback()
        self.model.play_motion('throw_startled')
        self.model.advance(1000, 1100)
        self.model.clear_motion()
        self.assertEqual(self.playback(), saved)

    def test_working_updates_keep_manual_action(self):
        saved = self.manual()
        self.model.play_motion('throw_startled')
        self.model.apply_state('WORKING')
        self.assertEqual(self.model.active_clip_name, 'throw_startled')
        self.model.clear_motion()
        self.assertEqual(self.playback(), saved)
        self.assertTrue(self.model.manual_repeat)
        self.assertEqual(self.model.base_state, 'WORKING')

    def test_important_state_replaces_old_manual_on_landing(self):
        for state in ('WAITING', 'SUCCESS', 'ERROR'):
            with self.subTest(state=state):
                self.setUp()
                self.manual()
                self.model.play_motion('throw_startled')
                self.model.apply_state(state)
                self.assertEqual(self.model.active_clip_name, 'throw_startled')
                self.model.clear_motion()
                self.assertEqual(self.model.active_clip_name, self.model.state_map[state])
                self.assertIsNone(self.model.manual_clip_name)
                self.assertFalse(self.model.manual_repeat)

    def test_completion_pulse_survives_motion_and_replaces_manual(self):
        self.manual()
        self.model.play_motion('throw_startled')
        self.model.apply_pulse('SUCCESS', 1000, 100, resume_state='IDLE', complete_clip=False)
        self.assertEqual(self.model.active_clip_name, 'throw_startled')
        self.model.clear_motion()
        self.assertEqual(self.model.active_clip_name, self.model.state_map['SUCCESS'])
        self.assertIsNone(self.model.manual_clip_name)

    def test_expired_pulse_is_not_replayed_after_long_throw(self):
        self.model.apply_pulse('SUCCESS', 1000, 100, resume_state='IDLE', complete_clip=False)
        self.model.play_motion('throw_startled')
        self.model.advance(2000, 2100)
        self.assertEqual(self.model.active_clip_name, 'throw_startled')
        self.model.clear_motion()
        self.assertEqual(self.model.active_clip_name, self.model.state_map['IDLE'])
        self.assertIsNone(self.model.pulse_state)

    def test_placing_without_throw_restores_after_release_animation(self):
        saved = self.manual()
        self.model.play_motion('dragging')
        self.model.play_motion('dragging_release', repeat=False)
        duration = len(self.model.active_clip.frames) * self.model.active_clip.frame_ms
        self.assertEqual(self.model.overlay_remaining_ms, duration)
        self.model.advance(duration, 10000)
        self.assertIsNone(self.model.motion_clip_name)
        self.assertEqual(self.playback(), saved)

    def test_cancel_and_regrab_preserve_action_and_missing_clip_is_safe(self):
        saved = self.manual()
        self.assertFalse(self.model.play_motion('missing_animation'))
        self.assertEqual(self.playback(), saved)
        for _ in range(2):
            self.model.play_motion('throw_startled')
            self.model.advance(1000, 2000)
            self.model.clear_motion()
            self.model.clear_motion()
            self.assertEqual(self.playback(), saved)


if __name__ == '__main__':
    unittest.main()
