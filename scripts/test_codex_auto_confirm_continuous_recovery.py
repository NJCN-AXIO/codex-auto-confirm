"""Regression cases for the 2026-10-22 capacity/503 recovery incidents."""
import unittest
from unittest.mock import patch

from scripts.test_codex_auto_confirm_recovery import load_module

CAPACITY = "⚠ Selected model is at capacity. Please try a different model."
UNAVAILABLE = ("■ unexpected status 503 Service Unavailable: No compatible account "
               "is available for this model, url: http://localhost:57119/v1/responses")


def snapshot(text, hwnd=951):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": hwnd,
            "title": "Windows Terminal", "text": text}


class ContinuousRecoveryTests(unittest.TestCase):
    def test_both_windows_retry_successes_and_failures_until_working(self):
        for delivered in (True, False):
            with self.subTest(delivered=delivered):
                mod = load_module()
                trackers = {hwnd: mod.ErrorRecoveryTracker() for hwnd in (951, 952)}
                for tracker in trackers.values():
                    tracker.semantic_retry_seconds = 3.0
                    tracker.delivery_retry_seconds = 3.0
                    tracker.max_delivery_attempts = 1
                calls = []
                sender = lambda hwnd: calls.append(hwnd) or delivered
                errors = [snapshot(CAPACITY + "\n› "), snapshot(UNAVAILABLE + "\n› ", 952)]
                for now in (0.0, 3.0, 6.0, 9.0):
                    with patch.object(mod.time, "monotonic", return_value=now):
                        self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                            errors, trackers, sender),
                            [(951, "model-capacity", delivered), (952, "http-503", delivered)])
                working = snapshot("◦ Working (12s • esc to interrupt)\n" + CAPACITY + "\n› ")
                with patch.object(mod.time, "monotonic", return_value=12.0):
                    self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                        [working, errors[1]], trackers, sender), [(952, "http-503", delivered)])
                self.assertEqual(calls, [951, 952] * 4 + [952])

    def test_capacity_followed_by_503_keeps_original_retry_interval(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 3.0
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        for now, text, expected in ((0.0, CAPACITY, True), (1.0, UNAVAILABLE, False),
                                    (3.0, UNAVAILABLE, True), (6.0, CAPACITY, True)):
            with patch.object(mod.time, "monotonic", return_value=now):
                result = mod.process_codex_recovery_snapshots([snapshot(text + "\n› ")], tracker, sender)
                self.assertEqual(result[0], expected)
        self.assertEqual(calls, [951] * 3)

    def test_single_entry_checks_later_status_sibling_before_sending(self):
        mod = load_module()
        calls = []
        error = snapshot(CAPACITY + "\n› ")
        status = snapshot("◦ Working (12s • esc to interrupt)")
        for siblings in ([error, status], [status, error]):
            self.assertEqual(mod.process_codex_recovery_snapshots(
                siblings, mod.ErrorRecoveryTracker(), lambda hwnd: calls.append(hwnd) or True),
                (False, None, None))
        self.assertEqual(calls, [])

    def test_working_split_across_four_ranges_stops_pending_retries(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        mod.process_codex_recovery_snapshots([snapshot(CAPACITY)], tracker, sender)
        working = snapshot(CAPACITY + "\n◦ Working\n⠦\n(\n12s • esc to interrupt)\n› ")
        self.assertEqual(mod.process_codex_recovery_snapshots([working], tracker, sender),
                         (False, None, None))
        self.assertEqual(mod.process_codex_recovery_snapshots([snapshot(CAPACITY)], tracker, sender),
                         (False, "model-capacity", None))
        self.assertEqual(calls, [951])

    def test_split_working_with_intervening_prose_is_not_status(self):
        mod = load_module()
        self.assertFalse(mod._working_status_active("Working\nordinary explanation\n(12s)"))

    def test_own_continue_draft_does_not_block_follow_up_retry(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 3.0
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        first = snapshot(CAPACITY + "\n› ")
        own_draft = snapshot(CAPACITY + "\n› 继续！")
        with patch.object(mod.time, "monotonic", return_value=0.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [first], {951: tracker}, sender), [(951, "model-capacity", True)])
        with patch.object(mod.time, "monotonic", return_value=3.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [own_draft], {951: tracker}, sender), [(951, "model-capacity", True)])
        self.assertEqual(calls, [951, 951])

    def test_worked_for_duration_is_terminal_and_blocks_capacity(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        text = "Worked for 2m 27s\n" + CAPACITY + "\n› "
        self.assertTrue(mod._working_status_active(text))
        self.assertEqual(mod.process_codex_recovery_snapshots(
            [snapshot(text)], tracker, lambda hwnd: calls.append(hwnd) or True),
            (False, None, None))
        self.assertEqual(calls, [])

    def test_worked_for_allows_known_ui_decoration_suffix(self):
        mod = load_module()
        self.assertTrue(mod._working_status_active(
            "Worked for 2m 27s •\n" + CAPACITY + "\n› "
        ))

    def test_historical_worked_for_does_not_mask_new_capacity(self):
        mod = load_module()
        history = "Worked for 2m 27s\n" + ("historical output\n" * 60)
        text = history + CAPACITY + "\n› "
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        self.assertFalse(mod._working_status_active(text))
        self.assertEqual(mod.process_codex_recovery_snapshots(
            [snapshot(text)], tracker, lambda hwnd: calls.append(hwnd) or True),
            (True, "model-capacity", True))
        self.assertEqual(calls, [951])

    def test_historical_worked_for_with_blank_gap_does_not_mask_new_capacity(self):
        mod = load_module()
        text = "Worked for 2m 27s" + ("\n" * 60) + CAPACITY + "\n› "
        self.assertFalse(mod._working_status_active(text))

    def test_same_text_typed_later_is_still_a_user_draft(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 3.0
        sender = lambda hwnd: True
        first = snapshot(CAPACITY + "\n› ")
        with patch.object(mod.time, "monotonic", return_value=0.0):
            mod.process_codex_recovery_snapshots([first], tracker, sender)
        later = snapshot(CAPACITY + "\n› 继续！")
        with patch.object(mod.time, "monotonic", return_value=20.0):
            self.assertEqual(mod.process_codex_recovery_snapshots(
                [later], tracker, sender), (False, None, None))

    def test_own_continue_draft_with_braille_echo_does_not_block_retry(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 3.0
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        first = snapshot(CAPACITY + "\n› ")
        echo = snapshot(CAPACITY + "\n› 继续！⠦")
        with patch.object(mod.time, "monotonic", return_value=0.0):
            mod.process_codex_recovery_snapshots_multi([first], {951: tracker}, sender)
        with patch.object(mod.time, "monotonic", return_value=3.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [echo], {951: tracker}, sender), [(951, "model-capacity", True)])
        self.assertEqual(calls, [951, 951])


if __name__ == "__main__":
    unittest.main()
