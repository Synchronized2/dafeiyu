"""Exercise actual Qt drag/perch/hover/wander and fractional-DPI rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def probe(dpi_only=False):
    from PySide6 import QtCore, QtGui, QtWidgets
    from runtime import helper
    from runtime.layout_store import load_layout
    app_type = QtWidgets.QApplication

    def check():
        app = app_type.instance()
        try:
            window = next(w for w in app.topLevelWidgets() if w.__class__.__name__ == 'CompanionWindow')
            for timer in (window.behavior_timer, window.animation_timer, window.motion_timer, window.micro_timer):
                timer.stop()
            window.bubble_mode = 'hidden'
            window._sync_bubble_size()
            window._set_preference('scale', .8)
            expected_size = (512, 288)
            if window._pet_size() != expected_size:
                raise AssertionError(f'DPI changed logical character size: {window._pet_size()}')
            old_position = (window.pet_x, window.pet_y)
            window._pixmap(window.model.frame)
            window.decoded_frames['sentinel'] = window._pixmap(window.model.frame)
            window._refresh_display()
            if 'sentinel' in window.decoded_frames or (window.pet_x, window.pet_y) != old_position:
                raise AssertionError('Display refresh kept old raster cache or moved the character')
            image = window.grab()
            dpr = window.devicePixelRatioF()
            if abs(image.width() - window.width() * dpr) > 1:
                raise AssertionError('Screenshot backing size does not match monitor DPI')
            if sys.platform == 'win32':
                import ctypes
                api = ctypes.windll.user32
                api.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
                api.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                if api.GetAwarenessFromDpiAwarenessContext(api.GetThreadDpiAwarenessContext()) != 2:
                    raise AssertionError('Native process is not per-monitor DPI aware')
            print('DPI_INFO', json.dumps(dict(dpr=dpr, logicalSize=window._pet_size(),
                                             screens=[dict(name=s.name(), geometry=s.geometry().getRect(),
                                                           dpr=s.devicePixelRatio()) for s in app.screens()])), flush=True)
            if dpi_only:
                print('DPI_OK', flush=True)
                app.exit(0)
                return

            window._set_preference('scale', 1)
            from runtime.desktop_controls import PetSettings
            settings = PetSettings(window)
            for key, saved_key, percent, preset in (('scale', 'scale', 73, 1.0),
                                                     ('bubble_scale', 'bubbleScale', 91, 1.2),
                                                     ('perch_scale', 'perchScale', 85, 1.5)):
                slider = settings.size_sliders[key]
                slider.setValue(percent)
                if abs(getattr(window, key) - percent / 100) > .001:
                    raise AssertionError(f'{key}: slider did not apply a custom size')
                if load_layout(window.layout_path)[saved_key] != percent / 100:
                    raise AssertionError(f'{key}: custom slider value was not saved')
                if settings.size_labels[key].text() != f'{percent}%':
                    raise AssertionError(f'{key}: percentage label did not update')
                if not settings.choices[key].currentText().startswith('自定义'):
                    raise AssertionError(f'{key}: custom size was labelled as a preset')
                slider.setValue(percent + 1)
                if sum(settings.choices[key].itemText(i).startswith('自定义')
                       for i in range(settings.choices[key].count())) != 1:
                    raise AssertionError('Dragging the slider accumulated custom choices')
                settings.choices[key].setCurrentIndex(settings.choices[key].findData(preset))
                if slider.value() != round(preset * 100) or getattr(window, key) != preset:
                    raise AssertionError(f'{key}: named preset did not synchronize with slider')
            window._set_preference('scale', 1.0)
            settings.size_sliders['bubble_scale'].setValue(100)
            settings.size_sliders['perch_scale'].setValue(100)
            if os.environ.get('DSH_INTERACTION_QA_DIR'):
                settings.show()
                settings.grab().save(str(Path(os.environ['DSH_INTERACTION_QA_DIR']) / 'settings-sliders.png'))
                settings.hide()
            for key, setting in (('perch_enabled', 'perchEnabled'), ('hover_enabled', 'hoverEnabled'),
                                 ('wander_enabled', 'wanderEnabled')):
                before = getattr(window, key)
                settings.toggles[key].click()
                if getattr(window, key) == before or load_layout(window.layout_path)[setting] == before:
                    raise AssertionError(f'{key}: checkbox did not apply and persist')
                settings.toggles[key].click()
            settings.close()
            window._set_preference('scale', .7)
            window._set_preference('bubble_scale', .7)
            window._set_preference('perch_scale', .7)
            reopened = PetSettings(window)
            for name in ('scale', 'bubble_scale', 'perch_scale'):
                if (reopened.size_sliders[name].value() != 70 or
                        reopened.size_labels[name].text() != '70%' or
                        reopened.choices[name].currentText() != '自定义（70%）'):
                    raise AssertionError(f'{name}: reopening exposed a ratio instead of the saved percentage')
            if load_layout(window.layout_path)['bubbleScale'] != .7:
                raise AssertionError('Reopening changed the actual saved size')
            if os.environ.get('DSH_INTERACTION_QA_DIR'):
                reopened.show()
                reopened.grab().save(str(Path(os.environ['DSH_INTERACTION_QA_DIR']) / 'settings-compact-70.png'))
                reopened.hide()
            reopened.close()
            window._set_preference('scale', 1.0)
            window._set_preference('bubble_scale', 1.0)
            window._set_preference('perch_scale', 1.0)

            def point_on_pet():
                pixmap = window._pet_pixmap()
                image = pixmap.toImage()
                x, y, width, height = window._pet_rect()
                for py in range(image.height() // 3, image.height(), 4):
                    for px in range(image.width() // 3, image.width() * 2 // 3, 4):
                        if image.pixelColor(px, py).alpha() >= 128:
                            return window.mapToGlobal(QtCore.QPoint(round(x + px * width / image.width()),
                                                                   round(y + py * height / image.height())))
                raise AssertionError('No visible character pixels found')

            def save(name):
                path = os.environ.get('DSH_INTERACTION_QA_DIR')
                if path:
                    Path(path).mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(Path(path) / (name + '.png')))
                    if window.status_bubble.isVisible():
                        window.status_bubble.grab().save(str(Path(path) / (name + '-bubble.png')))

            def playback():
                return window.model.active_clip_name, window.model.frame_index, window.model.frame_elapsed_ms

            # The full sprite canvas is wider than the visible character. Both
            # sides must touch the work area with the bubble still on screen.
            window.bubble_mode = 'always'
            window._sync_bubble_size()
            screen = window.screen().availableGeometry()
            for side, requested in (('left', screen.x() - 10000), ('right', screen.right() + 10000)):
                window._move_to_pet(requested, screen.y() + 180, screen_hint=window.screen())
                vx, vy, vw, vh = window._pet_visible_rect()
                edge = window.pet_x + vx if side == 'left' else window.pet_x + vx + vw
                expected = screen.x() if side == 'left' else screen.x() + screen.width()
                if abs(edge - expected) > 1:
                    raise AssertionError(f'{side}: transparent canvas blocked the visible edge')
                rx, ry, rw, rh = window._pet_rect()
                if window.x() + rx != window.pet_x:
                    raise AssertionError('Offscreen padding changed the drawn character anchor')
                bx, by, bw, bh = window._bubble_rect()
                bubble = window.status_bubble
                if bubble.x() + bx < screen.x() or bubble.x() + bx + bw > screen.x() + screen.width():
                    raise AssertionError('Visible-edge placement pushed the bubble offscreen')
                if bw > round(337 * window.bubble_scale):
                    raise AssertionError('Bubble did not use compact sizing')
                visual = window._current_visual_rect()
                if (window.width(), window.height()) != visual[2:]:
                    raise AssertionError('Native pet window still contains animation-canvas padding')
                from PIL import Image
                shot = window.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
                alpha = Image.frombytes('RGBA', (shot.width(), shot.height()), bytes(shot.constBits())).getchannel('A')
                opaque = alpha.point(lambda value: 255 if value >= 32 else 0).getbbox()
                tolerance = round(4 * window.devicePixelRatioF())
                if (not opaque or max(opaque[0], opaque[1], shot.width() - opaque[2],
                                      shot.height() - opaque[3]) > tolerance):
                    raise AssertionError(f'Invisible alpha residue left large native-window margins: {opaque}')
                if not bubble.windowFlags() & QtCore.Qt.WindowType.WindowTransparentForInput:
                    raise AssertionError('Independent bubble intercepts desktop input')
                save('visible-edge-' + side)
                window.apply_message(dict(protocolVersion=1, kind='state', state='WORKING', message='正在执行任务', detail='OpenAIQ'))
                if not window._try_perch():
                    raise AssertionError('Working state blocked deliberate edge placement')
                window.apply_message(dict(protocolVersion=1, kind='state', state='WORKING', message='正在执行任务'))
                if window.perched_edge != side:
                    raise AssertionError('Repeated working state cancelled perching')
                window.apply_message(dict(protocolVersion=1, kind='state', state='WAITING', message='需要你确认'))
                if window.perched_edge:
                    raise AssertionError('Attention state remained hidden at the edge')
            window.bubble_mode = 'hidden'
            window._sync_bubble_size()
            if window.status_bubble.isVisible():
                raise AssertionError('Hidden bubble still has a visible independent window')
            window.model.apply_state('IDLE')
            window.model.play_manual_action('extra_cube', repeat=True)
            window.model.advance(133, window._now_ms())
            saved_playback = playback()
            bounds = window._motion_bounds()
            window._move_to_pet(round(bounds.left + 4), round(bounds.top + 100))
            if not window._try_perch() or window.perched_edge != 'left':
                raise AssertionError('Slow placement at left edge did not perch')
            if window._pet_size()[0] != 96 or window._pet_size()[1] >= 200:
                raise AssertionError('Perched window is not compact')
            if window._bubble_visible() or window.model.manual_clip_name != 'extra_cube':
                raise AssertionError('Perching lost manual playback or left a large status card')
            save('perch-left')
            normal_width = window.width()
            for percent in (.5, 1.5, 2.0):
                window._set_preference('perch_scale', percent)
                if window._pet_size()[0] != round(96 * percent):
                    raise AssertionError('Perched size did not update immediately')
                vx, _, _, _ = window._pet_visible_rect()
                if abs(window.pet_x + vx - window.screen().availableGeometry().x()) > 1:
                    raise AssertionError('Resizing the perched head detached it from the edge')
                if load_layout(window.layout_path)['perchScale'] != percent:
                    raise AssertionError('Perched size did not persist')
            save('perch-left-large')
            window._set_preference('perch_scale', 1.0)
            if window.width() != normal_width:
                raise AssertionError('Restoring default perch size changed its appearance')
            window._refresh_display()
            window._leave_perch()
            if playback() != saved_playback or not window.model.manual_repeat:
                raise AssertionError('Leaving the edge did not resume the original animation')
            bounds = window._motion_bounds()
            window._move_to_pet(round(bounds.right - 4), round(bounds.top + 100))
            if not window._try_perch() or window.perched_edge != 'right':
                raise AssertionError('Slow placement at right edge did not perch')
            save('perch-right')
            saved_perch = load_layout(window.layout_path)
            window._leave_perch()
            window.layout = saved_perch
            window._restore_visible_position()
            if window.perched_edge != 'right':
                raise AssertionError('Restart layout did not restore the perched edge')
            window.apply_message(dict(protocolVersion=1, kind='state', state='WAITING', message='Task needs input'))
            if window.perched_edge or window.model.active_clip_name != window.model.state_map['WAITING']:
                raise AssertionError('Perching hid a task that needs attention')
            window.model.apply_state('IDLE')
            window.model.play_manual_action('extra_cube', repeat=True)
            window.model.advance(133, window._now_ms())
            saved_playback = playback()
            window._enter_perch('right')
            menu = window._build_context_menu()
            emerge = menu.findChild(QtWidgets.QPushButton, 'leavePerch')
            if emerge is None:
                raise AssertionError('No way to leave the edge from the menu')
            emerge.click()
            if window.perched_edge is not None or playback() != saved_playback:
                raise AssertionError('Come-out menu did not restore the original animation')

            # Top and bottom use the same release detection, size preference and
            # restore path as the side edges, with an upright/downward head.
            for edge in ('top', 'bottom'):
                bounds = window._motion_bounds()
                target_y = bounds.top + 2 if edge == 'top' else bounds.bottom - 2
                window._move_to_pet(round((bounds.left + bounds.right) / 2), round(target_y))
                if not window._try_perch() or window.perched_edge != edge:
                    raise AssertionError(f'{edge}: slow placement did not perch')
                if window._pet_size()[0] <= window._pet_size()[1]:
                    raise AssertionError(f'{edge}: head kept a sideways aspect ratio')
                save('perch-' + edge)
                for size in (.5, 1.5, 2.0):
                    window._set_preference('perch_scale', size)
                    vx, vy, vw, vh = window._pet_visible_rect()
                    area = window.screen().availableGeometry()
                    actual = window.pet_y + vy if edge == 'top' else window.pet_y + vy + vh
                    expected = area.y() if edge == 'top' else area.y() + area.height()
                    if abs(actual - expected) > 1:
                        raise AssertionError(f'{edge}: resizing detached the head from the edge')
                window._set_preference('perch_scale', 1.0)
                window._refresh_display()
                stored = load_layout(window.layout_path)
                anchor = window.pet_x, window.pet_y
                window._leave_perch()
                if playback() != saved_playback:
                    raise AssertionError(f'{edge}: leaving lost manual playback')
                window.layout = stored
                window._restore_visible_position()
                if window.perched_edge != edge or (window.pet_x, window.pet_y) != anchor:
                    raise AssertionError(f'{edge}: restart moved or lost the perched head')
                window._begin_drag()
                if window.perched_edge or not window.dragging:
                    raise AssertionError(f'{edge}: pulling out did not restore the full character')
                window._finish_drag()
                window.model.clear_motion()
                window.model.play_manual_action('extra_cube', repeat=True)
                window.model.advance(133, window._now_ms())
                saved_playback = playback()

            # Trigger real mouse event handlers, including pulling the head away from its edge.
            window._move_to_pet(round(bounds.left + 4), round(bounds.top + 100))
            window._try_perch()
            start = point_on_pet()
            local = window.mapFromGlobal(start)
            press = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(local), QtCore.QPointF(start),
                                     QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
                                     QtCore.Qt.KeyboardModifier.NoModifier)
            window.mousePressEvent(press)
            target = start + QtCore.QPoint(500, 30)
            move = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(window.mapFromGlobal(target)),
                                    QtCore.QPointF(target), QtCore.Qt.MouseButton.NoButton,
                                    QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
            window.mouseMoveEvent(move)
            if not window.dragging or window.perched_edge or window.drag_tilt <= 0:
                raise AssertionError('Dragging out of a perch failed to restore/tilt the full character')
            save('drag-tilt')
            # Pausing before release is placement, rather than a throw.
            window.drag_trail.last_moved = 0
            release = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPointF(window.mapFromGlobal(target)),
                                       QtCore.QPointF(target), QtCore.Qt.MouseButton.LeftButton,
                                       QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier)
            window.mouseReleaseEvent(release)
            if window.throw_motion or window.dragging or window.drag_tilt:
                raise AssertionError('Placing after a pause unexpectedly threw or stayed tilted')
            clip = window.model.active_clip
            window.model.advance(len(clip.frames) * clip.frame_ms, window._now_ms())
            if playback() != saved_playback:
                raise AssertionError('Drag completion lost the original animation position')

            # A hover pauses movement and shows its own card only after a delay.
            window.bubble_mode = 'always'
            window._sync_bubble_size()
            now = window._now_ms()
            point = point_on_pet()
            window._tick_behavior(now, point)
            if not window.hovered or window.hover_card_active:
                raise AssertionError('Hover delay or body hit testing failed')
            window._tick_behavior(now + 600, point)
            if not window.hover_card_active or ':' not in window._current_card()[1]:
                raise AssertionError('Hover did not show the live clock')
            save('hover-clock')
            if window._pet_contains(QtCore.QPoint(0, 0)):
                raise AssertionError('Transparent window margin counted as character hover')
            window.bubble_mode = 'hidden'
            window._sync_bubble_size()
            if window._bubble_visible():
                raise AssertionError('Hover ignored the hidden-bubble preference')
            away = QtCore.QPoint(-100000, -100000)
            window._tick_behavior(now + 650, away)
            if window.hover_card_active or window.hovered:
                raise AssertionError('Hover remained active after leaving the character')

            def start_walk(at):
                window.model.clear_overlay()
                window.model.apply_state('IDLE')
                window.last_touch_ms = at - 6000
                window.wander_wait_until = 0
                window.behavior_tick_ms = at - 50
                window._tick_behavior(at, away)
                if window.wander_motion is None:
                    raise AssertionError('Idle wandering did not begin')

            start_walk(now + 1000)
            before_x = window.pet_x
            window._tick_behavior(now + 1050, away)
            if window.pet_x == before_x:
                raise AssertionError('Walking animation is not moving the character')
            save('wander')
            window._tick_behavior(now + 1100, point_on_pet())
            if window.wander_motion or not window.hovered or window.model.motion_clip_name:
                raise AssertionError('Visible-pixel hover did not immediately stop wandering')
            window._tick_behavior(now + 1150, away)

            start_walk(now + 7000)
            window.apply_message(dict(protocolVersion=1, kind='state', state='WAITING', message='Task needs input'))
            window._tick_behavior(now + 7050, away)
            if window.wander_motion or window.model.active_clip_name != window.model.state_map['WAITING']:
                raise AssertionError('Wander animation overrode an important task state')
            window.model.apply_state('IDLE')
            window.model.play_manual_action('extra_cube', repeat=True)
            window.last_touch_ms = 0
            window.wander_wait_until = 0
            window._tick_behavior(now + 14000, away)
            if window.wander_motion or window.model.manual_clip_name != 'extra_cube':
                raise AssertionError('Wander animation overrode manual playback')

            start_walk(now + 15000)
            window._set_reduced_motion(True)
            window._tick_behavior(now + 20000, away)
            if window.wander_motion:
                raise AssertionError('Reduced motion did not disable wandering')
            window._set_reduced_motion(False)
            start_walk(now + 21000)
            window._set_preference('wander_enabled', False)
            if window.wander_motion:
                raise AssertionError('Disabling wandering did not stop current movement')
            window.model.clear_overlay()
            window._enter_perch('left')
            window._set_preference('perch_enabled', False)
            if window.perched_edge:
                raise AssertionError('Disabling perching did not bring the pet back')
            print('BEHAVIOR_OK', flush=True)
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


class NativeDesktopInteractionTests(unittest.TestCase):
    def run_probe(self, dpi=None):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, PYTHONUTF8='1', DSH_DAFEIYU_LAYOUT_PATH=str(Path(temporary) / 'layout.json'),
                       DSH_DAFEIYU_SOUND_ENABLED='0')
            arguments = ['--probe']
            if dpi is not None:
                env.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=str(dpi))
                arguments = ['--dpi-probe']
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *arguments],
                                       cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding='utf-8')
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                self.fail('Desktop interaction probe timed out')
            finally:
                stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertIn('DPI_OK' if dpi is not None else 'BEHAVIOR_OK', stdout, stderr)
            return stdout

    def test_native_drag_perch_hover_wander_and_priority(self):
        self.run_probe()

    def test_logical_geometry_and_backing_raster_at_fractional_dpi(self):
        for factor in (1, 1.25, 2):
            with self.subTest(dpi=factor):
                output = self.run_probe(dpi=factor)
                info = json.loads(next(line.removeprefix('DPI_INFO ') for line in output.splitlines()
                                       if line.startswith('DPI_INFO ')))
                self.assertAlmostEqual(info['dpr'], factor, places=2)
                self.assertEqual(info['logicalSize'], [512, 288])


if __name__ == '__main__':
    if '--probe' in sys.argv or '--dpi-probe' in sys.argv:
        raise SystemExit(probe(dpi_only='--dpi-probe' in sys.argv))
    unittest.main()
