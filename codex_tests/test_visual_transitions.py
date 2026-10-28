"""Verify native Qt clip changes do not composite a second pose."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def probe():
    from PySide6 import QtCore, QtGui, QtWidgets, QtTest
    from runtime import helper
    app_type = QtWidgets.QApplication

    def check():
        app = app_type.instance()
        try:
            window = next(w for w in app.topLevelWidgets() if w.__class__.__name__ == 'CompanionWindow')
            window.animation_timer.stop()
            window.micro_timer.stop()
            from PIL import Image

            def bounds():
                image = window.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
                alpha = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).getchannel('A')
                return alpha.point(lambda a: 255 if a >= 32 else 0).getbbox()

            # High-DPI backing frames must not enlarge or clip the character.
            window.bubble_mode = 'hidden'
            window._sync_bubble_size()
            for scale in (0.6, 1.0, 1.25):
                window._set_preference('scale', scale)
                window._set_preference('render_profile', 'original')
                original_bounds = bounds()
                for profile in ('bright', 'natural'):
                    window._set_preference('render_profile', profile)
                    enhanced_bounds = bounds()
                    if not original_bounds or not enhanced_bounds or any(abs(a-b) > 3 for a,b in zip(original_bounds, enhanced_bounds)):
                        raise AssertionError(f'{scale}/{profile}: pet geometry changed: {original_bounds} -> {enhanced_bounds}')
            window._set_preference('scale', 1.0)
            window.bubble_mode = 'always'
            window._sync_bubble_size()
            from runtime.desktop_controls import PetSettings
            settings = PetSettings(window)
            settings.choices['render_profile'].setCurrentIndex(1)
            if window.render_profile != 'natural':
                raise AssertionError('Settings did not apply the selected image profile')
            settings.choices['render_profile'].setCurrentIndex(0)
            before = window.edge_snap
            settings.toggles['edge_snap'].click()
            if window.edge_snap == before:
                raise AssertionError('Settings checkbox did not apply')
            settings.toggles['edge_snap'].click()
            from runtime.layout_store import load_layout
            saved = load_layout(window.layout_path)
            if saved['renderProfile'] != 'bright' or saved['edgeSnap'] != before:
                raise AssertionError('Settings did not persist')
            gravity_before = window.gravity_enabled
            settings.toggles['gravity_enabled'].click()
            saved_gravity = load_layout(window.layout_path)['gravityEnabled']
            if window.gravity_enabled == gravity_before or saved_gravity != window.gravity_enabled:
                raise AssertionError('Gravity checkbox did not apply and persist')
            settings.close()
            reopened = PetSettings(window)
            if reopened.toggles['gravity_enabled'].isChecked() != saved_gravity:
                raise AssertionError('Reopened settings lost gravity selection')
            reopened.close()
            window._set_preference('gravity_enabled', True)
            for state in ['THINKING', 'WORKING', 'WAITING', 'SUCCESS', 'IDLE']:
                window.apply_message(dict(protocolVersion=1, kind='state', state=state,
                                          message='Transition test', detail=''))
                immediate = window.grab().toImage()
                QtTest.QTest.qWait(180)
                settled = window.grab().toImage()
                if immediate != settled:
                    raise AssertionError(f'{state}: clip change still blends old and new poses')
            # Exercise the actual native drag/throw wiring with deterministic time steps.
            import time
            window._set_reduced_motion(False)
            window.inertia_enabled = True
            window.edge_snap = False

            def stop_timers():
                window.animation_timer.stop()
                window.micro_timer.stop()
                window.motion_timer.stop()

            def playback():
                return window.model.active_clip_name, window.model.frame_index, window.model.frame_elapsed_ms

            def throw():
                window._begin_drag()
                window._finish_drag()
                if not window._start_throw(-1800, -1100):
                    raise AssertionError('Native throw did not start')
                stop_timers()
                if window.model.active_clip_name != 'throw_startled':
                    raise AssertionError('Throw did not switch to startled animation')

            window.model.apply_state('IDLE')
            window.model.play_manual_action('extra_cube', repeat=True)
            window.model.advance(133, window._now_ms())
            saved = playback()
            bounds = window._motion_bounds()
            window._move_to_pet(round(bounds.left + 10), round(bounds.top + 10))
            throw()
            bounced = False
            qa_dir = os.environ.get('DSH_MOTION_QA_DIR')
            if qa_dir:
                Path(qa_dir).mkdir(parents=True, exist_ok=True)
                window.model.advance(400, window._now_ms())
                window.grab().save(str(Path(qa_dir) / 'throw-startled.png'))
            for _ in range(600):
                motion = window.throw_motion
                previous_vx = motion.vx
                window.motion_tick = time.monotonic() - .016
                window._tick_motion()
                bounced = bounced or previous_vx < 0 < motion.vx
                if window.throw_motion is None:
                    break
                window.model.advance(16, window._now_ms())
                if window.model.active_clip_name != 'throw_startled':
                    raise AssertionError('Startled animation ended before the throw settled')
            else:
                raise AssertionError('Throw never settled')
            stop_timers()
            if not bounced or playback() != saved or not window.model.manual_repeat:
                raise AssertionError(f'Bounce/landing did not restore manual action: {saved} -> {playback()}')
            if qa_dir:
                window.grab().save(str(Path(qa_dir) / 'landed-restored.png'))

            # Gravity can change in flight without restarting or teleporting the pet.
            window._move_to_pet(round(bounds.left + 10), round(bounds.top + 10))
            throw()
            motion = window.throw_motion
            snapshot = motion.x, motion.y, motion.vx, motion.vy
            window._set_preference('gravity_enabled', False)
            stop_timers()
            if motion.gravity_enabled or snapshot != (motion.x, motion.y, motion.vx, motion.vy):
                raise AssertionError('Gravity toggle reset the current throw')
            window._set_preference('gravity_enabled', True)
            if not motion.gravity_enabled:
                raise AssertionError('Enabling gravity did not affect the current throw')
            window._stop_throw(landing=False)
            window._set_preference('gravity_enabled', False)
            throw()
            if window.throw_motion.gravity_enabled:
                raise AssertionError('New throw ignored the saved gravity preference')
            bounced = False
            for _ in range(600):
                motion = window.throw_motion
                previous_vx = motion.vx
                window.motion_tick = time.monotonic() - .016
                window._tick_motion()
                bounced = bounced or previous_vx < 0 < motion.vx
                if window.throw_motion is None:
                    break
                window.model.advance(16, window._now_ms())
                if window.model.active_clip_name != 'throw_startled':
                    raise AssertionError('No-gravity throw lost the startled animation')
            else:
                raise AssertionError('No-gravity throw never settled')
            stop_timers()
            if not bounced or playback() != saved or not window.model.manual_repeat:
                raise AssertionError('No-gravity landing did not restore the original action')
            window._set_preference('gravity_enabled', True)

            throw()
            window._stop_throw(landing=False)  # Grabbing in flight.
            stop_timers()
            if playback() != saved or window.model.motion_clip_name is not None:
                raise AssertionError('Interrupted throw lost the prior action')

            throw()
            window._set_preference('inertia_enabled', False)
            stop_timers()
            if window.throw_motion is not None or playback() != saved:
                raise AssertionError('Disabling inertia did not restore the prior action')
            window.inertia_enabled = True

            throw()
            window.apply_message(dict(protocolVersion=1, kind='state', state='WAITING', message='Waiting'))
            if window.model.active_clip_name != 'throw_startled':
                raise AssertionError('Task update interrupted the moving reaction')
            window._stop_throw()
            stop_timers()
            if window.model.active_clip_name != window.model.state_map['WAITING']:
                raise AssertionError('Landing restored an outdated action over the latest task')

            throw()
            window._set_reduced_motion(True)
            stop_timers()
            if window.throw_motion is not None or window.model.motion_clip_name is not None:
                raise AssertionError('Reduced motion left the startled reaction stuck')

            print('MOTION_OK', flush=True)
            print('TRANSITIONS_OK', flush=True)
            window.apply_message(dict(protocolVersion=1, kind='config', restartSupported=True))
            menu = window._build_context_menu()
            restart = menu.findChild(QtWidgets.QPushButton, 'restartPet')
            if restart is None or not restart.isEnabled():
                raise AssertionError('Restart is missing from the native context menu')
            replies = []
            original_emit = helper.emit_reply
            helper.emit_reply = lambda kind, **fields: replies.append(kind)
            try:
                restart.click()
                window._restart_pet()  # A repeated activation must emit only one request.
            finally:
                helper.emit_reply = original_emit
            if replies != ['restart']:
                raise AssertionError(f'Restart menu emitted unexpected messages: {replies}')
            saved_layout = load_layout(window.layout_path)
            if (saved_layout['petX'], saved_layout['petY']) != (window.pet_x, window.pet_y):
                raise AssertionError('Restart did not save the latest pet position')
            print('RESTART_MENU_OK', flush=True)
            app.exit(0)
        except Exception:
            import traceback
            traceback.print_exc()
            app.exit(1)

    class TestApp(app_type):
        def __init__(self, *args):
            super().__init__(*args)
            QtCore.QTimer.singleShot(1000, check)

    QtWidgets.QApplication = TestApp
    return helper.run_visual(helper.EventRecorder(None))


class NativeTransitionTests(unittest.TestCase):
    def test_clip_changes_show_only_the_current_pose(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, PYTHONUTF8='1', DSH_DAFEIYU_LAYOUT_PATH=str(Path(temporary) / 'layout.json'),
                       DSH_DAFEIYU_SOUND_ENABLED='0')
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--probe'],
                                       cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding='utf-8')
            # Hold stdin open so helper EOF does not close the window before QA.
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                self.fail('Qt transition check timed out')
            finally:
                stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('TRANSITIONS_OK', stdout, stderr)
            self.assertIn('MOTION_OK', stdout, stderr)
            self.assertIn('RESTART_MENU_OK', stdout, stderr)


if __name__ == '__main__':
    if '--probe' in sys.argv:
        raise SystemExit(probe())
    unittest.main()
