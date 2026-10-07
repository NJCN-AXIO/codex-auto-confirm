import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecoveryTextTests(unittest.TestCase):
    def test_default_chinese_when_cjk_present(self):
        mod = load_module()
        # No env override in this subprocess.
        self.assertEqual(
            mod.pick_recovery_text("error: 429 Too Many Requests\n继续执行"),
            "继续执行",
        )

    def test_default_english_when_ascii_only(self):
        mod = load_module()
        self.assertEqual(
            mod.pick_recovery_text("error: 429 Too Many Requests\nretry later"),
            "continue",
        )

    def test_empty_viewport_falls_back_to_english(self):
        mod = load_module()
        self.assertEqual(mod.pick_recovery_text(""), "continue")
        self.assertEqual(mod.pick_recovery_text(None), "continue")

    def test_configured_env_wins(self):
        mod = load_module()
        mod.CONFIGURED_RECOVERY_TEXT = "weiter"
        try:
            self.assertEqual(mod.pick_recovery_text("any text"), "weiter")
        finally:
            mod.CONFIGURED_RECOVERY_TEXT = None

    def test_send_continue_defaults_to_chinese_for_backcompat(self):
        mod = load_module()
        sent = []
        with (
            mock.patch.object(
                mod, "send_text_via_attached_post",
                side_effect=lambda hwnd, text: sent.append(text) or True,
            ),
            mock.patch.object(mod, "send_enter", return_value=True),
        ):
            self.assertTrue(mod.send_continue(123))
        self.assertEqual(sent, ["继续执行"])

    def test_send_continue_uses_passed_text(self):
        mod = load_module()
        sent = []
        with (
            mock.patch.object(
                mod, "send_text_via_attached_post",
                side_effect=lambda hwnd, text: sent.append(text) or True,
            ),
            mock.patch.object(mod, "send_enter", return_value=True),
        ):
            self.assertTrue(mod.send_continue(123, "continue"))
        self.assertEqual(sent, ["continue"])


if __name__ == "__main__":
    unittest.main()
