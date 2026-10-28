"""Phase 0 native BigFish helper.

The DSH plugin owns this process and sends newline-delimited JSON over stdin.
Closing stdin is a lifecycle signal: the helper exits instead of becoming an
independent desktop application.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import random
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, TextIO

try:
    from .pet_behavior import CARING_WORDS, WanderMotion, head_crop, nearest_screen_index, perch_side
    from .display_support import enable_per_monitor_dpi
    from .animation_model import AnimationModel
    from .layout_store import default_layout_path, load_layout, save_layout
    from .asset_paths import bundle_root
    from .pet_geometry import bubble_top, panel_position, position_window
    from .pet_motion import Bounds, DragTrail, ThrowMotion
    from .action_library import actions_for, load_pet_manifest
except ImportError:
    from pet_behavior import CARING_WORDS, WanderMotion, head_crop, nearest_screen_index, perch_side
    from display_support import enable_per_monitor_dpi
    from animation_model import AnimationModel
    from layout_store import default_layout_path, load_layout, save_layout
    from asset_paths import bundle_root
    from pet_geometry import bubble_top, panel_position, position_window
    from pet_motion import Bounds, DragTrail, ThrowMotion
    from action_library import actions_for, load_pet_manifest


PROTOCOL_VERSION = 1
STATES = {"IDLE", "THINKING", "WORKING", "WAITING", "SUCCESS", "ERROR", "DISCONNECTED"}
# Full 640x360 frames cost ~0.88 MB decoded. Load on demand and retain only a
# bounded cache, independent of how many actions are installed.
DECODED_FRAME_CACHE = 24
DECODED_FRAME_CACHE_PIXELS = 24 * 640 * 360


def configure_qt_platform() -> None:
    """Prefer XWayland when available so desktop-window controls keep working."""
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM"):
        return
    platforms: list[str] = []
    if os.environ.get("DISPLAY"):
        platforms.append("xcb")
    if os.environ.get("WAYLAND_DISPLAY"):
        platforms.append("wayland")
    if platforms:
        os.environ["QT_QPA_PLATFORM"] = ";".join(platforms)


def configure_stdio() -> None:
    """Make the JSONL pipe UTF-8 regardless of the Windows console code page."""
    for stream, errors in ((sys.stdin, "strict"), (sys.stdout, "backslashreplace"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def parse_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    if message.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    kind = message.get("kind")
    if kind in {"state", "pulse"} and message.get("state") not in STATES:
        raise ValueError("unsupported companion state")
    return message


def emit_reply(kind: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"protocolVersion": PROTOCOL_VERSION, "kind": kind, "timestamp": int(time.time() * 1000), **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


# ---- Glove cursor (native Win32 .cur) ----
def _cursor_api() -> tuple[Any, Any, Any]:
    """Return configured (LoadCursorFromFileW, SetCursor, LoadCursorW) callables.

    Function signatures are declared explicitly so HCURSOR values are handled
    as pointer-sized handles: without argtypes/restype, ctypes treats the
    return value as a C int and truncates 64-bit HCURSORs. wintypes has no
    HCURSOR type, so ``wintypes.HANDLE`` (pointer-sized) is used.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    load_from_file = user32.LoadCursorFromFileW
    load_from_file.argtypes = [wintypes.LPCWSTR]
    load_from_file.restype = wintypes.HANDLE

    set_cursor = user32.SetCursor
    set_cursor.argtypes = [wintypes.HANDLE]
    set_cursor.restype = wintypes.HANDLE

    load_cursor = user32.LoadCursorW
    load_cursor.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    load_cursor.restype = wintypes.HANDLE

    return load_from_file, set_cursor, load_cursor


def load_native_cursor(path: Path) -> Any:
    """Load a .cur cursor with LoadCursorFromFileW (pointer-sized handles).

    Returns None outside Windows or on failure; callers then fall back to the
    Qt default cursor. The resource is loaded at its natural size: per the MSDN
    remarks, LoadCursorFromFileW does not participate in DPI virtualization, so
    the 32x32 .cur is NOT scaled up automatically; the OS renders the cursor
    bitmap on the same pipeline as system cursors.
    """
    if sys.platform != "win32":
        return None
    try:
        handle = _cursor_api()[0](str(path))
        return handle or None
    except Exception:
        return None


def set_native_cursor(handle: Any) -> None:
    """Set the current cursor immediately (bypasses Qt's cursor pipeline)."""
    try:
        _cursor_api()[1](handle)
    except Exception:
        pass


def reset_native_cursor() -> None:
    """Restore the default arrow cursor (IDC_ARROW)."""
    try:
        import ctypes

        # MAKEINTRESOURCE(32512): the identifier is passed as a pointer value.
        arrow = ctypes.cast(ctypes.c_void_p(32512), ctypes.c_wchar_p)
        _cursor_api()[2](None, arrow)
    except Exception:
        pass


class GloveCursorController:
    """Pure state machine for the glove cursor; no Qt or Win32 dependencies.

    ``open_h`` / ``closed_h`` may be None (non-Windows, or the .cur assets are
    missing): every query then returns None, so callers simply fall back to the
    default cursor. This keeps all cursor-state decisions testable.
    """

    WM_LBUTTONDOWN = 0x0201

    def __init__(self, open_h: Any, closed_h: Any) -> None:
        self.open_h = open_h
        self.closed_h = closed_h
        self.pressed = False

    def handle_for(self, closed: bool) -> Any:
        return self.closed_h if closed else self.open_h

    def on_enter(self) -> Any:
        """Pointer entered the pet window: show the open hand."""
        return self.open_h

    def on_leave(self) -> None:
        """Pointer left the pet window: clear the pressed flag, reset to arrow."""
        self.pressed = False
        return None

    def on_press(self) -> Any:
        """Left button pressed: show the closed fist."""
        self.pressed = True
        return self.closed_h

    def on_release(self, inside: bool) -> Any:
        """Left button released: open hand when still inside, otherwise None."""
        self.pressed = False
        return self.open_h if inside else None

    def on_wm_setcursor(self, mouse_msg: int) -> Any:
        """WM_SETCURSOR decision: closed on WM_LBUTTONDOWN (or while pressed)."""
        return self.handle_for(mouse_msg == self.WM_LBUTTONDOWN or self.pressed)


class EventRecorder:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._stream: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding="utf-8")

    def record(self, message: dict[str, Any]) -> None:
        if self._stream is None:
            return
        self._stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()


def run_headless(recorder: EventRecorder) -> int:
    try:
        emit_reply("ready")
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
                continue
            recorder.record(message)
            if message.get("kind") == "ping":
                emit_reply("pong")
                continue
            if message.get("kind") == "shutdown":
                break
    finally:
        recorder.close()
    return 0


