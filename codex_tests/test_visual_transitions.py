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
            settings.close()
            for state in ['THINKING', 'WORKING', 'WAITING', 'SUCCESS', 'IDLE']:
                window.apply_message(dict(protocolVersion=1, kind='state', state=state,
                                          message='Transition test', detail=''))
                immediate = window.grab().toImage()
                QtTest.QTest.qWait(180)
                settled = window.grab().toImage()
                if immediate != settled:
                    raise AssertionError(f'{state}: clip change still blends old and new poses')
            print('TRANSITIONS_OK', flush=True)
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


if __name__ == '__main__':
    if '--probe' in sys.argv:
        raise SystemExit(probe())
    unittest.main()
