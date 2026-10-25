"""An unaccepted approval must produce a persistent stall state, without extra input."""
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_approval_readback import frame, load_module


class ApprovalHealthTests(unittest.TestCase):
    def run_loop(self, *, seconds=90, unavailable=False):
        module = load_module()
        clock = [0.0]
        module.running = module.auto_confirm = True
        reader = Mock()
        reader.request_scan.return_value = True
        reader.poll.side_effect = lambda: None if unavailable and clock[0] > 1 else [frame()]
        reader.read_fresh.return_value = [frame()]
        reader.restart.return_value = True
        sender = Mock(return_value=True)
        health = Mock()
        def sleep(duration):
            clock[0] += duration
            if clock[0] >= seconds:
                module.running = False
        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "recovery_window_is_alive", return_value=True),
            patch.object(module, "send_enter", sender),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "find_codex_desktop_window", return_value=None),
            patch.object(module, "record_approval_health", health, create=True),
            patch.object(module, "record_recovery_decision"),
            patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(module.time, "sleep", side_effect=sleep),
        ):
            module.auto_enter_loop()
        return module, reader, sender, health

    def test_exhausted_input_budget_is_reported_without_reauthorizing_enter(self):
        _, reader, sender, health = self.run_loop()
        self.assertEqual(sender.call_count, 3)
        reasons = [state["reason"] for call in health.call_args_list for state in call.args[0]["windows"].values()]
        self.assertIn("input_budget_exhausted", reasons)
        self.assertEqual(reader.restart.call_count, 2)
        self.assertTrue(any(state["state"] == "stalled" for call in health.call_args_list
                            for state in call.args[0]["windows"].values()))

    def test_missing_uia_after_a_pending_approval_is_reported_and_refreshed(self):
        _, reader, sender, health = self.run_loop(unavailable=True)
        sender.assert_called_once_with(901)
        reasons = [state["reason"] for call in health.call_args_list for state in call.args[0]["windows"].values()]
        self.assertIn("uia_unavailable", reasons)
        self.assertEqual(reader.restart.call_count, 2)

    def test_incomplete_text_does_not_clear_pending_or_input_budget(self):
        module = load_module()
        tracker = module.ApprovalPromptTracker()
        tracker.delivery_attempts = 3
        monitor, reader = module.ApprovalHealthMonitor(), Mock()
        with (patch.object(module, "record_approval_health"), patch.object(module, "record_recovery_decision"),
              patch.object(module, "recovery_window_is_alive", return_value=True)):
            monitor.update([frame()], {901: tracker}, reader, now=0.0)
            monitor.update([frame("")], {901: tracker}, reader, now=12.0)
            self.assertEqual(monitor.windows[901]["pending_since"], 0.0)
            self.assertEqual(monitor.windows[901]["state"], "stalled")
            self.assertEqual(tracker.delivery_attempts, 3)
            monitor.update([frame("◦ Working (2s • esc to interrupt)")], {901: tracker}, reader, now=13.0)
            self.assertEqual(monitor.windows[901]["state"], "clear")
            self.assertEqual(tracker.delivery_attempts, 3)

    def test_virtual_eight_hour_stall_retains_diagnostics_and_refresh_limit(self):
        module = load_module()
        tracker = module.ApprovalPromptTracker()
        tracker.delivery_attempts = 3
        monitor, reader = module.ApprovalHealthMonitor(), Mock()
        with (patch.object(module, "record_approval_health") as health,
              patch.object(module, "record_recovery_decision"),
              patch.object(module, "recovery_window_is_alive", return_value=True)):
            for now in (0, 8, 10, 38, 60, 3600, 14400, 28800):
                monitor.update([frame()], {901: tracker}, reader, now=now)
            self.assertEqual(reader.restart.call_count, 2)
            latest = health.call_args.args[0]["windows"][901]
            self.assertEqual(latest["reason"], "input_budget_exhausted")
            self.assertEqual(latest["state"], "stalled")
            self.assertEqual(tracker.delivery_attempts, 3)

    def test_unknown_after_clear_does_not_invent_pending_request(self):
        module = load_module()
        monitor, reader = module.ApprovalHealthMonitor(), Mock()
        with (patch.object(module, "record_approval_health"), patch.object(module, "record_recovery_decision"),
              patch.object(module, "recovery_window_is_alive", return_value=True)):
            monitor.update([frame()], {}, reader, now=0.0)
            monitor.update([frame("Working (1s)")], {}, reader, now=1.0)
            for now in (2.0, 10.0):
                monitor.update([frame("")], {}, reader, now=now)
            self.assertIsNone(monitor.windows[901]["pending_since"])
            self.assertEqual(monitor.windows[901]["state"], "clear")
            reader.restart.assert_not_called()

    def test_ambiguous_working_does_not_clear_pending_or_refresh_budget(self):
        module = load_module()
        monitor, reader = module.ApprovalHealthMonitor(), Mock()
        with (patch.object(module, "record_approval_health"), patch.object(module, "record_recovery_decision"),
              patch.object(module, "recovery_window_is_alive", return_value=True)):
            monitor.update([frame()], {}, reader, now=0.0)
            monitor.windows[901]["reader_refreshes"] = 2
            monitor.update([frame("Working (1s)", input_ambiguous=True)], {}, reader, now=12.0)
            state = monitor.windows[901]
            self.assertEqual(state["pending_since"], 0.0)
            self.assertEqual(state["reader_refreshes"], 2)
            self.assertEqual(state["reason"], "input_ambiguous")
            self.assertEqual(state["state"], "stalled")


if __name__ == "__main__":
    unittest.main()
