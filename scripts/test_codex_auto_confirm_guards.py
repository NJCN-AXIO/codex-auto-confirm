import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm_guards_target", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutoConfirmGuardTests(unittest.TestCase):
    def _window_fixture(self, module, process_name):
        return (
            patch.object(module.user32, "EnumWindows", side_effect=lambda callback, param: callback(2718, param)),
            patch.object(module.user32, "IsWindowVisible", return_value=1),
            patch.object(module, "window_title", return_value="Action Required | fixture"),
            patch.object(module.user32, "GetWindowThreadProcessId", return_value=1),
            patch.object(module, "window_process_name", return_value=process_name, create=True),
        )

    def test_action_required_rejects_non_codex_host(self):
        module = load_module()
        with contextlib.ExitStack() as stack:
            for active_patch in self._window_fixture(module, "explorer.exe"):
                stack.enter_context(active_patch)
            self.assertEqual(module.find_action_required_window(), (None, ""))

    def test_action_required_accepts_windows_terminal_host(self):
        module = load_module()
        with contextlib.ExitStack() as stack:
            for active_patch in self._window_fixture(module, "WindowsTerminal.exe"):
                stack.enter_context(active_patch)
            self.assertEqual(module.find_action_required_window(), (2718, "Action Required | fixture"))

    def test_loop_reports_enter_delivery_failure(self):
        module = load_module()
        module.running = True
        module.auto_confirm = True
        output = io.StringIO()
        with (
            patch.object(module, "find_action_required_window", return_value=(2718, "Action Required | fixture")),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module, "send_enter", return_value=False),
            patch.object(module.time, "sleep", side_effect=lambda _: setattr(module, "running", False)),
            contextlib.redirect_stdout(output),
        ):
            module.auto_enter_loop()
        self.assertIn("send_enter=failed", output.getvalue())

    def test_loop_does_not_probe_desktop_on_every_recovery_tick(self):
        module = load_module()

        class FakeReader:
            def request_scan(self):
                return True

            def poll(self):
                return None

            def close(self):
                return None

        module.running = True
        module.auto_confirm = True
        desktop_probe = unittest.mock.Mock(return_value=False)
        sleep_calls = 0

        def stop_after_three(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                module.running = False

        with (
            patch.object(module, "CodexTerminalReader", return_value=FakeReader()),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "read_desktop_allow_once", desktop_probe),
            patch.object(module.time, "sleep", side_effect=stop_after_three),
        ):
            module.auto_enter_loop()

        self.assertEqual(desktop_probe.call_count, 1)

    def test_failed_recovery_delivery_does_not_block_the_next_retry_tick(self):
        module = load_module()

        class FakeReader:
            def request_scan(self):
                return True

            def poll(self):
                return None

            def close(self):
                return None

        module.running = True
        module.auto_confirm = True
        sleep_values = []

        def stop_after_two_sleeps(seconds):
            sleep_values.append(seconds)
            if len(sleep_values) >= 2:
                module.running = False

        with (
            patch.object(module, "CodexTerminalReader", return_value=FakeReader()),
            patch.object(module, "process_codex_recovery_snapshots_multi", return_value=[(909, "http-503", False)]),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module.time, "sleep", side_effect=stop_after_two_sleeps),
        ):
            module.auto_enter_loop()

        self.assertLessEqual(sleep_values[0], module.LOOP_SECONDS)

    def test_loop_survives_a_transient_iteration_exception(self):
        module = load_module()

        class FakeReader:
            def request_scan(self):
                return True

            def poll(self):
                return None

            def close(self):
                return None

        module.running = True
        module.auto_confirm = True
        finder_calls = []

        def find_action_required_window():
            finder_calls.append(True)
            if len(finder_calls) == 1:
                raise RuntimeError("transient window enumeration failure")
            return None, ""

        sleep_calls = []

        def stop_after_recovery(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 2:
                module.running = False

        output = io.StringIO()
        with (
            patch.object(module, "CodexTerminalReader", return_value=FakeReader()),
            patch.object(module, "find_action_required_window", side_effect=find_action_required_window),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module.time, "sleep", side_effect=stop_after_recovery),
            contextlib.redirect_stdout(output),
        ):
            module.auto_enter_loop()

        self.assertGreaterEqual(len(finder_calls), 2)
        self.assertIn("iteration error", output.getvalue().lower())

    def test_three_successful_recovery_events_do_not_serialize_with_long_sleep(self):
        module = load_module()

        class FakeReader:
            def request_scan(self):
                return True

            def poll(self):
                return None

            def close(self):
                return None

        module.running = True
        module.auto_confirm = True
        sleep_values = []

        def stop_after_three_sleeps(seconds):
            sleep_values.append(seconds)
            if len(sleep_values) >= 3:
                module.running = False

        with (
            patch.object(module, "CodexTerminalReader", return_value=FakeReader()),
            patch.object(
                module,
                "process_codex_recovery_snapshots_multi",
                return_value=[
                    (916, "http-503", True),
                    (917, "http-503", True),
                    (918, "http-503", True),
                ],
            ),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module.time, "sleep", side_effect=stop_after_three_sleeps),
        ):
            module.auto_enter_loop()

        self.assertTrue(sleep_values)
        self.assertTrue(all(value <= module.LOOP_SECONDS for value in sleep_values[:3]))

    def test_desktop_read_expression_uses_valid_quoted_selectors(self):
        module = load_module()
        expression = module.DESKTOP_READ_EXPRESSION
        self.assertIn('getAttribute("aria-label")', expression)
        self.assertIn('querySelectorAll(\'button,[role="dialog"]\')', expression)
        self.assertNotIn("getAttribute( aria-label)", expression)


if __name__ == "__main__":
    unittest.main()
