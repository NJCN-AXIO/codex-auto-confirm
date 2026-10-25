"""Regression cases for observation loss and exclusive per-window actions."""

import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load_module():
    path = Path(__file__).with_name("codex_auto_confirm.py")
    spec = importlib.util.spec_from_file_location("codex_state_stability", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPACITY = "Selected model is at capacity. Please try a different model."
MENU = (
    "Would you like to run the following command?\n"
    "  $ rtk git status\n"
    "› 1. Yes, proceed (y)\n"
    "  2. No, and tell Codex what to do differently (esc)"
)
ACTION_REQUIRED_TITLE = "[ ! ] Action Required | Respond to greeting | EXAMPLE-PC"
ACTION_REQUIRED_SELECTED_ONCE_WITHOUT_DENY = (
    "› 1. Yes, proceed (y)\n"
    "  2. Yes, and don't ask again for commands that start with `rtk proxy`\n"
    "\n"
    "  Press enter to confirm or esc to cancel"
)


def snapshot(text, hwnd=901):
    return {
        "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": hwnd,
        "title": "Codex", "text": "OpenAI Codex\n" + text,
    }


class ObservationLossTests(unittest.TestCase):
    def test_working_with_stale_capacity_establishes_a_status_barrier(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        working_with_stale_error = snapshot(
            "Working (26s • esc to interrupt)\n" + CAPACITY
        )
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [working_with_stale_error], trackers, sender
            ), [])
            self.assertTrue(trackers[901].working_seen)
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [snapshot(CAPACITY)], trackers, sender
            ), [])
        sender.assert_not_called()

    def test_split_working_status_with_spinner_still_blocks_capacity_recovery(self):
        module = load_module()
        text = (
            CAPACITY + "\n"
            "Working\n"
            "◦\n"
            "(26s • esc to interrupt)\n"
            "» Ask Codex to do anything"
        )
        sender = Mock(return_value=True)
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertTrue(module._working_status_active(text))
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, sender
            ), [])
        sender.assert_not_called()

    def test_clean_working_readback_rearms_after_stale_status_barrier(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots_multi([
                snapshot("Working (26s • esc to interrupt)\n" + CAPACITY)
            ], trackers, sender), [])
            self.assertEqual(module.process_codex_recovery_snapshots_multi([
                snapshot("Working (27s • esc to interrupt)")
            ], trackers, sender), [])
            self.assertEqual(module.process_codex_recovery_snapshots_multi([
                snapshot(CAPACITY)
            ], trackers, sender), [(901, "model-capacity", True)])
        sender.assert_called_once_with(901)

    def test_missing_approval_snapshot_does_not_rearm_after_success(self):
        for missing in (None, [], [snapshot("Working (2s)", hwnd=902)]):
            with self.subTest(missing=missing):
                module = load_module()
                trackers = {}
                sender = Mock(return_value=True)
                with (
                    patch.object(module, "recovery_input_busy", return_value=False),
                    patch.object(module, "recovery_window_is_alive", return_value=True),
                    patch.object(module.time, "monotonic", return_value=0.0) as clock,
                ):
                    self.assertEqual(module.process_codex_approval_snapshots_multi(
                        [snapshot(MENU)], trackers, sender), [(901, True)])
                    clock.return_value = 0.1
                    module.process_codex_approval_snapshots_multi(missing, trackers, sender)
                    clock.return_value = 0.2
                    self.assertEqual(module.process_codex_approval_snapshots_multi(
                        [snapshot(MENU)], trackers, sender), [])
                    clock.return_value = module.RETRY_ENTER_SECONDS
                    self.assertEqual(module.process_codex_approval_snapshots_multi(
                        [snapshot(MENU)], trackers, sender), [])
                self.assertEqual(sender.call_count, 1)

    def test_failed_approval_delivery_retries_only_within_bounded_budget(self):
        module = load_module()
        trackers = {}
        sender = Mock(side_effect=[False, False, False, True])
        with (
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "recovery_window_is_alive", return_value=True),
            patch.object(module.time, "monotonic", side_effect=[0.0, 0.1, 0.35, 0.7, 1.1]),
        ):
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [(901, False)])
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [])
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [(901, False)])
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [(901, False)])
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [])
        self.assertEqual(sender.call_count, 3)

    def test_observed_approval_clear_still_allows_a_new_menu(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        with (
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "recovery_window_is_alive", return_value=True),
            patch.object(module.time, "monotonic", return_value=0.0),
        ):
            module.process_codex_approval_snapshots_multi([snapshot(MENU)], trackers, sender)
            module.process_codex_approval_snapshots_multi([snapshot("Working (2s)")], trackers, sender)
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [(901, True)])
        self.assertEqual(sender.call_count, 2)

    def test_closed_approval_window_is_pruned(self):
        module = load_module()
        trackers = {901: module.ApprovalPromptTracker()}
        with patch.object(module, "recovery_window_is_alive", return_value=False):
            module.process_codex_approval_snapshots_multi([], trackers, Mock())
        self.assertEqual(trackers, {})

    def test_incomplete_scans_do_not_rearm_one_shot_recovery(self):
        for missing in ([], [snapshot("Working (2s)", hwnd=902)], [{"class": "Other"}]):
            with self.subTest(missing=missing):
                module = load_module()
                trackers = {}
                sender = Mock(return_value=True)
                error = snapshot("■ unexpected status 503 Service Unavailable")
                with (
                    patch.object(module, "recovery_input_busy", return_value=False),
                    patch.object(module, "recovery_window_is_alive", return_value=True),
                ):
                    module.process_codex_recovery_snapshots_multi([error], trackers, sender)
                    for _ in range(module.RECOVERY_MISSING_WINDOW_GRACE_SCANS + 2):
                        module.process_codex_recovery_snapshots_multi(missing, trackers, sender)
                    self.assertEqual(module.process_codex_recovery_snapshots_multi(
                        [error], trackers, sender), [])
                sender.assert_called_once_with(901)

    def test_incomplete_scans_preserve_explicit_cancellation(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        error = snapshot(CAPACITY)
        cancellation = snapshot(CAPACITY + "\nConversation interrupted - tell the model what to do differently")
        with (
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "recovery_window_is_alive", return_value=True),
        ):
            module.process_codex_recovery_snapshots_multi([error], trackers, sender)
            module.process_codex_recovery_snapshots_multi([cancellation], trackers, sender)
            for _ in range(module.RECOVERY_MISSING_WINDOW_GRACE_SCANS + 2):
                module.process_codex_recovery_snapshots_multi(
                    [snapshot("Working (2s)", hwnd=902)], trackers, sender)
            self.assertEqual(module.process_codex_recovery_snapshots_multi([error], trackers, sender), [])
            # A later actual processing read still clears the cancellation.
            module.process_codex_recovery_snapshots_multi([snapshot("Working (3s)")], trackers, sender)
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [error], trackers, sender), [(901, "model-capacity", True)])
        self.assertEqual(sender.call_count, 2)


