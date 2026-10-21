"""Posted Enter is not an acknowledgment from a still-visible approval menu."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MENU = (
    "Would you like to run the following command?\n"
    "$ echo CHECK\n"
    "› 1. Yes, proceed (y)\n"
    "  2. No, and tell Codex what to do differently (esc)\n"
    "Press enter to confirm or esc to cancel"
)


def load_module():
    spec = importlib.util.spec_from_file_location("approval_readback", Path(__file__).with_name("codex_auto_confirm.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(text=MENU, **fields):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex", "text": text, **fields}


class ApprovalReadbackTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.trackers = {}
        self.sender = Mock(return_value=True)
        self.clock = patch.object(self.module.time, "monotonic", return_value=0.0).start()
        self.busy = patch.object(self.module, "recovery_input_busy", return_value=False).start()
        patch.object(self.module, "recovery_window_is_alive", return_value=True).start()
        self.addCleanup(patch.stopall)

    def scan(self, now, values):
        self.clock.return_value = now
        return self.module.process_codex_approval_snapshots_multi(values, self.trackers, self.sender)

    def test_unaccepted_post_retries_only_after_two_delayed_menu_readbacks(self):
        self.assertEqual(self.scan(0, [frame()]), [(901, True)])
        for now in (0.25, 1.0, 1.9, 2.0):
            self.assertEqual(self.scan(now, [frame()]), [])
        self.assertEqual(self.scan(2.25, [frame()]), [(901, True)])
        for now in (2.5, 4.5, 8.0):
            self.assertEqual(self.scan(now, [frame("◦ Working (2s • esc to interrupt)")]), [])
        self.assertEqual(self.sender.call_count, 2)

    def test_persisting_menu_has_a_total_post_budget(self):
        for now in (0, 2.0, 2.25, 4.25, 4.5, 6.5, 6.75, 100.0, 100.25):
            self.scan(now, [frame()])
        self.assertEqual(self.sender.call_count, 3)

    def test_large_configured_budget_cannot_exceed_three_total_posts(self):
        self.trackers[901] = self.module.ApprovalPromptTracker(max_delivery_attempts=9)
        for now in (0, 2.0, 2.25, 4.25, 4.5, 6.5, 6.75, 8.75, 9.0):
            self.scan(now, [frame()])
        self.assertEqual(self.sender.call_count, 3)

    def test_configured_short_interval_cannot_bypass_two_second_wait(self):
        self.trackers[901] = self.module.ApprovalPromptTracker(retry_seconds=0.1)
        for now in (0, 1.2, 1.45):
            self.scan(now, [frame()])
        self.sender.assert_called_once_with(901)
        self.assertEqual(self.scan(2.0, [frame()]), [])
        self.assertEqual(self.scan(2.25, [frame()]), [(901, True)])

    def test_no_new_frame_does_not_break_two_actual_readbacks(self):
        self.scan(0, [frame()])
        self.scan(2.0, [frame()])
        self.scan(2.1, None)
        self.assertEqual(self.scan(2.25, [frame()]), [(901, True)])

    def test_incomplete_or_blocked_fresh_reads_break_confirmation_evidence(self):
        for blocked in (
            [], [frame("")], [frame("Would you like to run the following command?")],
            [frame(MENU.replace("$ echo CHECK\n", ""))],
            [frame(input_ambiguous=True)],
            [frame(), frame("› my unfinished draft")],
        ):
            with self.subTest(blocked=blocked):
                self.trackers.clear()
                self.sender.reset_mock()
                self.scan(0, [frame()])
                self.scan(2.0, [frame()])
                self.scan(2.1, blocked)
                self.assertEqual(self.scan(2.25, [frame()]), [])
                self.assertEqual(self.scan(2.5, [frame()]), [(901, True)])
                self.assertEqual(self.sender.call_count, 2)

    def test_physical_input_breaks_confirmation_evidence(self):
        self.scan(0, [frame()])
        self.scan(2.0, [frame()])
        self.busy.return_value = True
        self.scan(2.1, [frame()])
        self.busy.return_value = False
        self.assertEqual(self.scan(2.25, [frame()]), [])
        self.assertEqual(self.scan(2.5, [frame()]), [(901, True)])

    def test_long_observation_gap_requires_two_new_readbacks(self):
        self.scan(0, [frame()])
        self.scan(2.0, [frame()])
        self.assertEqual(self.scan(10.0, [frame()]), [])
        self.assertEqual(self.scan(10.25, [frame()]), [(901, True)])

    def test_new_command_acknowledges_old_request_and_prevents_old_retries(self):
        self.scan(0, [frame()])
        other = frame(MENU.replace("echo CHECK", "echo SECOND"))
        self.assertEqual(self.scan(0.25, [other]), [(901, True)])
        for now, item in ((2.5, frame()), (2.75, frame())):
            self.assertEqual(self.scan(now, [item]), [])
        self.assertEqual(self.sender.call_count, 2)

    def test_historical_menu_cannot_acknowledge_new_pending_request(self):
        other = frame(MENU.replace("echo CHECK", "echo SECOND"))
        self.scan(0, [frame()])
        self.scan(1.0, [other])
        self.assertEqual(self.scan(1.1, [frame()]), [])
        self.assertEqual(self.scan(3.1, [other]), [])
        self.assertEqual(self.scan(3.4, [other]), [(901, True)])
        self.assertEqual(self.sender.call_count, 3)

    def test_title_options_only_cannot_retry_successful_post(self):
        anonymous = frame("› 1. Yes, proceed (y)\n  2. No, and tell Codex what to do differently (esc)",
                          title="Action Required - Codex")
        for now in (0, 2.0, 2.25, 4.5, 4.75):
            self.scan(now, [anonymous])
        self.sender.assert_called_once_with(901)

    def test_readback_status_below_menu_prevents_retry(self):
        self.scan(0, [frame()])
        self.scan(2.0, [frame()])
        self.scan(2.25, [frame(MENU + "\n◦ Working (2s • esc to interrupt)")])
        self.sender.assert_called_once_with(901)


if __name__ == "__main__":
    unittest.main()
