"""Working barriers and delayed UIA reads from the 2026-10-23 incident."""
import json
import queue
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module

CAPACITY = "⚠ Selected model is at capacity. Please try a different model."
WORKING = "◦ Working (5m 33s • esc to interrupt)"


def frame(text):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex task", "text": text}


class SnapshotFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.sender = Mock(return_value=True)
        self.trackers = {}
        self.clock = patch.object(self.module.time, "monotonic", return_value=0.0).start()
        patch.object(self.module, "recovery_input_busy", return_value=False).start()
        patch.object(self.module, "recovery_window_is_alive", return_value=True).start()
        self.addCleanup(patch.stopall)

    def scan(self, text):
        return self.module.process_codex_recovery_snapshots_multi(
            [frame(text)], self.trackers, self.sender)

    def reader(self):
        reader = object.__new__(self.module.CodexTerminalReader)
        reader._responses = queue.Queue(maxsize=1)
        reader._process = Mock()
        reader._process.poll.return_value = None
        reader._scan_in_flight = True
        reader._scan_sent_at = 0.0
        return reader

    def test_delayed_error_is_discarded_then_fresh_working_is_read(self):
        reader = self.reader()
        reader._responses.put(json.dumps([frame(CAPACITY)]))
        self.clock.return_value = 1.0  # e.g. stalled behind the desktop CDP probe
        snapshots = reader.poll()
        self.assertIsNone(snapshots)
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            snapshots, self.trackers, self.sender), [])
        self.assertFalse(reader._scan_in_flight)
        self.assertTrue(reader.request_scan())
        reader._responses.put(json.dumps([frame(CAPACITY + "\n" + WORKING)]))
        self.clock.return_value = 1.1
        snapshots = reader.poll()
        self.assertIsNotNone(snapshots)
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            snapshots, self.trackers, self.sender), [])
        self.assertTrue(self.trackers[901].working_seen)
        self.sender.assert_not_called()

    def test_fresh_persistent_errors_still_retry_until_working(self):
        reader = self.reader()
        for start in (0.0, 3.0, 6.0):
            reader._scan_sent_at = start
            reader._scan_in_flight = True
            reader._responses.put(json.dumps([frame(CAPACITY)]))
            self.clock.return_value = start + 0.1
            self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
                reader.poll(), self.trackers, self.sender), [(901, "model-capacity", True)])
        self.scan(CAPACITY + "\n" + WORKING)
        self.clock.return_value = 20.0
        self.assertEqual(self.scan(CAPACITY), [])
        self.assertEqual(self.sender.call_count, 3)

    def test_partial_nonerror_redraw_cannot_clear_working_barrier(self):
        for partial in ("diff --git a/task.py b/task.py\n+ print(result)",
                        "OpenAI Codex", "Ready"):
            with self.subTest(partial=partial):
                self.trackers.clear()
                self.sender.reset_mock()
                self.scan(CAPACITY)
                self.scan(CAPACITY + "\n" + WORKING)
                self.scan(partial)
                self.clock.return_value += 10.0
                self.assertEqual(self.scan(CAPACITY), [])
                self.sender.assert_called_once_with(901)

    def test_real_idle_composer_can_clear_working_barrier(self):
        self.scan(CAPACITY)
        self.scan(CAPACITY + "\n" + WORKING)
        self.scan("› Ask Codex to do anything\n  82% context left · ? for shortcuts")
        self.clock.return_value = 10.0
        self.assertEqual(self.scan(CAPACITY), [(901, "model-capacity", True)])
        self.assertEqual(self.sender.call_count, 2)

    def test_dropped_stale_snapshot_does_not_clear_esc_barrier(self):
        self.scan("■ Conversation interrupted - tell the model what to do differently.")
        reader = self.reader()
        reader._responses.put(json.dumps([frame(WORKING)]))
        self.clock.return_value = 1.0
        self.module.process_codex_recovery_snapshots_multi(reader.poll(), self.trackers, self.sender)
        self.clock.return_value = 3.0
        self.assertEqual(self.scan(CAPACITY), [])
        self.sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
