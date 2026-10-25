"""Replay split UIA status rows and consecutive/partial approval reads."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")
CAPACITY = "■ Selected model is at capacity. Please try a different model."


def load_module():
    spec = importlib.util.spec_from_file_location("status_menu_regressions", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(text):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex", "text": "OpenAI Codex\n" + text}


def menu(command):
    return (
        "Would you like to run the following command?\n"
        f"$ {command}\n"
        "› 1. Yes, proceed (y)\n"
        "  2. No, and tell Codex what to do differently (esc)\n"
        "Press enter to confirm or esc to cancel"
    )


class StatusAndMenuRegressionTests(unittest.TestCase):
    def test_split_working_with_blank_ranges_blocks_every_capacity_retry(self):
        module = load_module()
        sender = Mock(return_value=True)
        text = CAPACITY + "\n• Working\n\n⠦\n\n(12s • esc to interrupt)\n› Ask Codex to do anything"
        self.assertTrue(module._working_status_active(text))
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for now in (0.0, 3.0, 6.0):
                with patch.object(module.time, "monotonic", return_value=now):
                    self.assertEqual(module.process_codex_recovery_snapshots_multi(
                        [snapshot(text)], trackers, sender), [])
        sender.assert_not_called()

    def test_two_different_menus_without_a_clear_are_confirmed_independently(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for command in ("echo FIRST", "echo SECOND"):
                self.assertEqual(module.process_codex_approval_snapshots_multi(
                    [snapshot(menu(command))], trackers, sender), [(901, True)])
        self.assertEqual(sender.call_count, 2)

    def test_partial_menu_read_does_not_rearm_the_delivered_menu(self):
        partials = (
            "› 1. Yes, proceed (y)\n  2. No, and tell Codex what to do differently (esc)",
            "Would you like to run the following command?",
            "Press enter to confirm or esc to cancel",
            "",
            menu("echo FIRST").replace("$ echo FIRST\n", ""),
            menu("echo FIRST").replace("$ echo FIRST", "Reason: inspect current version"),
        )
        for partial in partials:
            with self.subTest(partial=partial):
                module = load_module()
                sender = Mock(return_value=True)
                trackers = {}
                with patch.object(module, "recovery_input_busy", return_value=False):
                    for text in (menu("echo FIRST"), partial, menu("echo FIRST")):
                        module.process_codex_approval_snapshots_multi([snapshot(text)], trackers, sender)
                sender.assert_called_once_with(901)

    def test_command_reason_range_loss_does_not_create_a_new_request(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        full = menu("echo FIRST").replace("$ echo FIRST", "Reason: inspect current version\n$ echo FIRST")
        partial = full.replace("Reason: inspect current version\n", "")
        with patch.object(module, "recovery_input_busy", return_value=False):
            for text in (full, partial, full):
                module.process_codex_approval_snapshots_multi([snapshot(text)], trackers, sender)
        sender.assert_called_once_with(901)

    def test_numbered_body_prose_is_not_the_menu_option_boundary(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for command in ("echo FIRST", "echo SECOND"):
                text = menu(command).replace("$ " + command,
                    "Reason: read-only check\n1. No files will be modified\n$ " + command)
                module.process_codex_approval_snapshots_multi([snapshot(text)], trackers, sender)
        self.assertEqual(sender.call_count, 2)

    def test_edit_menu_metadata_loss_does_not_reauthorize_the_menu(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        full = menu("unused").replace(
            "Would you like to run the following command?\n$ unused",
            "Would you like to make the following edits?\nReason: update value\nscripts/a.py\n- old\n+ new")
        with patch.object(module, "recovery_input_busy", return_value=False):
            for text in (full, full.replace("Reason: update value\n", ""), full):
                module.process_codex_approval_snapshots_multi([snapshot(text)], trackers, sender)
        sender.assert_called_once_with(901)

    def test_options_only_action_required_read_does_not_create_new_identity(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        partial = snapshot("› 1. Yes, proceed (y)\n  2. No, and tell Codex what to do differently (esc)")
        partial["title"] = "Action Required - Codex"
        with patch.object(module, "recovery_input_busy", return_value=False):
            for frame in (snapshot(menu("echo FIRST")), partial, snapshot(menu("echo FIRST"))):
                module.process_codex_approval_snapshots_multi([frame], trackers, sender)
        sender.assert_called_once_with(901)

    def test_failed_request_budget_survives_other_menus(self):
        module = load_module()
        sender = Mock(return_value=False)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for index, command in enumerate(("echo FIRST", "echo SECOND") * 5):
                with patch.object(module.time, "monotonic", return_value=float(index)):
                    module.process_codex_approval_snapshots_multi([snapshot(menu(command))], trackers, sender)
        self.assertEqual(sender.call_count, 2 * module.RECOVERY_MAX_ATTEMPTS)

    def test_older_menu_cannot_replay_after_a_newer_menu_without_a_clear(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for command in ("echo FIRST", "echo SECOND", "echo FIRST", "echo SECOND"):
                module.process_codex_approval_snapshots_multi([snapshot(menu(command))], trackers, sender)
        self.assertEqual(sender.call_count, 2)

    def test_authoritative_clear_rearms_the_same_command(self):
        for clear in ("◦ Working (2s • esc to interrupt)",
                      "› Ask Codex to do anything\n  gpt-6.1-sol xhigh · E:\\example-project · Main [default]"):
            with self.subTest(clear=clear):
                module = load_module()
                sender = Mock(return_value=True)
                trackers = {}
                with patch.object(module, "recovery_input_busy", return_value=False):
                    for text in (menu("echo FIRST"), clear, menu("echo FIRST")):
                        module.process_codex_approval_snapshots_multi([snapshot(text)], trackers, sender)
                self.assertEqual(sender.call_count, 2)

    def test_historical_request_text_above_menu_does_not_create_new_identity(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for prefix in ("• Previous output\n", "• Changed previous output\n"):
                module.process_codex_approval_snapshots_multi([snapshot(prefix + menu("echo FIRST"))], trackers, sender)
        sender.assert_called_once_with(901)

    def test_old_working_above_current_menu_does_not_rearm_it(self):
        module = load_module()
        sender = Mock(return_value=True)
        trackers = {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            for prefix in ("", "◦ Working (2s • esc to interrupt)\n", "◦ Working (3s • esc to interrupt)\n"):
                module.process_codex_approval_snapshots_multi(
                    [snapshot(prefix + menu("echo FIRST"))], trackers, sender)
        sender.assert_called_once_with(901)


if __name__ == "__main__":
    unittest.main()
