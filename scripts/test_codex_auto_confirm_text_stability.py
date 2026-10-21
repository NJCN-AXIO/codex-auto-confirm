import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")
CAPACITY_ERROR = "⚠ Selected model is at capacity. Please try a different model."


def load_module():
    spec = importlib.util.spec_from_file_location("codex_text_stability", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(text):
    return {
        "class": "CASCADIA_HOSTING_WINDOW_CLASS",
        "hwnd": 901,
        "title": "Codex",
        "text": text,
    }


class TerminalTextStabilityTests(unittest.TestCase):
    def test_quoted_interruption_in_draft_does_not_latch_user_stop(self):
        module = load_module()
        trackers = {}
        calls = []
        draft = (
            f"{CAPACITY_ERROR}\n› Explain this status:\n"
            "  Conversation interrupted - tell the model what to do differently"
        )
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [snapshot(draft)], trackers, lambda hwnd: calls.append(hwnd) or True), [])
            self.assertFalse(trackers[901].cancellation_seen)
            self.assertEqual(module.process_codex_recovery_snapshots_multi(
                [snapshot(CAPACITY_ERROR + "\n» Ask Codex to do anything")],
                trackers, lambda hwnd: calls.append(hwnd) or True,
            ), [(901, "model-capacity", True)])
        self.assertEqual(calls, [901])

    def test_wrapped_submitted_status_quote_cannot_hide_real_capacity_error(self):
        module = load_module()
        for status in (
            "Working (26s • esc to interrupt)",
            "Compacting context (26s • esc to interrupt)",
        ):
            for extra_rows in (0, 30):
                with self.subTest(status=status, extra_rows=extra_rows):
                    text = (
                        "› 请检查这个显示：\n" + "  补充说明\n" * extra_rows
                        + f"  {status}\n\n"
                        f"• 正在检查。\n{CAPACITY_ERROR}\n\n"
                        "» Ask Codex to do anything\n  gpt-6-astra ultra · project"
                    )
                    calls = []
                    with patch.object(module, "recovery_input_busy", return_value=False):
                        events = module.process_codex_recovery_snapshots_multi(
                            [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
                        )
                    self.assertEqual(events, [(901, "model-capacity", True)])
                    self.assertEqual(calls, [901])

    def test_nested_quote_marker_cannot_hide_unfinished_multiline_draft(self):
        module = load_module()
        for marker in ("›", "»", ">"):
            for nested in (">", "> Ask Codex to do anything"):
                with self.subTest(marker=marker, nested=nested):
                    text = (
                        f"{CAPACITY_ERROR}\n{marker} 我还在输入这段说明\n"
                        f"  {nested}\n  gpt-6.1-sol high · project"
                    )
                    calls = []
                    with patch.object(module, "recovery_input_busy", return_value=False):
                        events = module.process_codex_recovery_snapshots_multi(
                            [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
                        )
                    self.assertEqual(events, [])
                    self.assertEqual(calls, [])
                    self.assertTrue(module._terminal_draft_visible(text))

    def test_independent_indented_status_still_suppresses_recovery(self):
        module = load_module()
        for status in (
            "  Working (26s • esc to interrupt)",
            "  Compacting context (26s • esc to interrupt)",
            "  Working\n    (26s • esc to interrupt)",
        ):
            with self.subTest(status=status):
                calls = []
                with patch.object(module, "recovery_input_busy", return_value=False):
                    events = module.process_codex_recovery_snapshots_multi(
                        [snapshot(CAPACITY_ERROR), snapshot(status)], {},
                        lambda hwnd: calls.append(hwnd) or True,
                    )
                self.assertEqual(events, [])
                self.assertEqual(calls, [])
                self.assertTrue(module._working_status_active(status))

    def test_copied_footer_inside_multiline_draft_cannot_end_input(self):
        module = load_module()
        text = (
            f"{CAPACITY_ERROR}\n›\n  gpt-6.1-sol high · project\n"
            "  这里是我的故障描述还没有写完\n  gpt-6.1-sol high · project"
        )
        calls = []
        with patch.object(module, "recovery_input_busy", return_value=False):
            events = module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
            )
        self.assertEqual(events, [])
        self.assertEqual(calls, [])
        self.assertTrue(module._terminal_draft_visible(text))

    def test_real_footer_with_shortcuts_and_particles_keeps_empty_composer_empty(self):
        module = load_module()
        text = (
            f"{CAPACITY_ERROR}\n›\n\n  gpt-6-astra ultra · project\n"
            "  64% context left\n  ? for shortcuts\n  ⠁  ⢀\n"
        )
        calls = []
        with patch.object(module, "recovery_input_busy", return_value=False):
            events = module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
            )
        self.assertEqual(events, [(901, "model-capacity", True)])
        self.assertEqual(calls, [901])
        self.assertFalse(module._terminal_draft_visible(text))

    def test_placeholder_copy_followed_by_text_is_a_real_multiline_draft(self):
        module = load_module()
        text = (
            f"{CAPACITY_ERROR}\n» Ask Codex to do anything\n"
            "  这段输入还没有完成\n  gpt-6-astra ultra · project"
        )
        calls = []
        with patch.object(module, "recovery_input_busy", return_value=False):
            events = module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
            )
        self.assertEqual(events, [])
        self.assertEqual(calls, [])
        self.assertTrue(module._terminal_draft_visible(text))

    def test_indented_assistant_status_example_cannot_mask_real_error(self):
        module = load_module()
        for status in (
            "Working (26s • esc to interrupt)",
            "Compacting context (26s • esc to interrupt)",
        ):
            for error, signature in (
                (CAPACITY_ERROR, "model-capacity"),
                ("■ unexpected status 503 Service Unavailable", "http-503"),
            ):
                with self.subTest(status=status, error=error):
                    text = (
                        f"• status example:\n  {status}\n{error}\n"
                        "» Ask Codex to do anything\n  gpt-6-astra ultra · project"
                    )
                    calls = []
                    with patch.object(module, "recovery_input_busy", return_value=False):
                        events = module.process_codex_recovery_snapshots_multi(
                            [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
                        )
                    self.assertEqual(events, [(901, signature, True)])
                    self.assertEqual(calls, [901])

    def test_circle_bullet_status_example_cannot_mask_real_error(self):
        module = load_module()
        text = (
            "◦ status example:\n"
            "  Working (26s • esc to interrupt)\n"
            f"{CAPACITY_ERROR}\n"
            "» Ask Codex to do anything\n  gpt-6-astra ultra · project"
        )
        calls = []
        with patch.object(module, "recovery_input_busy", return_value=False):
            events = module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
            )
        self.assertEqual(events, [(901, "model-capacity", True)])
        self.assertEqual(calls, [901])

    def test_indented_assistant_status_with_open_bullet_cannot_mask_real_error(self):
        module = load_module()
        text = (
            "◦ status example:\n  Working (26s • esc to interrupt)\n"
            f"{CAPACITY_ERROR}\n» Ask Codex to do anything\n"
            "  gpt-6-astra ultra · project"
        )
        calls = []
        with patch.object(module, "recovery_input_busy", return_value=False):
            events = module.process_codex_recovery_snapshots_multi(
                [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
            )
        self.assertEqual(events, [(901, "model-capacity", True)])
        self.assertEqual(calls, [901])

    def test_live_status_after_old_error_still_suppresses_recovery(self):
        module = load_module()
        for status in (
            "Working (26s • esc to interrupt)",
            "Compacting context (26s • esc to interrupt)",
        ):
            with self.subTest(status=status):
                text = (
                    f"{CAPACITY_ERROR}\n{status}\n"
                    "» Ask Codex to do anything\n  gpt-6-astra ultra · project"
                )
                calls = []
                with patch.object(module, "recovery_input_busy", return_value=False):
                    events = module.process_codex_recovery_snapshots_multi(
                        [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
                    )
                self.assertEqual(events, [])
                self.assertEqual(calls, [])
                self.assertTrue(module._working_status_active(text))

    def test_unindented_and_bullet_status_keep_priority_over_visible_errors(self):
        module = load_module()
        for status in (
            "■ Working (26s • esc to interrupt)",
            "⠴ Working (26s • esc to interrupt)",
            "Working (26s • esc to interrupt)",
            "◦ Working (26s • esc to interrupt)",
            "Compacting context (26s • esc to interrupt)",
            "• Compacting context (26s • esc to interrupt)",
        ):
            with self.subTest(status=status):
                text = (
                    f"• assistant output\n{status}\n{CAPACITY_ERROR}\n"
                    "» Ask Codex to do anything\n  gpt-6-astra ultra · project"
                )
                calls = []
                with patch.object(module, "recovery_input_busy", return_value=False):
                    events = module.process_codex_recovery_snapshots_multi(
                        [snapshot(text)], {}, lambda hwnd: calls.append(hwnd) or True
                    )
                self.assertEqual(events, [])
                self.assertEqual(calls, [])
                self.assertTrue(module._working_status_active(text))


if __name__ == "__main__":
    unittest.main()
