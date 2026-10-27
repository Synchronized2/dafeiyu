"""Regression coverage for task state tracking and Windows process failures."""
import argparse
import ctypes
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import codex_companion as companion


def row(kind, **payload):
    return {"timestamp": "2026-10-27T01:00:00Z", "type": kind, "payload": payload}


TERMINAL_STATES = {
    "task_complete": "SUCCESS", "task_completed": "SUCCESS", "turn_completed": "SUCCESS",
    "turn_aborted": "IDLE", "task_aborted": "IDLE", "task_cancelled": "IDLE",
    "task_failed": "ERROR", "turn_failed": "ERROR",
}


class TaskStateTests(unittest.TestCase):
    def active_session(self):
        session = companion.Session("chat")
        session.apply(row("event_msg", type="task_started", turn_id="current"))
        session.apply(row("response_item", type="function_call", name="exec_command",
                          call_id="working-tool", arguments="{}"))
        return session

    def test_sync_and_async_questions_wait_until_tool_returns(self):
        for name in ("request_user_input", "request_user_input_async",
                     "functions.request_user_input", "functions.request_user_input_async"):
            with self.subTest(name=name):
                session = self.active_session()
                session.apply(row("response_item", type="function_call", name=name,
                                  call_id="question", arguments="{}"))
                self.assertEqual(session.state, "WAITING")
                session.apply(row("response_item", type="function_call_output", call_id="question"))
                self.assertEqual(session.state, "WORKING")
                session.apply(row("response_item", type="function_call_output", call_id="working-tool"))
                self.assertEqual(session.state, "THINKING")

    def test_question_events_show_waiting(self):
        for name in ("request_user_input", "request_user_input_async", "approval_requested"):
            with self.subTest(name=name):
                session = self.active_session()
                session.apply(row("event_msg", type=name))
                self.assertEqual(session.state, "WAITING")

    def test_old_terminal_events_preserve_current_work(self):
        for event in TERMINAL_STATES:
            with self.subTest(event=event):
                session = self.active_session()
                before = (session.state, session.text, session.updated, dict(session.calls))
                self.assertFalse(session.apply(row("event_msg", type=event, turn_id="previous")))
                self.assertTrue(session.running)
                self.assertEqual((session.state, session.text, session.updated, dict(session.calls)), before)

    def test_current_terminal_events_end_current_work(self):
        for event, expected in TERMINAL_STATES.items():
            with self.subTest(event=event):
                session = self.active_session()
                self.assertTrue(session.apply(row("event_msg", type=event, turn_id="current")))
                self.assertFalse(session.running)
                self.assertEqual(session.state, expected)
                self.assertFalse(session.calls)

    def test_legacy_terminal_events_without_turn_id_still_work(self):
        for event, expected in TERMINAL_STATES.items():
            with self.subTest(event=event):
                session = self.active_session()
                self.assertTrue(session.apply(row("event_msg", type=event)))
                self.assertFalse(session.running)
                self.assertEqual(session.state, expected)


