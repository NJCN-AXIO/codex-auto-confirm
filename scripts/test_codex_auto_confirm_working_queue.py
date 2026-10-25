"""Regressions for Working with a queued automatic continuation (2301.png)."""
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module

CAPACITY = "⚠ Selected model is at capacity. Please try a different model."
WORKING = "◦ Working (3m 26s • esc to interrupt)"
QUEUED = ("• Messages to be submitted after next tool call "
          "(press esc to interrupt and send immediately)\n  ↳ 继续！")
COMPOSER = "\n› Ask Codex to do anything\n  gpt-6.1-sol xhigh · ~ · task"


def frame(text, hwnd=901):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": hwnd,
            "title": "Codex task", "text": text}


class WorkingQueueTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.sender = Mock(return_value=True)
        self.trackers = {}
        self.clock = patch.object(self.module.time, "monotonic", return_value=0.0).start()
        patch.object(self.module, "recovery_input_busy", return_value=False).start()
        patch.object(self.module, "recovery_window_is_alive", return_value=True).start()
        self.journal = patch.object(self.module, "record_recovery_decision", create=True).start()
        self.addCleanup(patch.stopall)

    def scan(self, text, **kwargs):
        return self.module.process_codex_recovery_snapshots_multi(
            [frame(text)], self.trackers, self.sender, **kwargs)

    def test_tool_output_warnings_are_not_terminal_failures(self):
        for text in (
            "• Ran rtk proxy python index.py\n  └ completed\n    ⚠ Optional dependency unavailable; using fallback",
            "◦ Running a tool\n  ■ unexpected status 503 Service Unavailable: example output",
            "  ⚠ Optional dependency unavailable; using fallback",
            "  ■ unexpected status 503 Service Unavailable: partial tool output",
            "  " + CAPACITY,
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.module.codex_recovery_error_signature(text + COMPOSER))
                self.assertEqual(self.scan(text + COMPOSER), [])
        self.sender.assert_not_called()

    def test_new_top_level_error_after_tool_output_still_recovers(self):
        text = "• Ran a tool\n  └ finished\n\n" + CAPACITY + COMPOSER
        self.assertEqual(self.scan(text), [(901, "model-capacity", True)])

    def test_queued_continue_blocks_even_if_working_row_is_missing(self):
        self.assertEqual(self.scan(CAPACITY + "\n" + QUEUED + COMPOSER), [])
        self.sender.assert_not_called()

    def test_queue_does_not_clear_a_working_barrier(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + "\n" + WORKING + COMPOSER)
        self.scan(QUEUED + COMPOSER)
        self.clock.return_value = 10.0
        self.assertEqual(self.scan(CAPACITY + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_working_and_queue_together_preserve_the_previous_error_barrier(self):
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                self.trackers.clear()
                self.sender.reset_mock()
                tracker = self.module.ErrorRecoveryTracker()
                def scan(text):
                    if multiple:
                        return self.scan(text)
                    return self.module.process_codex_recovery_snapshots([frame(text)], tracker, self.sender)
                scan(CAPACITY + COMPOSER)
                scan(CAPACITY + "\n" + WORKING + COMPOSER)
                scan(WORKING + "\n" + QUEUED + COMPOSER)
                self.clock.return_value = 10.0
                scan(CAPACITY + COMPOSER)
                self.sender.assert_called_once_with(901)

    def test_loop_rechecks_current_state_before_posting_continue(self):
        module = self.module
        module.running = module.auto_confirm = True
        reader = Mock()
        reader.poll.return_value = [frame(CAPACITY + COMPOSER)]
        reader.read_fresh.return_value = [frame(WORKING + COMPOSER)]
        processor = module.process_codex_recovery_snapshots_multi

        def process(snapshots, trackers, sender=None, **kwargs):
            return processor(snapshots, trackers, sender or self.sender, **kwargs)

        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
            patch.object(module, "process_codex_recovery_snapshots_multi", side_effect=process),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "find_codex_desktop_window", return_value=None),
            patch.object(module.time, "sleep", side_effect=lambda _: setattr(module, "running", False)),
        ):
            module.auto_enter_loop()
        self.sender.assert_not_called()
        reader.read_fresh.assert_called_once_with()

    def test_preflight_working_queue_draft_and_ambiguity_veto_delivery(self):
        for fresh in (
            [frame(WORKING + COMPOSER)], [frame(QUEUED + COMPOSER)],
            [frame(CAPACITY + "\n› unfinished draft")],
            [{**frame(CAPACITY + COMPOSER), "input_ambiguous": True}],
            [frame("Would you like to run the following command?\n› 1. Yes, proceed (y)\n2. No, cancel")],
        ):
            with self.subTest(fresh=fresh):
                self.trackers.clear()
                self.sender.reset_mock()
                self.assertEqual(self.scan(CAPACITY + COMPOSER, readback=lambda: fresh), [])
                self.sender.assert_not_called()
                self.assertEqual(self.trackers[901].delivery_attempts, 0)

    def test_unknown_or_incomplete_preflight_does_not_latch_or_spend_budget(self):
        for fresh in (None, [], [frame(CAPACITY)], [frame(CAPACITY + COMPOSER, hwnd=902)]):
            with self.subTest(fresh=fresh):
                self.trackers.clear()
                self.sender.reset_mock()
                self.assertEqual(self.scan(CAPACITY + COMPOSER, readback=lambda: fresh), [])
                self.sender.assert_not_called()
                self.assertIsNone(self.trackers[901].latched_signature)
                self.assertEqual(self.trackers[901].delivery_attempts, 0)
                self.assertEqual(self.scan(CAPACITY + COMPOSER,
                                          readback=lambda: [frame(CAPACITY + COMPOSER)]),
                                 [(901, "model-capacity", True)])

    def test_fresh_persistent_capacity_keeps_paced_retries(self):
        readback = Mock(return_value=[frame(CAPACITY + COMPOSER)])
        for now, expected in ((0, True), (1, False), (3, True), (6, True)):
            self.clock.return_value = now
            self.assertEqual(bool(self.scan(CAPACITY + COMPOSER, readback=readback)), expected)
        self.assertEqual(self.sender.call_count, 3)
        self.assertEqual(readback.call_count, 3)

    def test_own_continue_echo_requires_its_own_complete_footer(self):
        self.scan(CAPACITY + COMPOSER)
        self.clock.return_value = 3.0
        self.sender.reset_mock()
        partial = CAPACITY + COMPOSER + "\n› 继续！"
        self.assertEqual(self.scan(CAPACITY + COMPOSER, readback=lambda: [frame(partial)]), [])
        self.sender.assert_not_called()
        complete = CAPACITY + "\n› 继续！\n  gpt-6.1-sol xhigh · ~ · task"
        self.assertEqual(self.scan(CAPACITY + COMPOSER, readback=lambda: [frame(complete)]),
                         [(901, "model-capacity", True)])

    def test_authorizing_readback_is_recorded_before_delivery(self):
        def send(hwnd):
            self.assertEqual(self.journal.call_args.args[2], "authorized")
            self.assertEqual(self.journal.call_args.args[4], [frame(CAPACITY + COMPOSER)])
            return True
        self.sender.side_effect = send
        self.scan(CAPACITY + COMPOSER, readback=lambda: [frame(CAPACITY + COMPOSER)])
        self.sender.assert_called_once_with(901)
        self.assertEqual(self.journal.call_args.args[2], "posted")

    def test_preflight_is_target_specific_across_windows(self):
        snapshots = [frame(CAPACITY + COMPOSER), frame(CAPACITY + COMPOSER, hwnd=902)]
        readback = Mock(return_value=[frame(WORKING + COMPOSER), frame(CAPACITY + COMPOSER, hwnd=902)])
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            snapshots, self.trackers, self.sender, readback=readback), [(902, "model-capacity", True)])
        self.sender.assert_called_once_with(902)


class FreshScanTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.reader = object.__new__(self.module.CodexTerminalReader)
        self.reader._scan_in_flight = False

    def test_existing_inflight_request_cannot_be_reused_as_preflight(self):
        self.reader._scan_in_flight = True
        self.reader.request_scan = Mock()
        self.reader.poll = Mock(return_value=[frame(WORKING + COMPOSER)])
        self.assertIsNone(self.reader.read_fresh())
        self.reader.request_scan.assert_not_called()
        self.reader.poll.assert_not_called()

    def test_preflight_requires_a_new_scan_request(self):
        self.reader.request_scan = Mock(return_value=False)
        self.reader.poll = Mock(return_value=[frame(CAPACITY + COMPOSER)])
        self.assertIsNone(self.reader.read_fresh())
        self.reader.poll.assert_not_called()

    def test_new_scan_is_consumed_without_reusing_initial_snapshot(self):
        self.reader.request_scan = Mock(return_value=True)
        values = [frame(WORKING + COMPOSER)]
        self.reader.poll = Mock(side_effect=[None, values])
        clock = [0.0]
        with (
            patch.object(self.module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(self.module.time, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)),
        ):
            self.assertEqual(self.reader.read_fresh(), values)
        self.reader.request_scan.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
