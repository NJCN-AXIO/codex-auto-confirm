"""Public packaging features must survive updates from the installed watchdog."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import autostart
import tray
from pynput import keyboard

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")
AUTH_ERROR = (
    "■ unexpected status 503 Service Unavailable: auth_unavailable: "
    "账号池没有可用账号"
)


def load_module():
    spec = importlib.util.spec_from_file_location("release_integration", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseIntegrationTests(unittest.TestCase):
    def test_503_retries_at_three_seconds_then_respects_working_barrier(self):
        module = load_module()
        trackers = {}
        sender = Mock(return_value=True)
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 927,
            "title": "Codex", "text": "OpenAI Codex\n" + AUTH_ERROR,
        }
        for now, count in ((0.0, 1), (2.9, 1), (3.0, 2), (6.0, 3)):
            with patch.object(module.time, "monotonic", return_value=now):
                module.process_codex_recovery_snapshots_multi([error], trackers, sender)
            self.assertEqual(sender.call_count, count)
        working = {**error, "text": error["text"] + "\nWorking (12s • esc to interrupt)"}
        module.process_codex_recovery_snapshots_multi([working], trackers, sender)
        with patch.object(module.time, "monotonic", return_value=30.0):
            module.process_codex_recovery_snapshots_multi([error], trackers, sender)
        self.assertEqual(sender.call_count, 3)

    def test_auth_pool_draft_cannot_enable_retry_of_an_ordinary_503(self):
        module = load_module()
        text = "■ unexpected status 503 Service Unavailable\n› auth_unavailable"
        self.assertTrue(module._terminal_draft_visible(text))

    def test_historical_auth_error_cannot_enable_retries_for_newer_errors(self):
        for latest, signature in (("■ 429 Too Many Requests", "http-429"),
                                  ("■ a new provider failure", "visible-error")):
            with self.subTest(latest=latest):
                module = load_module()
                tracker = module.ErrorRecoveryTracker()
                sender = Mock(return_value=True)
                error = {
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 927,
                    "title": "Codex", "text": "OpenAI Codex\n" + AUTH_ERROR + "\n" + latest,
                }
                with patch.object(module.time, "monotonic", return_value=0.0):
                    self.assertEqual(module.process_codex_recovery_snapshots([error], tracker, sender),
                                     (True, signature, True))
                with patch.object(module.time, "monotonic", return_value=5.0):
                    self.assertEqual(module.process_codex_recovery_snapshots([error], tracker, sender),
                                     (False, signature, None))
                sender.assert_called_once_with(927)

    def test_explicit_language_uses_one_target_for_text_and_enter(self):
        module = load_module()
        with (
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "_post_messages_via_attached_target", return_value=True) as post,
        ):
            self.assertTrue(module.send_continue(927, "continue"))
        post.assert_called_once()
        hwnd, messages = post.call_args.args
        self.assertEqual(hwnd, 927)
        self.assertEqual("".join(chr(key) for msg, key, _ in messages[:-2]), "continue")
        self.assertEqual([msg for msg, _, _ in messages[-2:]],
                         [module.WM_KEYDOWN, module.WM_KEYUP])

    def test_frozen_helper_uses_extracted_bundle(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", "C:/bundle", create=True):
            module = load_module()
        self.assertEqual(Path(module.UIA_HELPER_SCRIPT_PATH), Path("C:/bundle/codex_terminal_uia_reader.ps1"))

    def test_source_autostart_targets_monitor(self):
        with patch.object(sys, "frozen", False, create=True):
            command = autostart._command_line()
        self.assertIn(str(Path(autostart.__file__).with_name("codex_auto_confirm.py")), command)
        self.assertTrue(command.endswith(" --tray"))

    def test_tray_distinguishes_failed_threads_from_intentional_exit(self):
        for worker_alive, listener_alive, intentional, expected in (
            (False, True, False, 1), (True, False, False, 1), (True, True, True, 0),
        ):
            with self.subTest(worker_alive=worker_alive, listener_alive=listener_alive, intentional=intentional):
                module = load_module()
                worker = Mock()
                worker.is_alive.return_value = worker_alive
                listener = Mock()
                listener.is_alive.return_value = listener_alive

                def run_tray(**kwargs):
                    if intentional:
                        module.running = False
                    self.assertFalse(kwargs["keep_running"]())

                with (
                    patch.object(sys, "argv", [str(MODULE_PATH), "--tray"]),
                    patch.object(module, "_setup_log_tee"),
                    patch.object(module, "acquire_single_instance", return_value=True),
                    patch.object(module, "release_single_instance"),
                    patch.object(module.threading, "Thread", return_value=worker),
                    patch.object(keyboard, "Listener", return_value=listener),
                    patch.object(tray, "run_tray", side_effect=run_tray),
                ):
                    self.assertEqual(module.main(), expected)
                listener.stop.assert_called_once()

    def test_tray_setup_stops_when_health_check_fails(self):
        icon = Mock()
        icon.run.side_effect = lambda *, setup: setup(icon)
        with patch("pystray.Icon", return_value=icon):
            tray.run_tray(
                is_on=lambda: True, toggle=lambda: None,
                is_autostart=lambda: False, set_autostart=lambda on: None,
                shutdown=lambda: None, keep_running=lambda: False,
            )
        icon.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
