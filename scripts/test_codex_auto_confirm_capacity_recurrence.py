"""A new capacity failure after the posted continuation is a new retry edge."""
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module

CAPACITY = "⚠ Selected model is at capacity. Please try a different model."
UNAVAILABLE = "■ unexpected status 503 Service Unavailable: No compatible account is available for this model"
WORKING = "◦ Working (2s • esc to interrupt)"
COMPOSER = "\n› Ask Codex to do anything\n  gpt-6.1-sol xhigh · ~ · task"
CONTINUE = "\n› 继续！\n"
CROPPED_SUBMITTED = """› 继续！

⚠ Selected model is at capacity. Please try a different model.

› 继续！

⚠ Selected model is at capacity. Please try a different model.

› 继续！

⚠ Selected model is at capacity. Please try a different model.

› 继续！

⚠ Selected model is at capacity. Please try a different model.

› 继续

• Previous work remains in progress.
"""


def frame(text, hwnd=901):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": hwnd,
            "title": "Codex task", "text": text}


class CapacityRecurrenceTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.sender = Mock(return_value=True)
        self.trackers = {}
        self.clock = patch.object(self.module.time, "monotonic", return_value=0.0).start()
        patch.object(self.module, "recovery_input_busy", return_value=False).start()
        patch.object(self.module, "record_recovery_decision").start()
        self.addCleanup(patch.stopall)

    def scan(self, text, hwnd=901):
        snapshot = frame(text, hwnd)
        return self.module.process_codex_recovery_snapshots_multi(
            [snapshot], self.trackers, self.sender, readback=lambda: [snapshot])

    def test_new_error_after_continue_retries_after_working_with_old_error(self):
        for failure in (CAPACITY, UNAVAILABLE):
            with self.subTest(failure=failure):
                self.trackers.clear()
                self.sender.reset_mock()
                self.clock.return_value = 0
                self.scan(failure + COMPOSER)
                self.scan(failure + CONTINUE + WORKING + COMPOSER)
                again = failure + CONTINUE + failure + COMPOSER
                self.clock.return_value = 1
                self.assertEqual(self.scan(again), [])
                self.clock.return_value = 3
                self.assertEqual(self.scan(again), [(901, self.trackers[901].latched_signature, True)])
                self.assertEqual(self.sender.call_count, 2)

    def test_multiple_failed_continuations_keep_recovering_until_working(self):
        text = CAPACITY
        for attempt in range(4):
            self.clock.return_value = float(attempt * 3)
            self.assertTrue(self.scan(text + COMPOSER))
            text += CONTINUE
            self.assertEqual(self.scan(text + WORKING + COMPOSER), [])
            text += CAPACITY
        self.assertEqual(self.sender.call_count, 4)

    def test_capacity_to_503_after_continue_keeps_the_original_interval(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        again = CAPACITY + CONTINUE + UNAVAILABLE + COMPOSER
        self.clock.return_value = 1
        self.assertEqual(self.scan(again), [])
        self.clock.return_value = 3
        self.assertEqual(self.scan(again), [(901, "http-503", True)])

    def test_error_already_below_continue_when_working_does_not_rearm_on_row_loss(self):
        self.scan(CAPACITY + COMPOSER)
        old = CAPACITY + CONTINUE + CAPACITY
        self.scan(old + "\n" + WORKING + COMPOSER)
        self.clock.return_value = 10
        for _ in range(3):
            self.assertEqual(self.scan(old + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_error_seen_during_working_stays_seen_when_uia_temporarily_omits_it(self):
        self.scan(CAPACITY + COMPOSER)
        old = CAPACITY + CONTINUE + CAPACITY
        self.scan(old + "\n" + WORKING + COMPOSER)
        self.scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.clock.return_value = 10
        self.assertEqual(self.scan(old + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_different_continue_anchor_cannot_release_the_working_barrier(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan("• task A\n" + CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.clock.return_value = 10
        self.assertEqual(self.scan("• task B\n" + CAPACITY + CONTINUE + CAPACITY + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_changed_anchor_during_working_cannot_revalidate_when_original_returns(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan("• task A\n" + CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.scan("• task B\n" + CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.scan("• task A\n" + CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.clock.return_value = 10
        self.assertEqual(self.scan("• task A\n" + CAPACITY + CONTINUE + CAPACITY + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_working_only_sibling_cannot_borrow_a_stale_siblings_checkpoint(self):
        self.scan(CAPACITY + COMPOSER)
        snapshots = [frame(CAPACITY + CONTINUE + COMPOSER), frame(WORKING)]
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            snapshots, self.trackers, self.sender), [])
        self.clock.return_value = 10
        self.assertEqual(self.scan(CAPACITY + CONTINUE + CAPACITY + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_error_already_in_sibling_during_working_cannot_rearm_on_row_loss(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.trackers.clear()
                self.sender.reset_mock()
                self.clock.return_value = 0
                self.scan(CAPACITY + COMPOSER)
                old = CAPACITY + CONTINUE + CAPACITY + COMPOSER
                snapshots = [frame(CAPACITY + CONTINUE + WORKING + COMPOSER), frame(old)]
                if reverse:
                    snapshots.reverse()
                self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
                    snapshots, self.trackers, self.sender), [])
                self.clock.return_value = 10
                self.assertEqual(self.scan(old), [])
                self.sender.assert_called_once_with(901)

    def test_other_working_window_does_not_block_the_repeated_failure(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        snapshots = [frame(CAPACITY + CONTINUE + CAPACITY + COMPOSER),
                     frame(CAPACITY + "\n" + WORKING + COMPOSER, 902)]
        self.clock.return_value = 3
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            snapshots, self.trackers, self.sender, readback=lambda: snapshots),
            [(901, "model-capacity", True)])
        self.assertEqual([call.args[0] for call in self.sender.call_args_list], [901, 901])

    def test_incomplete_preflight_cannot_spend_the_checkpoint(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        checkpoint = self.trackers[901].continuation_checkpoint
        self.clock.return_value = 3
        again = frame(CAPACITY + CONTINUE + CAPACITY + COMPOSER)
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            [again], self.trackers, self.sender, readback=lambda: []), [])
        self.assertEqual(self.trackers[901].continuation_checkpoint, checkpoint)
        self.assertTrue(self.trackers[901].working_seen)
        self.assertEqual(self.scan(again["text"]), [(901, "model-capacity", True)])

    def test_missing_working_checkpoint_does_not_release_stale_capacity(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + "\n" + WORKING + COMPOSER)
        self.clock.return_value = 10
        self.assertEqual(self.scan(CAPACITY + CONTINUE + CAPACITY + COMPOSER), [])
        self.sender.assert_called_once_with(901)

    def test_worked_for_and_esc_do_not_create_a_live_working_checkpoint(self):
        for stop in ("Worked for 2m 3s", "■ Conversation interrupted - tell the model what to do differently."):
            with self.subTest(stop=stop):
                self.trackers.clear()
                self.sender.reset_mock()
                self.scan(CAPACITY + COMPOSER)
                self.scan(CAPACITY + CONTINUE + stop + COMPOSER)
                self.clock.return_value = 20
                self.assertEqual(self.scan(CAPACITY + CONTINUE + CAPACITY + COMPOSER), [])
                self.sender.assert_called_once_with(901)

    def test_queue_and_draft_still_veto_the_new_failure(self):
        self.scan(CAPACITY + COMPOSER)
        self.scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.clock.return_value = 10
        again = CAPACITY + CONTINUE + CAPACITY
        self.assertEqual(self.scan(again + "\n• Messages to be submitted after next tool call" + COMPOSER), [])
        self.assertEqual(self.scan(again + "\n› unfinished draft"), [])
        self.sender.assert_called_once_with(901)

    def test_existing_single_owner_can_recognize_the_same_new_failure(self):
        tracker = self.module.ErrorRecoveryTracker()
        def scan(text):
            snapshot = frame(text)
            return self.module.process_codex_recovery_snapshots(
                [snapshot], tracker, self.sender, readback=lambda: [snapshot])
        scan(CAPACITY + COMPOSER)
        scan(CAPACITY + CONTINUE + WORKING + COMPOSER)
        self.clock.return_value = 3
        self.assertTrue(scan(CAPACITY + CONTINUE + CAPACITY + COMPOSER)[0])
        self.assertEqual(self.sender.call_count, 2)

    def test_cropped_submitted_continue_without_footer_still_retries(self):
        snapshot = frame(CROPPED_SUBMITTED)
        for at in (0, 3, 6, 9, 12, 15):
            self.clock.return_value = at
            events = self.module.process_codex_recovery_snapshots_multi(
                [snapshot], self.trackers, self.sender, readback=lambda: [snapshot])
            self.assertEqual(events, [(901, "model-capacity", True)])
        self.assertEqual(self.sender.call_count, 6)

    def test_cropped_current_draft_still_blocks_retries(self):
        snapshot = frame(CROPPED_SUBMITTED + "\n› 我还没写完")
        self.clock.return_value = 0
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            [snapshot], self.trackers, self.sender, readback=lambda: [snapshot]), [])
        self.assertEqual(self.sender.call_count, 0)

    def test_cropped_submitted_continue_with_uia_decoration_retries(self):
        snapshot = frame(CROPPED_SUBMITTED.replace("› 继续！", "› 继续！⠦"))
        self.clock.return_value = 0
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            [snapshot], self.trackers, self.sender, readback=lambda: [snapshot]),
            [(901, "model-capacity", True)])

    def test_persistent_error_with_no_composer_retries_after_repeated_incomplete_reads(self):
        snapshot = frame(CAPACITY)
        self.clock.return_value = 0
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            [snapshot], self.trackers, self.sender, readback=lambda: [snapshot]), [])
        self.clock.return_value = 3
        self.assertEqual(self.module.process_codex_recovery_snapshots_multi(
            [snapshot], self.trackers, self.sender, readback=lambda: [snapshot]),
            [(901, "model-capacity", True)])


if __name__ == "__main__":
    unittest.main()
