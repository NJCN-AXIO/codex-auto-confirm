"""Public language and EXE seams around the current approval/recovery owners."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.test_codex_auto_confirm_recovery import load_module

ERROR = '■ unexpected status 503 Service Unavailable'
COMPOSER = '\n› Ask Codex to do anything\n  82% context left · ? for shortcuts'
WORKING = '◦ Working (2s • esc to interrupt)'


def frame(text):
    return {'class': 'CASCADIA_HOSTING_WINDOW_CLASS', 'hwnd': 901,
            'title': 'Codex task', 'text': text}


class ReleaseRegressionTests(unittest.TestCase):
    def test_fresh_default_sender_preserves_language_and_new_error_checkpoint(self):
        for override, expected in ((None, 'continue'), ('weiter', 'weiter')):
            with self.subTest(override=override):
                module = load_module()
                module.CONFIGURED_RECOVERY_TEXT = override
                trackers, sent = {}, []
                with (
                    patch.object(module.time, 'monotonic', return_value=0.0) as clock,
                    patch.object(module, 'recovery_input_busy', return_value=False),
                    patch.object(module, 'record_recovery_decision'),
                    patch.object(module, '_post_messages_via_attached_target',
                                 side_effect=lambda hwnd, messages: sent.append(messages) or True),
                ):
                    def scan(text):
                        snapshots = [frame(text)]
                        return module.process_codex_recovery_snapshots_multi(
                            snapshots, trackers, readback=lambda: snapshots)

                    self.assertTrue(scan(ERROR + COMPOSER))
                    self.assertEqual(''.join(chr(key) for msg, key, _ in sent[0]
                                             if msg == module.WM_CHAR), expected)
                    self.assertEqual([msg for msg, _, _ in sent[0][-2:]],
                                     [module.WM_KEYDOWN, module.WM_KEYUP])
                    self.assertEqual(trackers[901].last_continue_text, expected)
                    continuation = '\n› ' + expected + '\n'
                    self.assertEqual(scan(ERROR + continuation + WORKING + COMPOSER), [])
                    clock.return_value = 3.0
                    self.assertTrue(scan(ERROR + continuation + ERROR + COMPOSER))
                    self.assertEqual(len(sent), 2)
                    # A different language's draft is never this window's own text.
                    other = '继续！' if expected == 'continue' else 'continue'
                    clock.return_value = 6.0
                    self.assertEqual(scan(ERROR + '\n› ' + other), [])
                    self.assertEqual(len(sent), 2)

    def test_frozen_health_and_journal_survive_bundle_cleanup(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {'APPDATA': directory}),
                patch.object(sys, 'frozen', True, create=True),
                patch.object(sys, '_MEIPASS', str(Path(directory) / 'bundle'), create=True),
            ):
                module.record_approval_health({'enabled': True, 'windows': {}})
                module.record_recovery_decision(901, 'http-503', 'preflight', [], [])
                logs = Path(directory) / 'codex-auto-confirm'
                self.assertEqual(json.loads((logs / 'codex-auto-confirm-health.json').read_text()),
                                 {'enabled': True, 'windows': {}})
                row = json.loads((logs / 'codex-recovery-decisions.jsonl').read_text())
                self.assertEqual(row['decision'], 'preflight')
                self.assertFalse((Path(directory) / 'bundle' / 'run_logs').exists())


if __name__ == '__main__':
    unittest.main()