class ExclusiveWindowActionTests(unittest.TestCase):
    def test_action_required_selected_once_without_visible_deny_is_confirmable(self):
        module = load_module()
        current = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 901,
            "title": ACTION_REQUIRED_TITLE,
            "text": ACTION_REQUIRED_SELECTED_ONCE_WITHOUT_DENY,
        }
        sender = Mock(return_value=True)
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertTrue(module.action_required_options_visible(current["text"]))
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [current], {}, sender
            ), [(901, True)])
        sender.assert_called_once_with(901)

    def test_action_required_selected_permanent_option_stays_blocked_without_deny(self):
        module = load_module()
        current = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 901,
            "title": ACTION_REQUIRED_TITLE,
            "text": (
                "  1. Yes, proceed (y)\n"
                "› 2. Yes, and don't ask again for commands that start with `rtk proxy`\n"
                "\n"
                "  Press enter to confirm or esc to cancel"
            ),
        }
        sender = Mock(return_value=True)
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertFalse(module.action_required_options_visible(current["text"]))
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [current], {}, sender
            ), [])
        sender.assert_not_called()

    def test_approval_defers_recovery_without_consuming_the_error_edge(self):
        module = load_module()
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                tracker = module.ErrorRecoveryTracker()
                trackers = {901: tracker}
                sender = Mock(return_value=True)
                with patch.object(module, "recovery_input_busy", return_value=False):
                    if multiple:
                        result = module.process_codex_recovery_snapshots_multi(
                            [snapshot(CAPACITY + "\n" + MENU)], trackers, sender)
                        self.assertEqual(result, [])
                    else:
                        result = module.process_codex_recovery_snapshots(
                            [snapshot(CAPACITY + "\n" + MENU)], tracker, sender)
                        self.assertEqual(result, (False, None, None))
                    sender.assert_not_called()
                    self.assertIsNone(tracker.latched_signature)
                    self.assertEqual(module.process_codex_recovery_snapshots_multi(
                        [snapshot(CAPACITY)], trackers, sender), [(901, "model-capacity", True)])

    def test_sibling_approval_defers_only_its_window_recovery(self):
        module = load_module()
        sender = Mock(return_value=True)
        with patch.object(module, "recovery_input_busy", return_value=False):
            result = module.process_codex_recovery_snapshots_multi([
                snapshot(CAPACITY), snapshot(MENU), snapshot(CAPACITY, hwnd=902),
            ], {}, sender)
        self.assertEqual(result, [(902, "model-capacity", True)])
        sender.assert_called_once_with(902)

    def test_monitor_performs_only_approval_when_old_error_remains_visible(self):
        module = load_module()
        module.running = True
        module.auto_confirm = True
        reader = Mock()
        reader.poll.return_value = [snapshot(CAPACITY + "\n" + MENU)]
        actions = []
        recovery_processor = module.process_codex_recovery_snapshots_multi

        def record_recovery(snapshots, trackers, **kwargs):
            return recovery_processor(snapshots, trackers, lambda hwnd: actions.append(("continue", hwnd)) or True,
                                      **kwargs)

        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "process_codex_recovery_snapshots_multi", side_effect=record_recovery),
            patch.object(module, "send_enter", side_effect=lambda hwnd: actions.append(("enter", hwnd)) or True),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module.time, "sleep", side_effect=lambda _: setattr(module, "running", False)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            module.auto_enter_loop()
        self.assertEqual(actions, [("enter", 901)])
        reader.close.assert_called_once()

    def test_draft_after_old_error_and_menu_blocks_both_actions(self):
        module = load_module()
        sender = Mock(return_value=True)
        current = snapshot(CAPACITY + "\n" + MENU + "\n\n› I have not finished typing")
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots_multi([current], {}, sender), [])
            self.assertEqual(module.process_codex_approval_snapshots_multi([current], {}, sender), [])
        sender.assert_not_called()


