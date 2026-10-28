"""Restart the helper under one supervisor without losing mode or the instance lock."""
import argparse
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import codex_companion as companion
from codex_platform import SingleInstance


class RestartTests(unittest.TestCase):
    def test_restart_replaces_old_helper_and_keeps_mode_and_lock(self):
        for initial_follow in (False, True):
            with self.subTest(initial_follow=initial_follow), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                local = root / '.local'
                children = []
                real_popen = subprocess.Popen
                # First helper changes mode, then requests restart. Second helper must
                # receive that changed mode, and exits when the supervisor shuts down.
                def launch(_command, **kwargs):
                    if children:
                        self.assertIsNotNone(children[-1].poll(), 'Old helper is still running')
                    competing = SingleInstance(local / 'companion.lock')
                    try:
                        self.assertFalse(competing.acquire(), 'Instance lock was released during restart')
                    finally:
                        competing.close()
                    first = not children
                    target_follow = not initial_follow
                    script = f"""
import json, sys
first = {first!r}
target_follow = {target_follow!r}
print(json.dumps(dict(kind='ready')), flush=True)
for line in sys.stdin:
    data = json.loads(line)
    if data.get('kind') == 'config' and 'followCodex' in data:
        if first:
            print(json.dumps(dict(kind='follow-codex', enabled=target_follow)), flush=True)
            print(json.dumps(dict(kind='restart')), flush=True)
            break
        if data['followCodex'] != target_follow:
            sys.exit(9)
    if data.get('kind') == 'shutdown':
        break
"""
                    child = real_popen([sys.executable, '-u', '-c', script], **kwargs)
                    children.append(child)
                    return child

                argv = ['codex_companion.py', '--codex-home', str(root), '--duration', '5']
                if not initial_follow:
                    argv.append('--standalone')
                errors = io.StringIO()
                with patch.object(companion, 'ROOT', root), patch.object(sys, 'argv', argv), \
                        patch.object(companion.subprocess, 'Popen', side_effect=launch), \
                        patch.object(companion.signal, 'signal'), patch.object(sys, 'stderr', errors):
                    self.assertEqual(companion.main(), 0, errors.getvalue())
                self.assertEqual(len(children), 2)
                self.assertTrue(all(child.returncode == 0 for child in children))
                available = SingleInstance(local / 'companion.lock')
                try:
                    self.assertTrue(available.acquire(), 'Final shutdown did not release the lock')
                finally:
                    available.close()
                self.assertEqual(errors.getvalue(), '')

    def test_failed_helper_is_not_restarted_even_after_request(self):
        real_popen = subprocess.Popen
        script = "print('{\"kind\":\"ready\"}', flush=True); print('{\"kind\":\"restart\"}', flush=True); raise SystemExit(7)"
        def launch(_command, **kwargs):
            return real_popen([sys.executable, '-u', '-c', script], **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(headless=False, snapshot=None, standalone=True,
                                      demo=False, duration=1, codex_home=root, thread=None)
            with patch.object(companion.subprocess, 'Popen', side_effect=launch), \
                    patch.object(companion.signal, 'signal'), patch.object(sys, 'stderr', io.StringIO()):
                code = companion.run_companion(args, root)
            self.assertNotEqual(code, companion.RESTART_REQUESTED)
            self.assertGreater(code, 0)


if __name__ == '__main__':
    unittest.main()
