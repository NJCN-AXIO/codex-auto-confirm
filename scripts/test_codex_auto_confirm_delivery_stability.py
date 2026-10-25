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
    def test_one_enter_uses_one_character_source_in_translating_message_pump(self):
        module = load_module()
        characters = []

        def translating_post(hwnd, message, wparam, lparam):
            # The real Terminal message pump translates VK_RETURN to WM_CHAR.
            if message in (module.WM_KEYDOWN, module.WM_CHAR) and wparam == module.VK_RETURN:
                characters.append("\r")
            return 1

        self.record_delivery(module, translating_post)
        self.assertTrue(module.send_enter(12345))
        self.assertEqual(characters, ["\r"])

    def test_continue_uses_one_enter_character_source(self):
        module = load_module()
        enters = []
        def translating_post(hwnd, message, wparam, lparam):
            if message in (module.WM_KEYDOWN, module.WM_CHAR) and wparam == module.VK_RETURN:
                enters.append("\r")
            return 1
        self.record_delivery(module, translating_post)
        self.assertTrue(module.send_continue(12345))
        self.assertEqual(enters, ["\r"])

    def test_fallback_uses_one_enter_character_source(self):
        module = load_module()
        enters = []
        def translating_post(hwnd, message, wparam, lparam):
            if message in (module.WM_KEYDOWN, module.WM_CHAR) and wparam == module.VK_RETURN:
                enters.append("\r")
            return 1
        self.record_delivery(module, translating_post)
        with patch.object(module, "send_enter_via_attached_post", return_value=None):
            self.assertTrue(module.send_enter(12345))
        self.assertEqual(enters, ["\r"])

    def test_terminal_fallback_reuses_inputsite_instead_of_pseudoconsole(self):
        module = load_module()
        targets = []
        self.record_delivery(module, lambda hwnd, *args: targets.append(hwnd) or 1)
        with (patch.object(module, "send_enter_via_attached_post", return_value=None),
              patch.object(module, "window_class", return_value="CASCADIA_HOSTING_WINDOW_CLASS"),
              patch.object(module, "find_input_target", return_value=98760) as legacy):
            self.assertTrue(module.send_enter(12345))
        self.assertEqual(targets, [67890, 67890])
        legacy.assert_not_called()

    def test_fallback_failed_keyup_only_releases_without_replaying_enter(self):
        module = load_module()
        messages = []
        def post(hwnd, message, wparam, lparam):
            messages.append(message)
            return len(messages) != 2
        self.record_delivery(module, post)
        with patch.object(module, "send_enter_via_attached_post", return_value=None):
            self.assertFalse(module.send_enter(12345))
        self.assertEqual(messages, [module.WM_KEYDOWN, module.WM_KEYUP, module.WM_KEYUP])

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
            return len(messages) != 2

        self.record_delivery(module, post)
        module.send_enter(12345)
        self.assertEqual(
            [row for row in messages if row[1:] == (module.WM_KEYDOWN, module.VK_RETURN)],
            [(67890, module.WM_KEYDOWN, module.VK_RETURN)],
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
            [ord(char) for char in module.AUTO_CONTINUE_MESSAGE],
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