class AmbiguousInputTargetTests(unittest.TestCase):
    def test_single_recovery_defers_ambiguous_target_and_resumes_after_clear(self):
        module = load_module()
        tracker = module.ErrorRecoveryTracker()
        sender = Mock(return_value=True)
        error = snapshot(CAPACITY)
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots(
                [{**error, "input_ambiguous": True}], tracker, sender), (False, None, None))
            sender.assert_not_called()
            self.assertIsNone(tracker.latched_signature)
            self.assertEqual(module.process_codex_recovery_snapshots(
                [{**error, "input_ambiguous": False}], tracker, sender), (True, "model-capacity", True))
        sender.assert_called_once_with(901)

    def test_ambiguous_recovery_window_does_not_block_other_window(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots_multi([
                {**snapshot(CAPACITY), "input_ambiguous": True}, snapshot(CAPACITY, hwnd=902),
            ], trackers, sender), [(902, "model-capacity", True)])
            self.assertEqual(module.process_codex_recovery_snapshots_multi([
                {**snapshot(CAPACITY), "input_ambiguous": False}, snapshot("Working (2s)", hwnd=902),
            ], trackers, sender), [(901, "model-capacity", True)])
        self.assertEqual([call.args[0] for call in sender.call_args_list], [902, 901])

    def test_ambiguous_processing_read_preserves_recovery_cancellation(self):
        module = load_module()
        sender = Mock(return_value=True)
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                tracker = module.ErrorRecoveryTracker()
                tracker.observe_error(None, status_active=True, cancellation_active=True)
                trackers = {901: tracker}
                ambiguous = {**snapshot("Working (2s)"), "input_ambiguous": True}
                with patch.object(module, "recovery_input_busy", return_value=False):
                    if multiple:
                        module.process_codex_recovery_snapshots_multi([ambiguous], trackers, sender)
                    else:
                        module.process_codex_recovery_snapshots([ambiguous], tracker, sender)
                    self.assertTrue(tracker.cancellation_seen)
                    self.assertEqual(module.process_codex_recovery_snapshots_multi(
                        [snapshot(CAPACITY)], trackers, sender), [])
        sender.assert_not_called()

    def test_ambiguous_approval_window_does_not_block_other_window(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_approval_snapshots_multi([
                {**snapshot(MENU), "input_ambiguous": True}, snapshot(MENU, hwnd=902),
            ], trackers, sender), [(902, True)])
            self.assertEqual(module.process_codex_approval_snapshots_multi([
                {**snapshot(MENU), "input_ambiguous": False}, snapshot("Working (2s)", hwnd=902),
            ], trackers, sender), [(901, True)])
        self.assertEqual([call.args[0] for call in sender.call_args_list], [902, 901])

    def test_ambiguous_approval_read_does_not_reset_retry_interval(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        with (
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module.time, "monotonic", return_value=0.0) as clock,
        ):
            module.process_codex_approval_snapshots_multi([snapshot(MENU)], trackers, sender)
            clock.return_value = 0.1
            module.process_codex_approval_snapshots_multi([
                {**snapshot("Working (2s)"), "input_ambiguous": True},
            ], trackers, sender)
            clock.return_value = 0.2
            self.assertEqual(module.process_codex_approval_snapshots_multi(
                [snapshot(MENU)], trackers, sender), [])
        sender.assert_called_once_with(901)

    def test_helper_marks_window_ambiguous_even_if_one_term_cannot_be_read(self):
        module = load_module()
        helper_path = module.UIA_HELPER_SCRIPT_PATH.replace("'", "''")
        # Dot-source the real helper with quit on stdin, then replace only its
        # UIA root with small fake objects. No desktop window is read or changed.
        command = ". '" + helper_path + "'; " + r'''
            $range = [pscustomobject]@{}
            $range | Add-Member ScriptMethod GetText { return "OpenAI Codex" }
            $pattern = [pscustomobject]@{ Ranges = @($range) }
            $pattern | Add-Member ScriptMethod GetVisibleRanges { return $this.Ranges }
            $readable = [pscustomobject]@{ Pattern = $pattern }
            $readable | Add-Member ScriptMethod TryGetCurrentPattern {
                $args[1].Value = $this.Pattern
                return $true
            }
            $unreadable = [pscustomobject]@{}
            $unreadable | Add-Member ScriptMethod TryGetCurrentPattern { return $false }
            $window = [pscustomobject]@{
                Current = [pscustomobject]@{
                    ClassName = "CASCADIA_HOSTING_WINDOW_CLASS"
                    NativeWindowHandle = 901
                    Name = "Codex"
                    ProcessId = 123
                }
                Results = @($readable)
            }
            $window | Add-Member ScriptMethod FindAll { return $this.Results }
            $root = [pscustomobject]@{ Results = @($window) }
            $root | Add-Member ScriptMethod FindAll { return $this.Results }
            $single = @(Read-VisibleSnapshots)
            $window.Results = @($readable, $unreadable)
            $multiple = @(Read-VisibleSnapshots)
            @{single = $single; multiple = $multiple} | ConvertTo-Json -Compress -Depth 5
        '''
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            input=b"quit\n", capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(len(payload["single"]), 1)
        self.assertIs(payload["single"][0].get("input_ambiguous"), False)
        self.assertEqual(len(payload["multiple"]), 1)
        self.assertIs(payload["multiple"][0].get("input_ambiguous"), True)


if __name__ == "__main__":
    unittest.main()
