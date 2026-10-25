"""Single-call MCP permission form reuses the existing approval/recovery owners."""
import unittest
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_approval_readback import MENU, frame, load_module

FORM = '''Field 1/1
Allow the huashu-chrome MCP server to run
tool"read_text"?

format: markdown
scope:tabId:
page1000000001

› 1. Allow
   Run the tool and continue
  2. Allow for this session
   Run the tool and remember this choice for this session.
  3. Always allow
   Run the tool and remember this choice for future tool calls.
  4. Cancel
   Cancel this tool call

enter to submit  esc to cancel
'''
WORKING = '• Working (2s • esc to interrupt)'
EMPTY = '› Ask Codex to do anything\n  gpt-6.1-sol high · 90% left'

class MCPFormTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.trackers, self.sender = {}, Mock(return_value=True)
        self.clock = patch.object(self.module.time, 'monotonic', return_value=0.0).start()
        patch.object(self.module, 'recovery_window_is_alive', return_value=True).start()
        patch.object(self.module, 'recovery_input_busy', return_value=False).start()
        self.addCleanup(patch.stopall)

    def scan(self, text, **fields):
        return self.module.process_codex_approval_snapshots_multi([frame(text, **fields)], self.trackers, self.sender)

    def test_reported_form_and_wrapped_option_confirm_only_single_allow(self):
        for text in (FORM, FORM.replace('› 1. Allow', '› 1.\n Allow')):
            with self.subTest(text=text):
                self.trackers.clear()
                self.assertTrue(self.module.codex_approval_prompt_visible(text))
                self.assertFalse(self.module._terminal_draft_visible(text))
                self.assertEqual(self.scan(text), [(901, True)])

    def test_real_uia_padded_crlf_rows_confirm_the_reported_form(self):
        text = '\r\n'.join(row.ljust(120) for row in FORM.splitlines()) + '\r\n'
        self.assertTrue(self.module.codex_approval_prompt_visible(text))
        self.assertEqual(self.scan(text), [(901, True)])

    def test_session_permanent_cancel_missing_selection_or_incomplete_form_never_send(self):
        for text in [FORM.replace('› 1.', '  1.').replace(f'  {n}.', f'› {n}.') for n in (2,3,4)] + [
            FORM.replace('› 1.', '  1.'), FORM.replace('enter to submit  esc to cancel', ''),
            FORM.replace('  4. Cancel', 'Cancel'), FORM.replace('Field 1/1', 'Field 1/2'),
            FORM.replace('1. Allow\n', '1. Allow for this session\n')]:
            with self.subTest(text=text):
                self.assertFalse(self.module.codex_approval_prompt_visible(text))
                self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_blocked_and_partial_forms_veto_all_recovery_owners(self):
        for form in (FORM.replace('› 1.', '  1.'), FORM.split('  2.')[0],
                     FORM.replace('enter to submit  esc to cancel', ''),
                     FORM.replace('› 1.', '  1.').replace('  3.', '› 3.')):
            text = '■ Model capacity reached\n' + form
            with self.subTest(text=form):
                self.assertTrue(self.module._terminal_draft_visible(text))
                sender = Mock(return_value=True)
                self.module.process_codex_recovery_snapshots([frame(text)], self.module.ErrorRecoveryTracker(), sender)
                self.module.process_codex_recovery_snapshots_multi([frame(text)], {}, sender)
                sender.assert_not_called()

    def test_native_tool_output_or_copied_draft_cannot_authorize_allow(self):
        for text in ('› Here is a copied permission form\n' + FORM,
                     '› 1. Here is a copied permission form\n' + FORM,
                     '› Here is a copied permission form\n' + '\n'.join('  '+r for r in FORM.splitlines()),
                     '• Ran echo example\n' + '\n'.join('  '+r for r in FORM.splitlines())):
            with self.subTest(text=text):
                self.assertFalse(self.module.codex_approval_prompt_visible(text))
                self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_allow_with_extra_suffix_is_never_shortened_to_single_allow(self):
        for suffix in ('  for this session', '  always'):
            text = FORM.replace('› 1. Allow\n', '› 1. Allow'+suffix+'\n')
            with self.subTest(suffix=suffix):
                self.assertFalse(self.module.codex_approval_prompt_visible(text))
                self.assertEqual(self.scan(text), [])
        self.sender.assert_not_called()

    def test_live_form_supersedes_old_menu_and_accepts_exact_inline_description(self):
        for text in (MENU+'\n'+FORM,
                     FORM.replace('Allow\n   Run the tool and continue', 'Allow  Run the tool and continue')):
            self.trackers.clear()
            self.assertEqual(self.scan(text), [(901, True)])

    def test_later_status_composer_or_draft_makes_form_historical(self):
        for tail in (WORKING, EMPTY, '› my unfinished message'):
            with self.subTest(tail=tail):
                self.assertFalse(self.module.codex_approval_prompt_visible(FORM+'\n'+tail))
                self.assertEqual(self.scan(FORM+'\n'+tail), [])

    def test_requests_are_distinct_after_old_command_and_do_not_replay_A_B_A(self):
        self.scan(MENU)
        self.scan(FORM)
        other = FORM.replace('page1000000001', 'page1000000002')
        self.scan(other)
        self.scan(FORM)
        self.assertEqual(self.sender.call_count, 3)
        key = self.module._approval_request_key(FORM)
        self.assertTrue(key)
        for text in (FORM.replace('read_text', 'Read_Text'),
                     FORM.replace('markdown', 'Markdown'),
                     FORM.replace('markdown', '"a  b"'),
                     FORM.replace('markdown', '"a b"')):
            self.assertNotEqual(key, self.module._approval_request_key(text))
        self.assertNotEqual(self.module._approval_request_key(FORM.replace('markdown', '"a  b"')),
                            self.module._approval_request_key(FORM.replace('markdown', '"a b"')))

    def test_existing_readback_delay_three_post_budget_and_unknown_guards_apply(self):
        for now in (0, 2, 2.25, 4.25, 4.5, 10, 10.25):
            self.clock.return_value = now
            self.scan(FORM)
        self.assertEqual(self.sender.call_count, 3)
        tracker = self.trackers[901]
        for text in ('', WORKING+'\n'+FORM.replace('› 1.', '  1.'), FORM.split('  2.')[0]):
            self.scan(text)
            self.assertEqual(tracker.delivery_attempts, 3)
        self.assertFalse(self.module._approval_prompt_cleared(WORKING+'\n'+FORM.replace('› 1.', '  1.')))

    def test_working_above_live_form_does_not_block_and_sibling_draft_does(self):
        self.assertEqual(self.scan(WORKING+'\n'+FORM), [(901, True)])
        self.trackers.clear()
        self.sender.reset_mock()
        self.assertEqual(self.module.process_codex_approval_snapshots_multi(
            [frame(FORM), frame('› unfinished draft')], self.trackers, self.sender), [])
        self.assertEqual(self.scan(FORM, input_ambiguous=True), [])
        self.sender.assert_not_called()

if __name__ == '__main__':
    unittest.main()