def run_visual(recorder: EventRecorder, snapshot_path: Path | None = None) -> int:
    configure_qt_platform()
    enable_per_monitor_dpi()
    try:
        from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QPoint, QRectF, Qt, QTimer, QUrl, Signal
        from PySide6.QtGui import QBitmap, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QMouseEvent, QPainter, QPen, QPixmap, QRegion, QTransform
        from PySide6.QtWidgets import QApplication, QMenu, QWidget
        try:
            from .action_browser import ActionBrowser
            from .desktop_controls import PetSettings
            from .pet_menu import PetMenu
            from .frame_renderer import render_frame
        except ImportError:
            from action_browser import ActionBrowser
            from desktop_controls import PetSettings
            from pet_menu import PetMenu
            from frame_renderer import render_frame
    except ImportError as error:
        print(
            f"PySide6 and Pillow are required for visual mode ({error}). Run with --headless for protocol tests.",
            file=sys.stderr,
        )
        recorder.close()
        return 2

    class Inbox(QObject):
        message = Signal(dict)
        closed = Signal()

    manifest_path = bundle_root() / "assets" / "pet-manifest.json"
    asset_root = manifest_path.parent / "pet"
    try:
        manifest = load_pet_manifest(manifest_path)
    except (OSError, ValueError) as error:
        print(f"Unable to load BigFish asset manifest: {error}", file=sys.stderr)
        recorder.close()
        return 2

    class GloveCursorFilter(QAbstractNativeEventFilter):
        """Owns WM_SETCURSOR while the pointer is over the pet window.

        The pet shows a glove hand cursor: an open hand on hover and a closed
        fist while the left button is held. Native .cur cursors are loaded with
        LoadCursorFromFileW and handed to the OS cursor pipeline directly (the
        same rendering path as system cursors; note the API loads the resource
        at its natural 32x32 size and does not participate in DPI
        virtualization). The message is consumed immediately instead of going
        through Qt's QCursor bitmaps, which are re-scaled by Qt and only take
        effect on the next cursor update cycle.
        """

        def __init__(self, widget: Any, open_h: Any, closed_h: Any) -> None:
            super().__init__()
            self.widget = widget
            self.open_h = open_h
            self.closed_h = closed_h

        def nativeEventFilter(self, event_type: bytes, message: Any):
            try:
                if event_type != b"windows_generic_MSG":
                    return False, 0
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message != 0x0020:  # WM_SETCURSOR
                    return False, 0
                hwnd = int(msg.hWnd) if msg.hWnd else 0
                if hwnd and hwnd != int(self.widget.winId()):
                    # Leave popups (context menu, …) to Qt's default cursor.
                    return False, 0
                hit_test = msg.lParam & 0xFFFF
                if hit_test != 1:  # HTCLIENT
                    return False, 0
                mouse_msg = (msg.lParam >> 16) & 0xFFFF
                handle = self.widget.glove.on_wm_setcursor(mouse_msg)
                if handle:
                    set_native_cursor(handle)
                    return True, 0
            except Exception:
                pass
            return False, 0

    class StatusBubble(QWidget):
        """An independent, input-transparent status card, never drag padding."""
        def __init__(self, companion):
            super().__init__(companion, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                             | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.companion = companion
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.companion._paint_status_card(painter)

    class CompanionWindow(QWidget):
        LABELS = {
            "IDLE": "休息中",
            "THINKING": "思考中",
            "WORKING": "干活中",
            "WAITING": "等你呢",
            "SUCCESS": "完成啦",
            "ERROR": "出问题了",
            "DISCONNECTED": "已断开",
        }

        def __init__(self) -> None:
            super().__init__()
            self.layout_path = default_layout_path()
            self.layout = load_layout(self.layout_path)
            self.render_profile = self.layout["renderProfile"]
            self.raster_factor = 1.0
            configured_scale = os.environ.get("DSH_DAFEIYU_SCALE")
            try:
                self.scale = min(1.8, max(0.4, float(configured_scale))) if configured_scale else self.layout["scale"]
            except ValueError:
                self.scale = self.layout["scale"]
            configured_bubble_scale = os.environ.get("DSH_DAFEIYU_BUBBLE_SCALE")
            try:
                self.bubble_scale = (
                    min(1.6, max(0.6, float(configured_bubble_scale)))
                    if configured_bubble_scale
                    else self.layout["bubbleScale"]
                )
            except ValueError:
                self.bubble_scale = self.layout["bubbleScale"]
            configured_reduced_motion = os.environ.get("DSH_DAFEIYU_REDUCED_MOTION")
            self.reduced_motion = (
                configured_reduced_motion == "1"
                if configured_reduced_motion is not None
                else self.layout["reducedMotion"]
            )
            configured_sound_enabled = os.environ.get("DSH_DAFEIYU_SOUND_ENABLED")
            self.sound_enabled = configured_sound_enabled != "0"
            self.activity_level = os.environ.get("DSH_DAFEIYU_ACTIVITY_LEVEL", self.layout["activityLevel"])
            self.inertia_enabled = self.layout["inertiaEnabled"]
            self.gravity_enabled = self.layout["gravityEnabled"]
            self.edge_snap = self.layout["edgeSnap"]
            self.perch_enabled = self.layout["perchEnabled"]
            self.perch_scale = self.layout["perchScale"]
            self.hover_enabled = self.layout["hoverEnabled"]
            self.wander_enabled = self.layout["wanderEnabled"]
            self.perched_edge: str | None = None
            self.hovered = False
            self.hover_card_active = False
            self.hover_since_ms = 0
            self.hover_clock_second = -1
            self.hover_sentence = CARING_WORDS[0]
            self.drag_tilt = 0.0
            self.drag_fraction = (.5, .5)
            self.drag_last_point: QPoint | None = None
            self.watched_screen = None
            self.display_refresh_pending = False
            self.visible_rect_cache = {}
            self.visual_bounds_key = None
            self.visual_bounds = None
            configured_bubble_mode = os.environ.get("DSH_DAFEIYU_BUBBLE_MODE")
            self.bubble_mode = (
                configured_bubble_mode
                if configured_bubble_mode in {"always", "hidden", "custom"}
                else self.layout.get("bubbleMode", "always")
            )
            configured_bubble_states = os.environ.get("DSH_DAFEIYU_BUBBLE_STATES")
            if configured_bubble_states is not None:
                self.bubble_states = [part.strip() for part in configured_bubble_states.split(",") if part.strip()]
            else:
                self.bubble_states = list(self.layout.get("bubbleStates", ["SUCCESS", "ERROR", "WAITING"]))
            self.manifest = manifest
            self.menu_open = False
            self.follow_codex = True
            self.restart_supported = False
            self.restart_pending = False
            self.model = AnimationModel(manifest)
            self.idle_actions = [name for name in self.layout["idleActions"] if name in self.model.manual_actions]
            self.model.idle_micro_clips = tuple(self.idle_actions)
            self.action_browser = None
            self.settings_dialog = None
            self.frame_sources: dict[str, Path] = {}
            for clip in self.model.clips.values():
                for frame in clip.frames:
                    if frame in self.frame_sources:
                        continue
                    source = asset_root / frame
                    if not source.is_file():
                        raise RuntimeError(f"Unable to load BigFish frame: {frame}")
                    self.frame_sources[frame] = source
            self.decoded_frames: OrderedDict[str, QPixmap] = OrderedDict()
            # Fail here, not on the first paint, when the assets are unreadable or
            # the bundled Qt has no WebP image plugin.
            for clip in self.model.clips.values():
                if clip.frames:
                    self._pixmap(clip.frames[0])
            self.decoded_frames.clear()

            self.display_state = "IDLE"
            self.status_state = "IDLE"
            self.status_message = "我在这儿等新任务哦"
            self.status_detail = "DSH · 等待下一次任务"
            self.status_deadline_ms: int | None = self._now_ms() + 4200
            # Glove cursor: native .cur handles (loaded at natural size).
            self.glove_open_h = load_native_cursor(asset_root.parent / "cursor_grab.cur")
            self.glove_closed_h = load_native_cursor(asset_root.parent / "cursor_grabbing.cur")
            self.glove = GloveCursorController(self.glove_open_h, self.glove_closed_h)
            self.overlay_state: str | None = None
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_deadline_ms: int | None = None
            self.task = ""
            self.tasks: list[dict[str, Any]] = []
            self.webui_url = os.environ.get("DSH_DAFEIYU_WEBUI_URL", "http://127.0.0.1:3080/")
            self.open_label = os.environ.get("DSH_DAFEIYU_OPEN_LABEL", "打开 DSH")
            self.balance_summary = ""
            self.drag_origin: QPoint | None = None
            self.pet_origin: QPoint | None = None
            self.pet_x = 0
            self.pet_y = 0
            self.dragging = False
            self.drag_trail = DragTrail()
            self.throw_motion: ThrowMotion | None = None
            self.wander_motion: WanderMotion | None = None
            self.last_touch_ms = self._now_ms()
            self.wander_wait_until = self.last_touch_ms + random.randint(6000, 12000)
            self.behavior_tick_ms = self.last_touch_ms
            self.last_tick_ms = self._now_ms()
            self.animation_timer = QTimer(self)
            self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.animation_timer.timeout.connect(self._tick)
            self.animation_timer.start(self._animation_interval_ms())
            self.micro_timer = QTimer(self)
            self.micro_timer.setSingleShot(True)
            self.micro_timer.timeout.connect(self._play_idle_micro)
            self.motion_timer = QTimer(self)
            self.motion_timer.setInterval(16)
            self.motion_timer.timeout.connect(self._tick_motion)
            self.motion_tick = time.monotonic()
            self.behavior_timer = QTimer(self)
            self.behavior_timer.setInterval(50)
            self.behavior_timer.timeout.connect(self._tick_behavior)
            self.behavior_timer.start()
            if not self.reduced_motion:
                self._schedule_micro()
            self.snapshot_saved = False
            self.setWindowTitle(os.environ.get("DSH_DAFEIYU_TITLE", "DSH 大肥鱼"))
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.status_bubble = StatusBubble(self)
            QApplication.instance().aboutToQuit.connect(self.status_bubble.hide)
            self._apply_window_size()
            QTimer.singleShot(0, self._restore_visible_position)

        def apply_message(self, message: dict[str, Any]) -> None:
            recorder.record(message)
            kind = message.get("kind")
            if kind in {"state", "pulse"} and (kind == "pulse" or message.get("state") != "IDLE"):
                self._stop_wander()
                if kind == "pulse" or message.get("state") in {"WAITING", "ERROR", "SUCCESS"}:
                    self._leave_perch()
                self._set_hover(False, self._now_ms())
            if kind == "shutdown":
                QApplication.quit()
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if kind == "task":
                self.task = str(message.get("task", ""))
                self._show_status(
                    str(message.get("message", self.task)),
                    str(message.get("detail", "")),
                    self.model.base_state,
                    None if self.model.base_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else 6000,
                )
            elif kind == "tasks":
                raw_tasks = message.get("tasks")
                self.tasks = raw_tasks if isinstance(raw_tasks, list) else []
                self._sync_bubble_size()
            elif kind == "config":
                self._apply_config(message)
            elif kind == "balance":
                self.balance_summary = str(message.get("summary", ""))[:200]
                self._sync_bubble_size()
            elif kind == "action":
                self._play_manual_action(str(message.get("action", "")), repeat=message.get("repeat") is True)
            elif kind in {"state", "pulse"}:
                previous_base_state = self.model.base_state
                state = str(message.get("state", "IDLE"))
                self.display_state = state
                if kind == "pulse":
                    ttl_ms = max(250, int(message.get("ttlMs", 1800)))
                    resume_state = str(message.get("resumeState", self.model.base_state))
                    self.model.apply_pulse(
                        state,
                        ttl_ms,
                        self._now_ms(),
                        resume_state,
                        message.get("resumeActivity"),
                        complete_clip=not self.reduced_motion,
                    )
                    ttl_ms = self.model.pulse_deadline_ms - self._now_ms()
                    self._show_status(
                        str(message.get("resumeMessage", self.LABELS.get(resume_state, resume_state))),
                        str(message.get("resumeDetail", "")),
                        resume_state,
                        None if resume_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else ttl_ms + 2200,
                    )
                    self._show_overlay(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        ttl_ms,
                    )
                    if state in {"SUCCESS", "ERROR"}:
                        self._notify_alert(state)
                else:
                    activity = None if self.reduced_motion else message.get("activity")
                    self.model.apply_state(state, activity)
                    self.display_state = self.model.pulse_state or state
                    if self.model.pulse_state is None:
                        self._clear_overlay()
                    persistent = state in {"THINKING", "WORKING", "WAITING", "ERROR"}
                    self._show_status(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        None if persistent else 4200,
                    )
                if previous_base_state != self.model.base_state and not self.reduced_motion:
                    self._schedule_micro()
            self._sync_frame_transition(previous_frame, previous_clip)
            self._sync_bubble_size()
            self.update()
            if snapshot_path is not None and not self.snapshot_saved:
                QTimer.singleShot(180, self._save_snapshot)

        def _set_reduced_motion(self, enabled: bool) -> None:
            self.reduced_motion = enabled
            self.animation_timer.setInterval(self._animation_interval_ms())
            if enabled:
                self._stop_wander()
                self._stop_throw()
                self.micro_timer.stop()
                if not self.dragging:
                    self.model.clear_motion()
                    self.model.clear_overlay()
            else:
                self._schedule_micro()

        def _apply_config(self, message: dict[str, Any]) -> None:
            """Apply a live CONFIG message without restarting the window."""
            if isinstance(message.get("openUrl"), str):
                self.webui_url = message["openUrl"]
            if isinstance(message.get("openLabel"), str):
                self.open_label = message["openLabel"]
            if isinstance(message.get("restartSupported"), bool):
                self.restart_supported = message["restartSupported"]
            if isinstance(message.get("followCodex"), bool):
                self.follow_codex = message["followCodex"]
            scale = message.get("scale")
            if isinstance(scale, (int, float)) and not isinstance(scale, bool):
                self.scale = min(1.8, max(0.4, float(scale)))
            bubble_scale = message.get("bubbleScale")
            if isinstance(bubble_scale, (int, float)) and not isinstance(bubble_scale, bool):
                self.bubble_scale = min(1.6, max(0.6, float(bubble_scale)))
            reduced_motion = message.get("reducedMotion")
            if isinstance(reduced_motion, bool) and reduced_motion != self.reduced_motion:
                self._set_reduced_motion(reduced_motion)
            sound_enabled = message.get("soundEnabled")
            if isinstance(sound_enabled, bool):
                self.sound_enabled = sound_enabled
            activity_level = message.get("activityLevel")
            if activity_level in {"quiet", "normal", "lively"}:
                self.activity_level = activity_level
                if not self.reduced_motion:
                    self._schedule_micro()
            bubble_mode = message.get("bubbleMode")
            if bubble_mode in {"always", "hidden", "custom"}:
                self.bubble_mode = bubble_mode
            bubble_states = message.get("bubbleStates")
            if isinstance(bubble_states, list):
                self.bubble_states = [str(state) for state in bubble_states if isinstance(state, str)]
            self._sync_bubble_size()
            self._save_layout()

        def _apply_glove(self, closed: bool) -> None:
            """Closed fist while the button is held, open hand otherwise.

            Sets the cursor directly so feedback is immediate instead of
            waiting for the next WM_SETCURSOR pass.
            """
            self.glove.pressed = closed
            handle = self.glove.handle_for(closed)
            if handle:
                set_native_cursor(handle)

        def enterEvent(self, event: Any) -> None:
            self._apply_glove(False)
            super().enterEvent(event)

        def leaveEvent(self, event: Any) -> None:
            self.glove.pressed = False
            reset_native_cursor()
            super().leaveEvent(event)

        def _set_hover(self, hovered: bool, now_ms: int) -> None:
            if hovered != self.hovered:
                self.hovered = hovered
                self.hover_since_ms = now_ms
                if hovered:
                    self.hover_sentence = random.choice(CARING_WORDS)
                    self._stop_wander()
            if hovered:
                self.last_touch_ms = now_ms
            active = (hovered and self.hover_enabled and now_ms - self.hover_since_ms >= 550
                      and self.model.base_state == "IDLE" and self.model.pulse_state is None
                      and not self.dragging and self.throw_motion is None and not self.menu_open)
            if active != self.hover_card_active:
                self.hover_card_active = active
                self._sync_bubble_size()
            if active and now_ms // 1000 != self.hover_clock_second:
                self.hover_clock_second = now_ms // 1000
                self._update_status_bubble()
                self.update()

        def _pet_pixmap(self) -> QPixmap:
            if self.perched_edge is None:
                return self._pixmap(self.model.frame)
            # Perching reuses our own idle head, not a different character's art.
            source = self._pixmap(self.model.clips[self.model.state_map["IDLE"]].frames[0])
            crop = head_crop(tuple(manifest.get("originalFrameRect", (0, 0, source.width(), source.height()))))
            factor = self.raster_factor
            head = source.copy(*(round(value * factor) for value in crop))
            angle = 90 if self.perched_edge == "left" else -90
            return head.transformed(QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation)

        def _pet_contains(self, local: QPoint) -> bool:
            x, y, width, height = self._pet_rect()
            if not (x <= local.x() < x + width and y <= local.y() < y + height):
                return False
            pixmap = self._pet_pixmap()
            px = min(pixmap.width() - 1, int((local.x() - x) * pixmap.width() / width))
            py = min(pixmap.height() - 1, int((local.y() - y) * pixmap.height() / height))
            return pixmap.toImage().pixelColor(px, py).alpha() >= 32

        def _tick_behavior(self, now_ms: int | None = None, pointer: QPoint | None = None) -> None:
            now_ms = self._now_ms() if now_ms is None else now_ms
            elapsed = max(0, now_ms - self.behavior_tick_ms) / 1000
            self.behavior_tick_ms = now_ms
            pointer = QCursor.pos() if pointer is None else pointer
            panels_open = self.settings_dialog is not None or self.action_browser is not None
            can_hover = not (self.dragging or self.drag_origin is not None or self.menu_open or panels_open)
            self._set_hover(can_hover and self._pet_contains(self.mapFromGlobal(pointer)), now_ms)
            can_walk = (self.wander_enabled and not self.reduced_motion and not self.hovered
                        and not self.dragging and self.drag_origin is None and self.throw_motion is None
                        and self.perched_edge is None and not self.menu_open and not panels_open
                        and self.model.base_state == "IDLE" and self.model.pulse_state is None
                        and self.model.overlay_clip_name is None and now_ms - self.last_touch_ms >= 5000)
            if not can_walk:
                self._stop_wander()
                return
            if self.wander_motion is None:
                if self.model.motion_clip_name is not None or now_ms < self.wander_wait_until:
                    return
                bounds = self._motion_bounds()
                if bounds is None or bounds.right - bounds.left < 16:
                    return
                target = min(max(self.pet_x + random.choice((-1, 1)) * random.uniform(80, 200) * self.scale,
                                 bounds.left), bounds.right)
                if abs(target - self.pet_x) < 12:
                    target = bounds.right if self.pet_x <= (bounds.left + bounds.right) / 2 else bounds.left
                self.wander_motion = WanderMotion(self.pet_x, self.pet_y, target, bounds, 72 * self.scale)
                self.micro_timer.stop()
                walking = "extra_floating_steps" if "extra_floating_steps" in self.model.clips else self.model.base_clip_name
                self._play_motion_animation(walking)
            motion = self.wander_motion
            motion.step(elapsed)
            self._move_to_pet(round(motion.x), round(motion.y))
            if not motion.active:
                self._stop_wander()
                self.wander_wait_until = now_ms + random.randint(4000, 9000)
                self._save_layout()

        def _stop_wander(self) -> None:
            if self.wander_motion is None:
                return
            self.wander_motion = None
            self.model.clear_motion()
            self.wander_wait_until = self._now_ms() + random.randint(4000, 9000)
            self._schedule_micro()
            self.update()

        def _try_perch(self) -> bool:
            if (not self.perch_enabled or self.throw_motion is not None or self.model.pulse_state is not None
                    or self.model.base_state not in {"IDLE", "DISCONNECTED", "THINKING", "WORKING"}):
                return False
            bounds = self._motion_bounds()
            side = perch_side(self.pet_x, self._pet_size()[0], bounds, self.scale) if bounds else None
            if side is None:
                return False
            self._enter_perch(side)
            return True

        def _enter_perch(self, side: str, *, save: bool = True) -> None:
            if side not in {"left", "right"}:
                return
            screen = self._screen_for_point(self.pet_x + self._pet_size()[0] // 2, self.pet_y)
            if screen is None:
                return
            self._stop_wander()
            self.perched_edge = side
            self.drag_tilt = 0
            self._play_motion_animation(self.model.state_map["IDLE"])
            self._apply_window_size()
            geometry = screen.availableGeometry()
            vx, _, vw, _ = self._pet_visible_rect()
            x = geometry.left() - vx if side == "left" else geometry.x() + geometry.width() - vx - vw
            self._move_to_pet(x, self.pet_y, screen_hint=screen)
            self.micro_timer.stop()
            if save:
                self._save_layout()

        def _leave_perch(self) -> None:
            if self.perched_edge is None:
                return
            side = self.perched_edge
            screen = self._screen_for_point(self.pet_x, self.pet_y)
            self.perched_edge = None
            self.model.advance(0, self._now_ms())
            self.model.clear_motion()
            self._apply_window_size()
            x = self.pet_x
            if screen:
                geometry = screen.availableGeometry()
                vx, _, vw, _ = self._pet_visible_rect()
                x = geometry.left() - vx if side == "left" else geometry.x() + geometry.width() - vx - vw
            self._move_to_pet(x, self.pet_y, screen_hint=screen)
            self.last_touch_ms = self._now_ms()
            self._schedule_micro()
            self._save_layout()

        def _screen_for_point(self, x: int, y: int):
            screen = QApplication.screenAt(QPoint(x, y))
            if screen is not None:
                return screen
            screens = QApplication.screens()
            index = nearest_screen_index((x, y), [item.geometry().getRect() for item in screens])
            return screens[index] if index is not None else None

        def _connect_display_events(self) -> None:
            handle = self.windowHandle()
            if handle is None:
                return
            handle.screenChanged.connect(self._on_screen_changed)
            QApplication.instance().screenAdded.connect(self._schedule_display_refresh)
            QApplication.instance().screenRemoved.connect(self._schedule_display_refresh)
            self._on_screen_changed(handle.screen())

        def _on_screen_changed(self, screen: Any) -> None:
            old = self.watched_screen
            if old is not None:
                for signal_name in ("logicalDotsPerInchChanged", "availableGeometryChanged", "geometryChanged"):
                    try:
                        getattr(old, signal_name).disconnect(self._schedule_display_refresh)
                    except (RuntimeError, TypeError):
                        pass
            self.watched_screen = screen
            if screen is not None:
                for signal_name in ("logicalDotsPerInchChanged", "availableGeometryChanged", "geometryChanged"):
                    getattr(screen, signal_name).connect(self._schedule_display_refresh)
            self._schedule_display_refresh()

        def _schedule_display_refresh(self, *args: Any) -> None:
            if not self.display_refresh_pending:
                self.display_refresh_pending = True
                QTimer.singleShot(0, self._refresh_display)

        def _refresh_display(self) -> None:
            self.display_refresh_pending = False
            self.decoded_frames.clear()
            self._stop_wander()
            self._apply_window_size()
            screen = self._screen_for_point(self.pet_x + self._pet_size()[0] // 2, self.pet_y)
            if self.dragging:
                pointer = QCursor.pos()
                screen = self._screen_for_point(pointer.x(), pointer.y())
                width, height = self._pet_size()
                x = round(pointer.x() - self.drag_fraction[0] * width)
                y = round(pointer.y() - self.drag_fraction[1] * height)
                self.drag_trail = DragTrail()  # A monitor coordinate jump is not throw velocity.
            else:
                x, y = self.pet_x, self.pet_y
                if self.perched_edge and screen:
                    geometry = screen.availableGeometry()
                    vx, _, vw, _ = self._pet_visible_rect()
                    x = geometry.x() - vx if self.perched_edge == "left" else geometry.x() + geometry.width() - vx - vw
            self._move_to_pet(x, y, screen_hint=screen)
            if self.throw_motion is not None:
                bounds = self._motion_bounds()
                if bounds:
                    self.throw_motion.bounds = bounds
                    self.throw_motion.x, self.throw_motion.y = bounds.clamp(self.pet_x, self.pet_y)
            self.update()

        def event(self, event: Any) -> bool:
            result = super().event(event)
            if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "display_refresh_pending"):
                self._schedule_display_refresh()
            return result

        def _animation_interval_ms(self) -> int:
            if self.reduced_motion:
                return 40
            # Sub-frame poll: a once-per-frame timer turns one early delivery into a whole-frame hitch.
            return max(8, min(20, round(self.model.active_clip.frame_ms / 3)))

        def _rearm_animation_interval(self) -> None:
            wanted = self._animation_interval_ms()
            if self.animation_timer.interval() != wanted:
                self.animation_timer.setInterval(wanted)

        def _pixmap(self, frame: str) -> QPixmap:
            factor = 1.0 if self.render_profile == "original" else max(1.0, min(3.0, self.scale * self.devicePixelRatioF()))
            if factor != self.raster_factor:
                self.decoded_frames.clear()
                self.raster_factor = factor
            cached = self.decoded_frames.get(frame)
            if cached is not None:
                self.decoded_frames.move_to_end(frame)
                return cached
            image = render_frame(self.frame_sources[frame], self.render_profile, factor)
            pixmap = QPixmap.fromImage(image)
            original = manifest.get("originalFrameRect")
            if original and (round(image.width() / factor), round(image.height() / factor)) == tuple(original[2:]):
                # Original cropped clips and full-canvas community clips share
                # exactly the same character scale, source center and feet line.
                canvas = QPixmap(round(manifest["maxFrameWidth"] * factor), round(manifest["maxFrameHeight"] * factor))
                canvas.fill(Qt.GlobalColor.transparent)
                painter = QPainter(canvas)
                painter.drawPixmap(round(original[0] * factor), round(original[1] * factor), pixmap)
                painter.end()
                pixmap = canvas
            self.decoded_frames[frame] = pixmap
            while len(self.decoded_frames) > 1 and (
                    len(self.decoded_frames) > DECODED_FRAME_CACHE or
                    sum(p.width() * p.height() for p in self.decoded_frames.values()) > DECODED_FRAME_CACHE_PIXELS):
                self.decoded_frames.popitem(last=False)
            return pixmap

        def _tick(self) -> None:
            now_ms = self._now_ms()
            elapsed_ms = max(0, now_ms - self.last_tick_ms)
            self.last_tick_ms = now_ms
            had_pulse = self.model.pulse_state is not None
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            model_elapsed = 0 if self.reduced_motion else elapsed_ms
            self.model.advance(model_elapsed, now_ms)
            self._sync_frame_transition(previous_frame, previous_clip)
            if had_pulse and self.model.pulse_state is None:
                self.display_state = self.model.base_state
            if self.overlay_deadline_ms is not None and now_ms >= self.overlay_deadline_ms:
                self._clear_overlay()
            self._rearm_animation_interval()
            self.update()

        def _play_idle_micro(self) -> None:
            if self.hovered or self.perched_edge or self.wander_motion is not None:
                self._schedule_micro()
                return
            if self.reduced_motion:
                return
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            self.model.play_idle_micro(random.randrange(max(1, len(self.model.idle_micro_clips))))
            self._sync_frame_transition(previous_frame, previous_clip)
            self.update()
            self._schedule_micro()

        def _sync_frame_transition(
            self,
            previous_frame: str,
            previous_clip: str,
            *,
            allow_fade: bool = True,
        ) -> None:
            # Preload the new frame; composite only this pose when painting.
            # Blending transparent sprites from different clips creates two
            # visible outlines even with correct frame clearing.
            self._pixmap(self.model.frame)
            self._apply_window_size()

        def _play_motion_animation(
            self,
            clip_name: str,
            *,
            repeat: bool = True,
            repaint: bool = True,
        ) -> bool:
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            if not self.model.play_motion(clip_name, repeat=repeat):
                return False
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            if repaint:
                self.update()
            return True

        def _begin_drag(self) -> None:
            if self.dragging:
                return
            self._stop_wander()
            self._leave_perch()
            self.dragging = True
            self._set_hover(False, self._now_ms())
            self.micro_timer.stop()
            played = self._play_motion_animation("dragging", repaint=False)
            if not played:
                self.animation_timer.stop()
                return
            clip = self.model.active_clip
            if self.reduced_motion or not clip.loop:
                self.animation_timer.stop()
            else:
                self.last_tick_ms = self._now_ms()
                self.animation_timer.start(self._animation_interval_ms())

        def _motion_bounds(self) -> Bounds | None:
            width, height = self._pet_size()
            geometry = self._screen_geometry_at(self.pet_x + width // 2, self.pet_y + height // 2)
            if geometry is None:
                return None
            vx, vy, vw, vh = self._pet_visible_rect()
            return Bounds(geometry.x() - vx, geometry.y() - vy,
                          max(geometry.x() - vx, geometry.x() + geometry.width() - vx - vw),
                          max(geometry.y() - vy, geometry.y() + geometry.height() - vy - vh))

        def _snap_to_edge(self) -> None:
            bounds = self._motion_bounds()
            if self.edge_snap and bounds is not None:
                x, y = bounds.snap(self.pet_x, self.pet_y)
                self._move_to_pet(round(x), round(y))

        def _start_throw(self, vx: float, vy: float) -> bool:
            self._stop_wander()
            bounds = self._motion_bounds()
            if bounds is None or self.reduced_motion or not self.inertia_enabled or (vx == 0 and vy == 0):
                return False
            self.throw_motion = ThrowMotion(self.pet_x, self.pet_y, vx, vy, bounds,
                                            gravity_enabled=self.gravity_enabled)
            self.micro_timer.stop()
            # Keep the startled reaction through every bounce until motion settles.
            reaction = "throw_startled" if "throw_startled" in self.model.clips else "dragging"
            self._play_motion_animation(reaction)
            self.last_tick_ms = self._now_ms()
            self.motion_tick = time.monotonic()
            self.animation_timer.start(self._animation_interval_ms())
            self.motion_timer.start()
            return True

        def _tick_motion(self) -> None:
            motion = self.throw_motion
            if motion is None:
                self.motion_timer.stop()
                return
            now = time.monotonic()
            motion.step(now - self.motion_tick)
            self.motion_tick = now
            self._move_to_pet(round(motion.x), round(motion.y))
            if not motion.active:
                self._stop_throw()

        def _stop_throw(self, *, landing: bool = True) -> None:
            if self.throw_motion is None:
                return
            self.throw_motion = None
            self.motion_timer.stop()
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            now_ms = self._now_ms()
            self.model.advance(0, now_ms)
            self.model.clear_motion()
            self.last_tick_ms = now_ms
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            self.animation_timer.start(self._animation_interval_ms())
            if landing:
                self._snap_to_edge()
            self._schedule_micro()
            self.update()
            self._save_layout()

        def _finish_drag(self) -> None:
            if not self.dragging:
                return
            now_ms = self._now_ms()
            previous_frame = self.model.frame
            previous_clip = self.model.active_clip_name
            # Expire an underlying pulse before revealing it after a long drag.
            self.model.advance(0, now_ms)
            if self.reduced_motion or not self.model.play_motion("dragging_release", repeat=False):
                self.model.clear_motion()
            self._sync_frame_transition(previous_frame, previous_clip, allow_fade=False)
            self.dragging = False
            self.drag_tilt = 0
            self.last_touch_ms = now_ms
            self.last_tick_ms = now_ms
            self.animation_timer.start(self._animation_interval_ms())
            if not self.reduced_motion:
                self._schedule_micro()

        def _schedule_micro(self) -> None:
            if self.reduced_motion:
                self.micro_timer.stop()
                return
            lower, upper = self.model.idle_micro_interval(self.activity_level)
            self.micro_timer.start(self.model.overlay_remaining_ms + random.randint(lower, upper))

        def _bubble_visible(self) -> bool:
            if self.perched_edge and not self.hover_card_active:
                return False
            if self.hover_card_active and self.bubble_mode != "hidden":
                return True
            if self.bubble_mode == "hidden":
                return False
            if self.bubble_mode == "always":
                return True
            if len(self.tasks) >= 2:
                return any(task.get("state") in self.bubble_states for task in self.tasks)
            state = self.overlay_state or self.status_state or self.model.base_state or "IDLE"
            return state in self.bubble_states

        def _sync_bubble_size(self) -> None:
            self._apply_window_size()

        def _current_visual_rect(self) -> tuple[int, int, int, int]:
            pixmap = self._pet_pixmap()
            width, height = self._pet_size()
            tilt = self.drag_tilt if self.dragging and not self.reduced_motion else 0
            key = (self.model.frame, self.perched_edge, width, height, self.raster_factor, tilt)
            if key != self.visual_bounds_key:
                rect = QRegion(QBitmap.fromImage(pixmap.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdDither))).boundingRect()
                if rect.isEmpty():
                    rect = pixmap.rect()
                logical = QRectF(rect.x() * width / pixmap.width(), rect.y() * height / pixmap.height(),
                                 rect.width() * width / pixmap.width(), rect.height() * height / pixmap.height())
                if tilt:
                    transform = QTransform().translate(width / 2, height * .55)
                    transform.rotate(tilt)
                    transform.translate(-width / 2, -height * .55)
                    logical = transform.mapRect(logical)
                logical = logical.adjusted(-2, -2, 2, 2).toAlignedRect()
                self.visual_bounds = logical.getRect()
                self.visual_bounds_key = key
            return self.visual_bounds

        def _apply_window_size(self) -> None:
            # Preserve the shared animation anchor while fitting the native
            # window to this frame. No sprite scaling or per-frame recentering.
            x, y, width, height = self._current_visual_rect()
            self.setFixedSize(width, height)
            self.move(round(self.pet_x + x), round(self.pet_y + y))
            self._update_status_bubble()

        def _update_status_bubble(self) -> None:
            bubble = getattr(self, "status_bubble", None)
            if bubble is None:
                return
            if not self._bubble_visible() or self.menu_open or not self.isVisible():
                bubble.hide()
                return
            _, _, width, height = self._bubble_rect()
            bubble.setFixedSize(width + 16, height + 22)
            vx, vy, vw, vh = self._current_visual_rect()
            screen = self._screen_for_point(self.pet_x + vx + vw // 2, self.pet_y + vy + vh // 2)
            if screen is None:
                return
            area = screen.availableGeometry()
            left = round(self.pet_x + vx + vw / 2 - bubble.width() / 2)
            top = round(self.pet_y + vy - bubble.height() - 5)
            if top < area.y() + 3:
                top = round(self.pet_y + vy + vh + 5)
            left = min(max(left, area.x() + 3), max(area.x() + 3, area.x() + area.width() - bubble.width() - 3))
            top = min(max(top, area.y() + 3), max(area.y() + 3, area.y() + area.height() - bubble.height() - 3))
            bubble.move(left, top)
            bubble.show()
            card = self._current_card()
            bubble.setToolTip("\n".join(card[:2]) if card else "")
            bubble.update()

        def _screen_geometry_at(self, x: int, y: int):
            screen = self._screen_for_point(x, y)
            if screen is None:
                return None
            return screen.availableGeometry()

        def _pet_size(self) -> tuple[int, int]:
            if self.perched_edge:
                _, _, head_width, head_height = head_crop(tuple(manifest.get("originalFrameRect", (0, 0, 412, 344))))
                width = round(96 * self.scale * self.perch_scale)
                return width, round(width * head_width / head_height)
            return (
                round(int(manifest["maxFrameWidth"]) * self.scale),
                round(int(manifest["maxFrameHeight"]) * self.scale),
            )

        def _move_to_pet(self, pet_x: int, pet_y: int, *, screen_hint: Any = None) -> None:
            """Place the logical pet anchor on the cursor's monitor during a drag."""
            selected = screen_hint or self._screen_for_point(pet_x + self._pet_size()[0] // 2, pet_y)
            geometry = selected.availableGeometry() if selected is not None else None
            handle = self.windowHandle()
            if handle is not None and selected is not None and handle.screen() != selected:
                handle.setScreen(selected)
            screen = (geometry.x(), geometry.y(), geometry.width(), geometry.height()) if geometry is not None else None
            width, height = self._pet_size()
            vx, vy, vw, vh = self._pet_visible_rect()
            if geometry is not None:
                pet_x = min(max(pet_x, geometry.x() - vx), max(geometry.x() - vx, geometry.x() + geometry.width() - vx - vw))
                pet_y = min(max(pet_y, geometry.y() - vy), max(geometry.y() - vy, geometry.y() + geometry.height() - vy - vh))
            self.pet_x, self.pet_y = round(pet_x), round(pet_y)
            self._apply_window_size()
            self.update()

        def _pet_offset_x(self, pet_width: int) -> int:
            return self.pet_x - self.x()

        def _pet_rect(self) -> tuple[int, int, int, int]:
            return self.pet_x - self.x(), self.pet_y - self.y(), *self._pet_size()

        def _pet_visible_rect(self) -> tuple[int, int, int, int]:
            """Stable idle silhouette bounds; transparent animation padding is not a wall."""
            key = self.perched_edge
            if key not in self.visible_rect_cache:
                pixmap = (self._pet_pixmap() if key else
                          self._pixmap(self.model.clips[self.model.state_map["IDLE"]].frames[0]))
                rect = QRegion(QBitmap.fromImage(pixmap.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdDither))).boundingRect()
                if rect.isEmpty():
                    rect = pixmap.rect()
                self.visible_rect_cache[key] = (rect.x() / pixmap.width(), rect.y() / pixmap.height(),
                                                rect.width() / pixmap.width(), rect.height() / pixmap.height())
            width, height = self._pet_size()
            x, y, w, h = self.visible_rect_cache[key]
            return round(x * width), round(y * height), max(1, round(w * width)), max(1, round(h * height))

        def _bubble_render_scale(self) -> float:
            return self.bubble_scale * .8

        def _bubble_rect(self) -> tuple[int, int, int, int]:
            # Match the visible character, not the 640-pixel animation canvas.
            _, _, visible_width, _ = self._pet_visible_rect()
            if self.perched_edge:
                visible_width = round(220 * self.scale)
            width = round(max(190, min(300, visible_width * 1.2)) * self.bubble_scale)
            return 8, 6, width, self._card_height()

        def _restore_visible_position(self) -> None:
            pet_width, pet_height = self._pet_size()
            top_offset = self.height() - pet_height - 8
            center_offset = (self.width() - pet_width) // 2
            saved_pet_x = self.layout.get("petX")
            saved_pet_y = self.layout.get("petY")
            if isinstance(saved_pet_x, int) and isinstance(saved_pet_y, int):
                pet_x, pet_y = saved_pet_x, saved_pet_y
            else:
                saved_x = self.layout.get("x")
                saved_y = self.layout.get("y")
                if isinstance(saved_x, int) and isinstance(saved_y, int):
                    # Legacy layouts stored the window position.  Recreate the
                    # pet position that the old centered layout would have had.
                    pet_x = saved_x + center_offset
                    pet_y = saved_y + top_offset
                else:
                    geometry = self._screen_geometry_at(self.x() + self.width() // 2, self.y() + self.height() // 2)
                    if geometry is None:
                        return
                    pet_x = geometry.right() - pet_width - 24
                    pet_y = geometry.bottom() - pet_height - 24
            preferred = next((screen for screen in QApplication.screens()
                              if screen.name() == self.layout.get("displayName")), None)
            self._move_to_pet(pet_x, pet_y, screen_hint=preferred)
            if self.perch_enabled and self.layout.get("perchedEdge") in {"left", "right"}:
                self._enter_perch(self.layout["perchedEdge"], save=False)

        def _save_layout(self) -> None:
            self.layout = {
                "version": 1,
                "x": self.x(),
                "y": self.y(),
                "petX": self.pet_x,
                "petY": self.pet_y,
                "scale": self.scale,
                "bubbleScale": self.bubble_scale,
                "renderProfile": self.render_profile,
                "reducedMotion": self.reduced_motion,
                "bubbleMode": self.bubble_mode,
                "bubbleStates": self.bubble_states,
                "inertiaEnabled": self.inertia_enabled,
                "gravityEnabled": self.gravity_enabled,
                "edgeSnap": self.edge_snap,
                "perchEnabled": self.perch_enabled,
                "perchScale": self.perch_scale,
                "hoverEnabled": self.hover_enabled,
                "wanderEnabled": self.wander_enabled,
                "perchedEdge": self.perched_edge,
                "displayName": self.windowHandle().screen().name() if self.windowHandle() and self.windowHandle().screen() else "",
                "activityLevel": self.activity_level,
                "idleActions": self.idle_actions,
            }
            try:
                save_layout(self.layout_path, self.layout)
            except OSError as error:
                print(f"Unable to save BigFish layout: {error}", file=sys.stderr)

        def _save_snapshot(self) -> None:
            if snapshot_path is None or self.snapshot_saved:
                return
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.snapshot_saved = self.grab().save(str(snapshot_path), "PNG")

        def _show_status(self, message: str, detail: str, state: str, ttl_ms: int | None) -> None:
            self.status_message = message
            self.status_detail = detail
            self.status_state = state
            self.status_deadline_ms = None if ttl_ms is None else self._now_ms() + ttl_ms

        def _show_overlay(self, message: str, detail: str, state: str, ttl_ms: int) -> None:
            self.overlay_message = message
            self.overlay_detail = detail or self.status_detail
            self.overlay_state = state
            self.overlay_deadline_ms = self._now_ms() + ttl_ms

        def _clear_overlay(self) -> None:
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_state = None
            self.overlay_deadline_ms = None

        @staticmethod
        def _now_ms() -> int:
            return int(time.monotonic() * 1000)

        def _current_card(self) -> tuple[str, str, str] | None:
            now_ms = self._now_ms()
            if self.hover_card_active and self.model.base_state == "IDLE" and self.model.pulse_state is None:
                stamp = datetime.now()
                weekday = "一二三四五六日"[stamp.weekday()]
                return self.hover_sentence, stamp.strftime(f"%Y-%m-%d 周{weekday}  %H:%M:%S"), "IDLE"
            if self.overlay_message and (
                self.overlay_deadline_ms is None or now_ms < self.overlay_deadline_ms
            ):
                return self.overlay_message, self.overlay_detail, self.overlay_state or self.status_state
            if self.status_message and (
                self.status_deadline_ms is None or now_ms < self.status_deadline_ms
            ):
                return self.status_message, self.status_detail, self.status_state
            if self.balance_summary:
                return "大肥鱼陪你待命", "DSH · 等待下一次任务", "IDLE"
            return None

        @staticmethod
        def _status_colors(state: str) -> tuple[QColor, QColor]:
            return {
                "SUCCESS": (QColor("#D9F7E4"), QColor("#12B85A")),
                "ERROR": (QColor("#FDE3E3"), QColor("#E5484D")),
                "WAITING": (QColor("#FFF0CE"), QColor("#D88A00")),
                "THINKING": (QColor("#E2ECFF"), QColor("#4C78E8")),
                "WORKING": (QColor("#DDEBFF"), QColor("#3478F6")),
                "DISCONNECTED": (QColor("#ECEEF1"), QColor("#7B818A")),
            }.get(state, (QColor("#ECEEF1"), QColor("#747A84")))

        def _draw_status_icon(self, painter: QPainter, state: str, center_x: int, center_y: int) -> None:
            background, foreground = self._status_colors(state)
            radius = 23
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
            pen = QPen(foreground, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if state == "SUCCESS":
                painter.drawLine(center_x - 10, center_y, center_x - 3, center_y + 8)
                painter.drawLine(center_x - 3, center_y + 8, center_x + 12, center_y - 10)
            elif state == "ERROR":
                painter.drawLine(center_x - 8, center_y - 8, center_x + 8, center_y + 8)
                painter.drawLine(center_x + 8, center_y - 8, center_x - 8, center_y + 8)
            elif state == "WAITING":
                painter.drawLine(center_x, center_y - 10, center_x, center_y + 3)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 2, center_y + 9, 4, 4)
            elif state in {"THINKING", "WORKING"}:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                for offset in (-9, 0, 9):
                    painter.drawEllipse(center_x + offset - 3, center_y - 3, 6, 6)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)

        def _card_height(self) -> int:
            footer = 28 if self.balance_summary else 0
            if len(self.tasks) >= 2:
                rows = min(len(self.tasks), 3)
                return round((58 + rows * 26 + footer) * self._bubble_render_scale())
            return round((62 + footer) * self.bubble_scale)

        def _draw_card_background(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            corner_radius: int,
            s: float,
        ) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(17, 24, 39, 13))
            painter.drawRoundedRect(
                card_x + 1, card_y + round(13 * s), card_width - 2, card_height,
                corner_radius, corner_radius,
            )
            painter.setBrush(QColor(17, 24, 39, 18))
            painter.drawRoundedRect(
                card_x, card_y + round(7 * s), card_width, card_height,
                corner_radius, corner_radius,
            )
            painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
            painter.setBrush(QColor(252, 252, 253, 248))
            painter.drawRoundedRect(
                card_x, card_y, card_width, card_height,
                corner_radius, corner_radius,
            )

        def _draw_multi_task_card(
            self,
            painter: QPainter,
            card_x: int,
            card_y: int,
            card_width: int,
            card_height: int,
            s: float,
        ) -> None:
            title_font = QFont("Microsoft YaHei UI")
            title_font.setPointSizeF(11.0 * max(.8, s))
            title_font.setWeight(QFont.Weight.DemiBold)
            detail_font = QFont("Microsoft YaHei UI")
            detail_font.setPointSizeF(9.0 * max(.8, s))
            text_x = card_x + round(16 * s)
            text_width = max(40, card_width - round(32 * s))
            painter.setFont(title_font)
            painter.setPen(QColor("#25282D"))
            title = f"{len(self.tasks)} 个任务进行中"
            painter.drawText(
                text_x,
                card_y + round(10 * s),
                text_width,
                max(12, round(22 * s)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, text_width),
            )
            painter.setFont(detail_font)
            for index, task in enumerate(self.tasks[:3]):
                row_y = card_y + round((36 + index * 24) * s)
                state = str(task.get("state", "IDLE"))
                state_label = self.LABELS.get(state, state)
                label = task.get("project") or task.get("task") or task.get("message") or state_label
                line = f"{state_label} · {label}"
                _, foreground = self._status_colors(state)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(text_x, row_y + round(4 * s), round(8 * s), round(8 * s))
                painter.setPen(QColor("#747981"))
                painter.drawText(
                    text_x + round(14 * s),
                    row_y,
                    text_width - round(14 * s),
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    QFontMetrics(detail_font).elidedText(line, Qt.TextElideMode.ElideRight, text_width - round(14 * s)),
                )
            if len(self.tasks) > 3:
                more = f"还有 {len(self.tasks) - 3} 个任务…"
                painter.setPen(QColor("#9AA0A6"))
                painter.drawText(
                    text_x + round(14 * s),
                    card_y + round((36 + 3 * 24) * s),
                    text_width,
                    max(12, round(20 * s)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    more,
                )

        def _notify_alert(self, state: str) -> None:
            if self.sound_enabled:
                played = False
                if sys.platform == "win32":
                    try:
                        import winsound

                        sound_name = "success.wav" if state == "SUCCESS" else "error.wav"
                        sound_path = bundle_root() / "assets" / "sounds" / sound_name
                        winsound.PlaySound(
                            str(sound_path),
                            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                        )
                        played = True
                    except (ImportError, OSError, RuntimeError):
                        pass
                if not played:
                    try:
                        QApplication.beep()
                    except Exception:
                        pass

        def _paint_status_card(self, painter: QPainter) -> None:
            show_card = self._bubble_visible() and not self.menu_open
            card = self._current_card() if show_card else None
            card_x, card_y, card_width, card_height = self._bubble_rect()
            s = self._bubble_render_scale()
            corner_radius = round(13 * s)

            if len(self.tasks) >= 2 and show_card:
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                self._draw_multi_task_card(painter, card_x, card_y, card_width, card_height, s)
            elif card:
                title, detail, card_state = card
                self._draw_card_background(painter, card_x, card_y, card_width, card_height, corner_radius, s)
                s = self.bubble_scale
                icon_center_x = card_x + card_width - round(23 * s)
                icon_center_y = card_y + round(30 * s)
                painter.save()
                painter.translate(icon_center_x, icon_center_y)
                painter.scale(.58 * s, .58 * s)
                painter.translate(-icon_center_x, -icon_center_y)
                self._draw_status_icon(painter, card_state, icon_center_x, icon_center_y)
                painter.restore()
                text_x = card_x + round(12 * s)
                text_width = max(40, card_width - round(51 * s))
                title_font = QFont("Microsoft YaHei UI")
                title_font.setPointSizeF(9 * max(.9, s))
                title_font.setWeight(QFont.Weight.DemiBold)
                detail_font = QFont("Microsoft YaHei UI")
                detail_font.setPointSizeF(8 * max(.9, s))
                for text, font, color, y, height in (
                        (title, title_font, "#25282D", 7, 23),
                        (detail, detail_font, "#747981", 31, 20)):
                    painter.setFont(font)
                    painter.setPen(QColor(color))
                    text = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, text_width)
                    painter.drawText(text_x, card_y + round(y * s), text_width, round(height * s),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

            if self.balance_summary and show_card:
                balance_font = QFont("Microsoft YaHei UI")
                balance_font.setPointSizeF(9.0 * max(.8, s))
                painter.setFont(balance_font)
                painter.setPen(QColor("#53616F"))
                text_width = card_width - round(32 * s)
                text = QFontMetrics(balance_font).elidedText(self.balance_summary, Qt.TextElideMode.ElideRight, text_width)
                painter.drawText(card_x + round(16 * s), card_y + card_height - round(31 * s),
                                 text_width, round(23 * s), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            pixmap = self._pet_pixmap()

            # Pixel density changes the backing raster, never the logical size.
            x, y, pw, ph = self._pet_rect()
            painter.save()
            if self.dragging and not self.reduced_motion:
                painter.translate(x + pw / 2, y + ph * .55)
                painter.rotate(self.drag_tilt)
                painter.translate(-x - pw / 2, -y - ph * .55)
            painter.drawPixmap(QRectF(x, y, pw, ph), pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))
            painter.restore()

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._stop_wander()
                self.last_touch_ms = self._now_ms()
                x, y, width, height = self._pet_rect()
                self.drag_fraction = ((.5, .39) if self.perched_edge else
                                      ((event.position().x() - x) / width, (event.position().y() - y) / height))
                self.drag_last_point = event.globalPosition().toPoint()
                self._stop_throw(landing=False)
                self._apply_glove(True)
                self.drag_origin = event.globalPosition().toPoint()
                self.pet_origin = QPoint(self.pet_x, self.pet_y)
                self.dragging = False
                self.drag_trail = DragTrail()
                self.drag_trail.add(time.monotonic(), event.globalPosition().x(), event.globalPosition().y())

        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            if self.drag_origin is not None and self.pet_origin is not None:
                self.drag_trail.add(time.monotonic(), event.globalPosition().x(), event.globalPosition().y())
                if not self.dragging and (event.globalPosition().toPoint() - self.drag_origin).manhattanLength() > 5:
                    self._begin_drag()
                if not self.dragging:
                    return
                point = event.globalPosition().toPoint()
                if self.drag_last_point is not None:
                    self.drag_tilt = max(-12.0, min(12.0, (point.x() - self.drag_last_point.x()) * .25))
                self.drag_last_point = point
                width, height = self._pet_size()
                self._move_to_pet(round(point.x() - self.drag_fraction[0] * width),
                                  round(point.y() - self.drag_fraction[1] * height),
                                  screen_hint=self._screen_for_point(point.x(), point.y()))

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.dragging:
                    now = time.monotonic()
                    self.drag_trail.add(now, event.globalPosition().x(), event.globalPosition().y())
                    vx, vy = self.drag_trail.velocity(now)
                    self._finish_drag()
                    perched = vx == 0 and vy == 0 and self._try_perch()
                    if not perched and not self._start_throw(vx, vy):
                        self._snap_to_edge()
                    self._save_layout()
                else:
                    self._play_click_interaction(event.position().x(), event.position().y())
            self.drag_origin = None
            self.pet_origin = None
            self.dragging = False
            self.drag_tilt = 0
            self.last_touch_ms = self._now_ms()
            # The button state is authoritative: restore the open hand if the
            # pointer is still over the pet, or the default arrow otherwise.
            self.glove.pressed = False
            if self.rect().contains(event.position().toPoint()):
                self._apply_glove(False)
            else:
                reset_native_cursor()

        def _play_click_interaction(self, x: float, y: float) -> None:
            pet_x, pet_y, pet_width, pet_height = self._pet_rect()
            original = manifest.get("originalFrameRect")
            if original:
                pet_x += original[0] * self.scale
                pet_y += original[1] * self.scale
                pet_width, pet_height = original[2] * self.scale, original[3] * self.scale
            relative_x = max(0.0, x - pet_x)
            relative_y = max(0.0, y - pet_y)
            if relative_y < pet_height * 0.45:
                self._play_interaction("head_pat", "摸摸也不能让我少干活哦~")
            elif relative_x > pet_width * 0.72:
                self._play_interaction("tail", "尾巴不是进度条啦！")
            else:
                self._play_interaction("poke", "戳我干嘛，任务还在跑呢")

        def _play_interaction(self, clip_name: str, message: str) -> None:
            self._stop_wander()
            self._leave_perch()
            self.last_touch_ms = self._now_ms()
            previous_frame, previous_clip = self.model.frame, self.model.active_clip_name
            if not self.reduced_motion and not self.model.play_interaction(clip_name, self._now_ms()):
                return
            self._sync_frame_transition(previous_frame, previous_clip)
            self._show_overlay(message, self.status_detail, self.status_state, 1800)
            self._schedule_micro()
            self.update()

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._play_interaction("head_pat", "好啦好啦，知道你喜欢我~")

        def _play_manual_action(self, name: str, *, repeat: bool = False) -> bool:
            action = next((a for a in actions_for(manifest) if a[0] == name), None)
            if action is None:
                return False
            if self.reduced_motion:
                self._show_overlay("先关闭“减少动态”就能看动作啦", self.status_detail, self.status_state, 2500)
                return False
            self._stop_wander()
            self._leave_perch()
            self.last_touch_ms = self._now_ms()
            previous_frame, previous_clip = self.model.frame, self.model.active_clip_name
            if self.throw_motion is not None or not self.model.play_manual_action(name, repeat=repeat):
                self._show_overlay("先处理眼前的任务，等会儿再玩哦", self.status_detail, self.status_state, 2500)
                return False
            self._sync_frame_transition(previous_frame, previous_clip)
            self._show_overlay(action[3], "本地动作 · " + action[1], self.status_state, 2600)
            self._schedule_micro()
            self.update()
            return True

        def _show_control_panel(self, dialog: Any) -> None:
            self._stop_wander()
            screen = self.screen()
            if screen:
                geometry = screen.availableGeometry()
                dialog.resize(min(dialog.width(), geometry.width() - 32),
                              min(dialog.height(), geometry.height() - 64))
            dialog.show()
            if screen:
                frame = dialog.frameGeometry()
                position = panel_position(
                    (frame.width(), frame.height()), geometry.getRect(),
                    self.frameGeometry().getRect(), (self.pet_x, self.pet_y))
                dialog.move(*position)
            dialog.raise_()
            dialog.activateWindow()

        def _open_action_browser(self) -> None:
            if self.settings_dialog is not None:
                self.settings_dialog.close()
            if self.action_browser is None:
                self.action_browser = ActionBrowser(self, manifest)
                self.action_browser.finished.connect(lambda _: setattr(self, "action_browser", None))
            self._show_control_panel(self.action_browser)

        def _open_settings(self) -> None:
            if self.action_browser is not None:
                self.action_browser.close()
            if self.settings_dialog is None:
                self.settings_dialog = PetSettings(self)
                self.settings_dialog.finished.connect(lambda _: setattr(self, "settings_dialog", None))
            self._show_control_panel(self.settings_dialog)

        def _set_preference(self, name: str, value: Any) -> None:
            if name == "reduced_motion":
                self._set_reduced_motion(bool(value))
                emit_reply("settings", reducedMotion=self.reduced_motion)
            elif name in {"scale", "bubble_scale", "perch_scale"}:
                setattr(self, name, value)
                self._apply_window_size()
                self._move_to_pet(self.pet_x, self.pet_y)
                if self.perched_edge:
                    self._refresh_display()
                key = {"scale": "scale", "bubble_scale": "bubbleScale", "perch_scale": "perchScale"}[name]
                emit_reply("settings", **{key: value})
            elif name == "activity_level":
                self.activity_level = value
                self._schedule_micro()
            elif name == "render_profile":
                if value not in {"bright", "natural", "original"}:
                    return
                self.render_profile = value
                self.decoded_frames.clear()
            elif name == "inertia_enabled":
                self.inertia_enabled = bool(value)
                if not value:
                    self._stop_throw()
            elif name == "gravity_enabled":
                self.gravity_enabled = bool(value)
                if self.throw_motion is not None:
                    self.throw_motion.gravity_enabled = self.gravity_enabled
            elif name in {"perch_enabled", "hover_enabled", "wander_enabled"}:
                setattr(self, name, bool(value))
                if name == "perch_enabled" and not value:
                    self._leave_perch()
                if name == "wander_enabled" and not value:
                    self._stop_wander()
                if name == "hover_enabled" and not value:
                    self._set_hover(False, self._now_ms())
            elif name == "edge_snap":
                self.edge_snap = bool(value)
            else:
                return
            self._save_layout()
            self.update()

        def _go_home(self) -> None:
            self._stop_wander()
            self._leave_perch()
            self.last_touch_ms = self._now_ms()
            self._stop_throw(landing=False)
            screen = QApplication.primaryScreen()
            if screen:
                geometry = screen.availableGeometry()
                width, height = self._pet_size()
                self._move_to_pet(geometry.right() - width - 24, geometry.bottom() - height - 24)
                self._save_layout()

        def _build_context_menu(self) -> Any:
            return PetMenu(self)

        def _set_follow_codex(self, enabled: bool) -> None:
            self.follow_codex = enabled
            emit_reply("follow-codex", enabled=enabled)

        def _context_menu_position(self, menu: Any, anchor: Any) -> Any:
            screen = QApplication.screenAt(anchor) or self.screen()
            if not screen:
                return anchor
            size = menu.sizeHint()
            available = screen.availableGeometry()
            x = anchor.x() + 8
            if x + size.width() > available.right() - 8:
                x = anchor.x() - size.width() - 8
            x = min(max(x, available.left() + 8), max(available.left() + 8, available.right() - size.width() - 8))
            y = min(max(anchor.y() - 24, available.top() + 8), max(available.top() + 8, available.bottom() - size.height() - 8))
            return QPoint(x, y)

        def contextMenuEvent(self, event: Any) -> None:
            self._stop_wander()
            self.last_touch_ms = self._now_ms()
            menu = self._build_context_menu()
            self.menu_open = True
            self._update_status_bubble()
            self.update()
            try:
                menu.exec(self._context_menu_position(menu, event.globalPos()))
            finally:
                self.menu_open = False
                self._update_status_bubble()
                self.update()
                menu.deleteLater()

        def _restart_pet(self) -> None:
            if not self.restart_supported or self.restart_pending:
                return
            self.restart_pending = True
            self._save_layout()
            emit_reply("restart")
            QApplication.quit()

        def _close_pet(self) -> None:
            self._save_layout()
            emit_reply("closed", reason="user")
            QApplication.quit()

        def _open_client(self) -> None:
            if not QDesktopServices.openUrl(QUrl(self.webui_url)):
                print("Unable to open the configured client", file=sys.stderr)
                self._show_overlay(f"无法{self.open_label}", "请确认应用已安装、打开地址设置正确", "ERROR", 4000)
                self._sync_bubble_size()
                self.update()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    inbox = Inbox()
    window = CompanionWindow()
    glove_filter = GloveCursorFilter(window, window.glove_open_h, window.glove_closed_h)
    application.installNativeEventFilter(glove_filter)
    inbox.message.connect(window.apply_message)
    inbox.closed.connect(application.quit)

    def read_stdin() -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
                if message.get("kind") == "ping":
                    emit_reply("pong")
                inbox.message.emit(message)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
        try:
            inbox.closed.emit()
        except RuntimeError:
            # The UI may already have been destroyed after a user-initiated exit.
            pass

    reader = threading.Thread(target=read_stdin, name="dsh-bigfish-stdin", daemon=True)
    reader.start()
    window.show()
    window._update_status_bubble()
    window._connect_display_events()
    emit_reply("ready")
    code = application.exec()
    recorder.close()
    return code


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="DSH BigFish native helper")
    parser.add_argument("--headless", action="store_true", help="validate the protocol without opening a window")
    parser.add_argument("--event-log", type=Path, help="append received protocol messages to a JSONL file")
    parser.add_argument("--snapshot", type=Path, help="save one diagnostic visual frame after the first message")
    args = parser.parse_args()
    recorder = EventRecorder(args.event_log)
    return run_headless(recorder) if args.headless else run_visual(recorder, args.snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
