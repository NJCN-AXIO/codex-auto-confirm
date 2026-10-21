"""Delivery regressions; Win32 calls are recorded and never reach real windows."""
import contextlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


def load_module():
    path = Path(__file__).with_name("codex_auto_confirm.py")
    spec = importlib.util.spec_from_file_location("delivery_stability_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeliveryStabilityTests(unittest.TestCase):
    def record_delivery(self, module, post):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(module, "recovery_input_busy", return_value=False))
        resolver = stack.enter_context(patch.object(module, "find_inputsite_target", return_value=67890))
        stack.enter_context(patch.object(module, "find_input_target", return_value=67890))
        stack.enter_context(patch.object(module.user32, "GetWindowThreadProcessId", return_value=1))
        stack.enter_context(patch.object(module.kernel32, "GetCurrentThreadId", return_value=2))
        stack.enter_context(patch.object(module.user32, "PeekMessageW", return_value=0))
        stack.enter_context(patch.object(module.user32, "AttachThreadInput", return_value=1))
        stack.enter_context(patch.object(module.user32, "PostMessageW", side_effect=post))
        return resolver

    def test_enter_keyup_failure_does_not_replay_a_posted_enter(self):
        module = load_module()
        messages = []

        def post(hwnd, message, wparam, lparam):
            messages.append((hwnd, message, wparam))
            return len(messages) != 3

        self.record_delivery(module, post)
        module.send_enter(12345)
        self.assertEqual(
            [row for row in messages if row[1:] == (module.WM_CHAR, module.VK_RETURN)],
            [(67890, module.WM_CHAR, module.VK_RETURN)],
            "A partial delivery must not replay Enter through a fallback",
        )

    def test_continue_text_and_enter_keep_the_same_resolved_target(self):
        module = load_module()
        messages = []
        resolver = self.record_delivery(
            module, lambda hwnd, message, wparam, lparam: messages.append((hwnd, message, wparam)) or 1,
        )
        resolver.side_effect = [67890, 98760]
        self.assertTrue(module.send_continue(12345))
        self.assertEqual({row[0] for row in messages}, {67890})
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(
            [row[2] for row in messages if row[1] == module.WM_CHAR],
            [ord(char) for char in module.AUTO_CONTINUE_MESSAGE] + [module.VK_RETURN],
        )

    def test_failed_continue_character_never_posts_enter(self):
        module = load_module()
        messages = []

        def post(hwnd, message, wparam, lparam):
            messages.append((hwnd, message, wparam))
            return len(messages) != 2

        self.record_delivery(module, post)
        self.assertFalse(module.send_continue(12345))
        self.assertFalse(any(row[2] == module.VK_RETURN for row in messages))


if __name__ == "__main__":
    unittest.main()