class TaskCountingTests(unittest.TestCase):
    def observe(self, recordings, thread=None):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / 'sessions' / '2026' / '10' / '27'
            directory.mkdir(parents=True)
            for index, rows in enumerate(recordings):
                (directory / f'rollout-chat-{index}.jsonl').write_text(
                    ''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            observer = companion.Observer(home, thread=thread)
            messages = observer.poll(now=companion.event_time('2026-10-27T01:01:00Z'))
            return next(m['tasks'] for m in messages if m['kind'] == 'tasks')

    def recording(self, identity, end=False, offset=0, source='vscode'):
        rows = [row('session_meta', id=identity, cwd='same-project', source=source),
                row('event_msg', type='task_started', turn_id='turn')]
        if end:
            rows.append(row('event_msg', type='task_complete', turn_id='turn'))
        for item in rows:
            stamp = companion.event_time(item['timestamp']) + offset
            item['timestamp'] = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        return rows

    def test_multiple_recordings_of_one_chat_count_once(self):
        tasks = self.observe([self.recording('main'), self.recording('main', offset=1)])
        self.assertEqual([t['sessionId'] for t in tasks], ['main'])

    def test_new_completion_replaces_old_active_recording(self):
        tasks = self.observe([self.recording('main'), self.recording('main', end=True, offset=1)])
        self.assertEqual(tasks, [])

    def test_main_and_guardian_count_as_one_user_task(self):
        tasks = self.observe([self.recording('main'), self.recording('guardian', source={'subagent': {'other': 'guardian'}})])
        self.assertEqual([t['sessionId'] for t in tasks], ['main'])

    def test_distinct_chats_in_same_project_are_kept(self):
        tasks = self.observe([self.recording('first'), self.recording('second')])
        self.assertEqual({t['sessionId'] for t in tasks}, {'first', 'second'})

    def test_inherited_metadata_does_not_change_agent_identity(self):
        session = companion.Session('file')
        session.apply(row('session_meta', id='child', session_id='parent', source={'subagent': {}}))
        session.apply(row('session_meta', id='parent', source='vscode'))
        self.assertEqual(session.id, 'child')
        self.assertTrue(session.is_subagent)

    def test_silent_old_task_is_not_counted_as_running(self):
        tasks = self.observe([self.recording('old', offset=-601)])
        self.assertEqual(tasks, [])


class ProcessExitTests(unittest.TestCase):
    def run_with_helper(self, script, duration=5):
        real_popen = subprocess.Popen
        children = []

        def launch(_command, **kwargs):
            child = real_popen([sys.executable, "-u", "-c", script], **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            args = argparse.Namespace(headless=False, snapshot=None, standalone=True,
                                      demo=False, duration=duration, codex_home=local, thread=None)
            errors = io.StringIO()
            with patch.object(companion.subprocess, "Popen", side_effect=launch), \
                    patch.object(companion.signal, "signal"), patch.object(sys, "stderr", errors):
                code = companion.run_companion(args, local)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll(), "helper must be reaped")
            return code, errors.getvalue()

    def test_ready_helper_crash_propagates_exit_code(self):
        code, diagnostic = self.run_with_helper('''
import json, sys
print('{"kind":"ready"}', flush=True)
for line in sys.stdin:
    if json.loads(line).get('kind') == 'state':
        sys.exit(7)
''')
        self.assertEqual(code, 7)
        self.assertIn("7", diagnostic)
        self.assertIn("helper.log", diagnostic)

    def test_normal_shutdown_stays_successful(self):
        code, diagnostic = self.run_with_helper('''
import json, sys
print('{"kind":"ready"}', flush=True)
for line in sys.stdin:
    if json.loads(line).get('kind') == 'shutdown':
        break
''', duration=0.1)
        self.assertEqual(code, 0)
        self.assertEqual(diagnostic, "")

    def test_startup_failure_stays_failure(self):
        code, diagnostic = self.run_with_helper("import sys; sys.exit(7)")
        self.assertNotEqual(code, 0)
        self.assertIn("helper.log", diagnostic)

    @unittest.skipUnless(sys.platform == "win32", "Windows notification")
    def test_windowless_launcher_notifies_on_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "codex_launcher.pyw"
            launcher.write_text((companion.ROOT / launcher.name).read_text(encoding="utf-8"), encoding="utf-8")
            with patch.dict(sys.modules, {"codex_companion": SimpleNamespace(main=lambda: 7)}), \
                    patch.object(ctypes.windll.user32, "MessageBoxW", return_value=1) as notify, \
                    patch.object(sys, "stdout", io.StringIO()), patch.object(sys, "stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(str(launcher), run_name="__main__")
            self.assertEqual(stopped.exception.code, 7)
            notify.assert_called_once()
            self.assertIn("运行", notify.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
