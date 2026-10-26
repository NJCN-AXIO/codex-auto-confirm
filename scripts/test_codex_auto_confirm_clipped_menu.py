"""Clipped Action Required menus with a complete permanent-option command scope."""
import textwrap
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module

FOOTER = "Press enter to confirm or esc to cancel"


def clipped(scope, selected="1", footer=True):
    rows = ["› 1. Yes, proceed (y)",
            "  2. Yes, and don't ask again for commands that start with `" + scope + "`"]
    if selected == "2":
        rows = [rows[0].replace("› ", "  "), rows[1].replace("  2.", "› 2.")]
    elif selected == "none":
        rows[0] = rows[0].replace("› ", "  ")
    if footer:
        rows += ["", FOOTER]
    return "\n".join(rows)


def full(command, scope=None):
    return "Would you like to run the following command?\n$ " + command + "\n" + clipped(scope or command)


def shortcut(scope, **fields):
    return clipped(scope, **fields).replace("`" + scope + "`", "`" + scope + "` (p)")


def snapshot(text, hwnd=901):
    return {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": hwnd,
            "title": "[!] Action Required | Codex", "text": text}


class ClippedMenuTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.sender = Mock(return_value=True)
        self.trackers = {}
        self.clock = patch.object(self.module.time, "monotonic", return_value=0.0).start()
        patch.object(self.module, "recovery_input_busy", return_value=False).start()
        self.addCleanup(patch.stopall)

    def scan(self, text, hwnd=901):
        return self.module.process_codex_approval_snapshots_multi(
            [snapshot(text, hwnd)], self.trackers, self.sender)

    def test_new_clipped_long_menu_is_not_blocked_by_previous_request(self):
        scope = 'rtk proxy python -c "exec(bytes.fromhex(\'' + "70617373" * 250 + '\').decode())"'
        wrapped = "\n    ".join(textwrap.wrap(scope, width=110, break_long_words=True))
        self.scan(full("echo FIRST"))
        self.assertEqual(self.scan(clipped(wrapped)), [(901, True)])
        self.assertEqual(self.sender.call_count, 2)

    def test_full_clipped_full_preserve_identity_and_pacing(self):
        self.scan(full("echo FIRST"))
        self.scan(clipped("echo FIRST"))
        self.scan(full("echo FIRST"))
        self.sender.assert_called_once_with(901)

    def test_clipped_to_full_upgrades_identity_without_a_second_first_send(self):
        self.scan(clipped("echo FIRST"))
        self.scan(full("echo FIRST"))
        self.sender.assert_called_once_with(901)
        tracker = self.trackers[901]
        self.assertEqual(tracker.delivery_attempts, 1)
        self.assertEqual(tracker.last_delivery_at, 0.0)

    def test_full_read_missing_scope_still_inherits_the_clipped_delivery(self):
        self.scan(clipped("echo FIRST"))
        partial_full = ("Would you like to run the following command?\n$ echo FIRST\n"
                        "› 1. Yes, proceed (y)\n" + FOOTER)
        self.scan(partial_full)
        self.sender.assert_called_once_with(901)
        self.assertEqual(self.trackers[901].delivery_attempts, 1)

    def test_scope_belongs_to_the_last_selected_menu(self):
        self.scan(clipped("echo FIRST"))
        self.assertEqual(self.scan(clipped("echo FIRST") + "\n" + clipped("echo SECOND")),
                         [(901, True)])
        self.assertEqual(self.sender.call_count, 2)

    def test_clipped_readback_retries_are_bounded_and_need_two_fresh_reads(self):
        for now, expected in ((0, True), (1, False), (2.1, False), (2.4, True),
                              (4.5, False), (4.8, True), (7, False), (7.3, False)):
            self.clock.return_value = now
            self.assertEqual(bool(self.scan(clipped("echo FIRST"))), expected)
        self.assertEqual(self.sender.call_count, 3)

    def test_same_scope_with_two_full_commands_keeps_clipped_reads_ambiguous(self):
        self.scan(full("rtk proxy python FIRST.py", "rtk proxy python"))
        self.scan(full("rtk proxy python SECOND.py", "rtk proxy python"))
        self.clock.return_value = 10
        for _ in range(4):
            self.assertEqual(self.scan(clipped("rtk proxy python")), [])
            self.clock.return_value += 0.3
        self.assertEqual(self.sender.call_count, 2)

    def test_stale_old_clipped_menu_does_not_rearm_after_a_different_scope(self):
        for text in (full("echo FIRST"), clipped("echo SECOND"), clipped("echo FIRST")):
            self.scan(text)
        self.clock.return_value = 10
        for _ in range(3):
            self.scan(clipped("echo FIRST"))
            self.clock.return_value += 0.3
        self.assertEqual(self.sender.call_count, 2)

    def test_incomplete_or_unselected_scope_cannot_authorize_new_identity(self):
        for text in (clipped("echo NEXT").replace("NEXT`", "NEXT"),
                     clipped("echo NEXT", selected="2"),
                     clipped("echo NEXT", selected="none"),
                     clipped("echo NEXT", footer=False)):
            with self.subTest(text=text):
                self.trackers.clear()
                self.sender.reset_mock()
                self.scan(full("echo FIRST"))
                self.assertEqual(self.scan(text), [])
                self.sender.assert_called_once_with(901)

    def test_scope_preserves_case_and_stays_per_window(self):
        self.scan(clipped("echo CaseSensitive"))
        self.scan(clipped("echo casesensitive"))
        self.scan(clipped("echo CaseSensitive"), hwnd=902)
        self.assertEqual(self.sender.call_count, 3)

    def test_reflowed_scope_does_not_create_a_new_request(self):
        scope = "rtk proxy python -c abcdefghijklmnopqrstuvwxyz0123456789"
        self.scan(clipped(scope))
        self.scan(clipped("\n  ".join(textwrap.wrap(scope, width=21))))
        self.sender.assert_called_once_with(901)

    def test_distinct_clipped_requests_with_shortcut_each_receive_enter(self):
        self.assertEqual(self.scan(shortcut("echo FIRST")), [(901, True)])
        self.assertEqual(self.scan(shortcut("echo SECOND")), [(901, True)])
        self.assertEqual(self.scan(shortcut("echo FIRST")), [])
        self.assertEqual(self.sender.call_count, 2)

    def test_shortcut_redraw_and_full_body_keep_one_delivery_and_budget(self):
        command = "echo FIRST"
        self.scan(shortcut(command))
        self.scan(clipped(command))
        self.scan(full(command))
        self.sender.assert_called_once_with(901)
        self.assertEqual(self.trackers[901].delivery_attempts, 1)
        self.assertEqual(self.trackers[901].last_delivery_at, 0.0)
        for now, expected in ((2.1, False), (2.4, True), (4.5, False), (4.8, True),
                              (7.0, False), (7.3, False), (20.0, False)):
            self.clock.return_value = now
            self.assertEqual(bool(self.scan(shortcut(command))), expected)
        self.assertEqual(self.sender.call_count, 3)

    def test_shortcut_scope_wrapping_padding_and_case_remain_stable(self):
        scope = "python -c CaseSensitive0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        wrapped = "\n    ".join(textwrap.wrap(scope, width=19))
        text = "\r\n\r\n".join(line.ljust(129) for line in shortcut(wrapped).splitlines())
        self.scan(full("echo FIRST"))
        self.assertEqual(self.scan(text), [(901, True)])
        self.assertEqual(self.scan(clipped(scope)), [])
        self.assertEqual(self.scan(shortcut(scope.lower())), [(901, True)])
        self.assertEqual(self.sender.call_count, 3)

    def test_shortcut_is_not_part_of_the_command_scope(self):
        scope = "python -c print('(p)')"
        self.assertEqual(self.module._approval_command_scope(shortcut(scope)),
                         self.module._approval_command_scope(clipped(scope)))
        self.assertIn("'(p)'", self.module._approval_command_scope(shortcut(scope)))

    def test_unknown_or_incomplete_shortcut_tails_cannot_identify_a_new_request(self):
        for text in (shortcut("echo NEXT").replace("` (p)", " (p)"),
                     shortcut("echo NEXT").replace("(p)", "(x)"),
                     shortcut("echo NEXT").replace("(p)", "(p) extra"),
                     shortcut("echo NEXT").replace("(p)", "(p"),
                     shortcut("echo NEXT", footer=False),
                     shortcut("echo NEXT", selected="2"),
                     shortcut("echo NEXT", selected="none")):
            with self.subTest(text=text):
                self.trackers.clear()
                self.sender.reset_mock()
                self.scan(full("echo FIRST"))
                self.assertIsNone(self.module._approval_command_scope(text))
                self.assertEqual(self.scan(text), [])
                self.sender.assert_called_once_with(901)

    def test_shortcut_uses_existing_draft_pane_and_activity_guards(self):
        text = shortcut("echo FIRST")
        self.assertEqual(self.scan("› Please explain this menu\n" + text), [])
        self.assertEqual(self.module.process_codex_approval_snapshots_multi(
            [{**snapshot(text), "input_ambiguous": True}], self.trackers, self.sender), [])
        with patch.object(self.module, "recovery_input_busy", return_value=True):
            self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_shortcut_scope_stays_ambiguous_for_two_full_commands(self):
        scope = "python"
        self.scan(full("python FIRST.py", scope))
        self.scan(full("python SECOND.py", scope))
        self.clock.return_value = 10.0
        for _ in range(3):
            self.assertEqual(self.scan(shortcut(scope)), [])
            self.clock.return_value += 0.3
        self.assertEqual(self.sender.call_count, 2)


if __name__ == "__main__":
    unittest.main()
