"""A live approval overlay must end the preceding native tool-output block."""
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module

MENU = (
    '  Would you like to run the following command?\n'
    '  $ python -c "print(1)"\n'
    '› 1. Yes, proceed (y)\n'
    '  2. Yes, and don\'t ask again for commands that start with `python` (p)\n'
    '  3. No, and tell Codex what to do differently (esc)\n'
    '  Press enter to confirm or esc to cancel\n'
)
HISTORY = '› continue\n• The earlier input was submitted.\n'
TOOL = '• Running python -c "print(1)"\n'


def frame(text, title='Action Required | Codex', **fields):
    return {'class': 'CASCADIA_HOSTING_WINDOW_CLASS', 'hwnd': 901,
            'title': title, 'text': text, **fields}


class ApprovalOverlayOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.sender = Mock(return_value=True)
        self.trackers = {}
        patch.object(self.module, 'recovery_input_busy', return_value=False).start()
        self.addCleanup(patch.stopall)

    def scan(self, text, **fields):
        return self.module.process_codex_approval_snapshots_multi(
            [frame(text, **fields)], self.trackers, self.sender)

    def test_live_menu_after_running_and_submitted_input_confirms(self):
        for history in ('', HISTORY, '› 继续！\n'):
            for glyph in ('•', '◦'):
                for title in ('Codex', 'Action Required | Codex'):
                    with self.subTest(history=history, glyph=glyph, title=title):
                        self.trackers.clear()
                        self.sender.reset_mock()
                        text = history + TOOL.replace('•', glyph) + MENU
                        self.assertTrue(self.module.codex_approval_prompt_visible(text))
                        self.assertFalse(self.module._terminal_draft_visible(text))
                        self.assertEqual(self.scan(text, title=title), [(901, True)])
                        self.sender.assert_called_once_with(901)

    def test_real_uia_blank_padded_crlf_rows_keep_overlay_boundary(self):
        text = '\r\n\r\n'.join(line.ljust(140) for line in (HISTORY + TOOL + MENU).splitlines())
        self.assertEqual(self.scan(text), [(901, True)])

    def test_indented_native_output_or_pasted_menu_is_never_input(self):
        copied = '\n'.join('    ' + line for line in MENU.splitlines())
        for text in (HISTORY + '• Ran print example\n' + copied,
                     HISTORY + TOOL + copied,
                     '› Please explain this menu\n' + MENU,
                     '› Please explain this menu\n' + copied):
            with self.subTest(text=text):
                self.assertFalse(self.module.codex_approval_prompt_visible(text))
                self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_incomplete_or_superseded_overlay_does_not_end_tool_ownership(self):
        variants = [
            MENU.replace('  Press enter to confirm or esc to cancel\n', ''),
            MENU + '› unfinished draft\n',
            MENU + '◦ Working (2s • esc to interrupt)\n',
            MENU.replace('Would you like to run the following command?',
                         'Would you like to run the following command? quoted example'),
        ]
        for tail in variants:
            with self.subTest(tail=tail):
                text = HISTORY + TOOL + tail
                self.assertFalse(self.module.codex_approval_prompt_visible(text))
                self.assertEqual(self.scan(text, title='Codex'), [])
        self.sender.assert_not_called()

    def test_lookahead_cannot_cross_a_live_composer_to_borrow_old_heading(self):
        before, options = MENU.split('› 1.', 1)
        text = HISTORY + TOOL + before + '› Please explain these options\n' + '› 1.' + options
        self.assertFalse(self.module.codex_approval_prompt_visible(text))
        self.assertTrue(self.module._terminal_draft_visible(text))
        self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_old_selected_row_cannot_bridge_a_draft_to_a_second_selection(self):
        before, options = MENU.split('› 1.', 1)
        text = (HISTORY + TOOL + before
                + '› 3. No, and tell Codex what to do differently (esc)\n'
                + '› Please explain these options\n' + '› 1.' + options)
        self.assertFalse(self.module.codex_approval_prompt_visible(text))
        self.assertTrue(self.module._terminal_draft_visible(text))
        self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_non_once_selection_and_sibling_draft_still_block(self):
        for chosen in ('2', '3'):
            text = (HISTORY + TOOL + MENU).replace('› 1.', '  1.').replace('  ' + chosen + '.', '› ' + chosen + '.')
            self.assertEqual(self.scan(text), [])
        text = HISTORY + TOOL + MENU
        self.assertEqual(self.module.process_codex_approval_snapshots_multi(
            [frame(text), frame('› user draft')], self.trackers, self.sender), [])
        self.assertEqual(self.scan(text, input_ambiguous=True), [])
        with patch.object(self.module, 'recovery_input_busy', return_value=True):
            self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_overlay_keeps_existing_readback_delay_and_three_post_limit(self):
        text = HISTORY + TOOL + MENU
        with patch.object(self.module.time, 'monotonic', return_value=0.0) as clock:
            self.assertEqual(self.scan(text), [(901, True)])
            for now, expected in ((1.9, []), (2.0, []), (2.25, [(901, True)]),
                                  (4.25, []), (4.5, [(901, True)]), (7.0, []), (10.0, [])):
                clock.return_value = now
                self.assertEqual(self.scan(text), expected)
        self.assertEqual(self.sender.call_count, 3)


if __name__ == '__main__':
    unittest.main()
