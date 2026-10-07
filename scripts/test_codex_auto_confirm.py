import ctypes
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")
BATCH_PATH = MODULE_PATH.with_suffix(".bat")


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutoConfirmTests(unittest.TestCase):
    def test_inline_approval_matches_codex_015x_tui_copy(self):
        mod = load_module()
        self.assertTrue(mod.codex_approval_prompt_visible(
            "OpenAI Codex (v0.156.1)\n"
            "Would you like to run the following command?\n"
            "1. Yes, proceed (y)\n"
            "2. No, continue without running it (n)"
        ))
        self.assertTrue(mod.codex_approval_prompt_visible(
            "Would you like to make the following edits?\nYes, proceed"
        ))

    def test_inline_approval_rejects_stale_or_persistent_options(self):
        mod = load_module()
        self.assertFalse(mod.codex_approval_prompt_visible(
            "Would you like to run the following command?\n"
            "Yes, and don't ask again for commands that start with `git`"
        ))
        self.assertFalse(mod.codex_approval_prompt_visible(
            "› explain why Would you like to run the following command?\nYes, proceed"
        ))
        self.assertFalse(mod.codex_approval_prompt_visible(
            "- Would you like to run the following command?\n"
            "- Yes, proceed"
        ))

    def test_transcript_reference_does_not_make_codex_snapshot_ineligible(self):
        mod = load_module()
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 123,
            "title": "diagnose CODEX CLI | my-laptop",
            "text": "The transcript mentions codex_auto_confirm.py",
        }
        self.assertTrue(mod.eligible_codex_snapshot(snapshot))

    def test_new_edit_approval_without_codex_title_is_eligible(self):
        mod = load_module()
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 456,
            "title": "my-project - Windows Terminal",
            "text": (
                "Would you like to make the following edits?\n"
                "Description: Apply proposed file edits\n"
                "Destination: my-project/.git/info\nexclude\n"
                "1. Yes, proceed (y)2. Yes, and don't ask again for these files (a)"
                "3. No, and tell Codex what to do differently (esc)"
            ),
        }
        self.assertTrue(mod.eligible_codex_snapshot(snapshot))
        sent = []
        trackers = {}
        events = mod.process_codex_approval_snapshots_multi(
            [snapshot], trackers, lambda hwnd: sent.append(hwnd) or True
        )
        self.assertEqual(events, [(456, True)])
        self.assertEqual(sent, [456])

    def test_inline_approval_tracker_is_per_window_and_edge_triggered(self):
        mod = load_module()
        trackers = {}
        snapshots = [
            {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 101,
             "title": "Codex CLI", "text": "Would you like to run the following command?\n1. Yes, proceed"},
            {"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 102,
             "title": "Codex CLI", "text": "Would you like to run the following command?\n1. Yes, proceed"},
        ]
        sent = []
        sender = lambda hwnd: sent.append(hwnd) or True
        self.assertEqual(mod.process_codex_approval_snapshots_multi(snapshots, trackers, sender), [(101, True), (102, True)])
        self.assertEqual(mod.process_codex_approval_snapshots_multi(snapshots, trackers, sender), [])
        self.assertEqual(sent, [101, 102])

    def test_desktop_allow_once_semantics_are_positive_only(self):
        mod = load_module()
        self.assertTrue(mod.desktop_allow_once_visible([{"text": "允许一次", "visible": True}]))
        self.assertTrue(mod.desktop_allow_once_visible([{"text": "Allow once", "visible": True}]))
        self.assertFalse(mod.desktop_allow_once_visible([{"text": "拒绝", "visible": True}]))
        self.assertFalse(mod.desktop_allow_once_visible([{"text": "始终允许", "visible": True}]))
        self.assertFalse(mod.desktop_allow_once_visible([{"text": "允许一次", "visible": False}]))

    def test_desktop_approval_tracker_retries_and_clears(self):
        mod = load_module(); tracker = mod.DesktopApprovalTracker(retry_seconds=1.5)
        self.assertTrue(tracker.observe(True, now=10.0)); self.assertFalse(tracker.observe(True, now=11.0)); self.assertTrue(tracker.observe(True, now=11.5)); self.assertFalse(tracker.observe(False, now=11.6)); self.assertTrue(tracker.observe(True, now=12.0))

    def test_desktop_target_filter_accepts_only_codex_pages(self):
        mod = load_module(); targets = [{"type":"page","title":"Codex","webSocketDebuggerUrl":"ws://one"},{"type":"page","title":"Other","webSocketDebuggerUrl":"ws://two"},{"type":"service_worker","title":"Codex","webSocketDebuggerUrl":"ws://three"}]
        self.assertEqual(mod.codex_page_targets(targets), [targets[0]])

    def test_desktop_readback_fails_closed(self):
        mod = load_module()
        with patch.object(mod, "discover_cdp_targets", side_effect=OSError("offline")):
            self.assertFalse(mod.read_desktop_allow_once(27374, 0.1))
    def test_find_input_target_prefers_pseudoconsole_window(self):
        mod = load_module()
        original_enum_windows = mod.user32.EnumWindows
        original_enum_children = mod.user32.EnumChildWindows
        original_get_window = mod.user32.GetWindow
        original_class = mod.window_class
        try:
            classes = {11: "Windows.UI.Input.InputSite.WindowClass", 22: "PseudoConsoleWindow"}
            mod.window_class = lambda hwnd: classes.get(hwnd, "")
            mod.user32.GetWindow = lambda hwnd, command: 99 if hwnd == 22 and command == mod.GW_OWNER else 0
            mod.user32.EnumWindows = lambda callback, lparam: callback(22, lparam)
            mod.user32.EnumChildWindows = lambda parent, callback, lparam: callback(11, lparam)

            self.assertEqual(mod.find_input_target(99), 22)
        finally:
            mod.user32.EnumWindows = original_enum_windows
            mod.user32.EnumChildWindows = original_enum_children
            mod.user32.GetWindow = original_get_window
            mod.window_class = original_class

    def test_send_enter_uses_input_child_resolver(self):
        mod = load_module()
        calls = []
        original_post_message = mod.user32.PostMessageW
        try:
            mod.find_input_target = lambda hwnd: 67890
            mod.send_enter_via_input = lambda hwnd: False
            mod.user32.PostMessageW = lambda hwnd, message, wparam, lparam: calls.append((hwnd, message, wparam, lparam)) or 1

            self.assertTrue(mod.send_enter(12345))
            self.assertTrue(calls)
            self.assertTrue(all(call[0] == 67890 for call in calls))
        finally:
            mod.user32.PostMessageW = original_post_message

    def test_input_structure_matches_win32_size(self):
        mod = load_module()
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(mod.INPUT), expected)

    def test_send_enter_prefers_attached_inputsite_delivery(self):
        mod = load_module()
        calls = []
        mod.send_enter_via_attached_post = lambda hwnd: calls.append(("attached", hwnd)) or True

        self.assertTrue(mod.send_enter(12345))
        self.assertEqual(calls, [("attached", 12345)])

    def test_send_enter_posts_to_target_without_stealing_foreground(self):
        mod = load_module()
        calls = []
        original_show_window = mod.user32.ShowWindow
        original_set_foreground_window = mod.user32.SetForegroundWindow
        original_keybd_event = mod.user32.keybd_event
        original_post_message = mod.user32.PostMessageW
        original_sleep = mod.time.sleep
        try:
            mod.user32.ShowWindow = lambda hwnd, flag: calls.append(("show", hwnd, flag)) or 1
            mod.user32.SetForegroundWindow = lambda hwnd: calls.append(("foreground", hwnd)) or 1
            mod.user32.keybd_event = lambda vk, scan, flags, extra: calls.append(("key", vk, flags)) or None
            mod.user32.PostMessageW = lambda hwnd, message, wparam, lparam: calls.append(("post", hwnd, message, wparam, lparam)) or 1
            mod.time.sleep = lambda _: None

            self.assertTrue(mod.send_enter(12345))

            self.assertEqual(calls, [
                ("post", 12345, mod.WM_KEYDOWN, mod.VK_RETURN, 0x001C0001),
                ("post", 12345, mod.WM_CHAR, mod.VK_RETURN, 0x001C0001),
                ("post", 12345, mod.WM_KEYUP, mod.VK_RETURN, 0xC01C0001),
            ])
        finally:
            mod.user32.ShowWindow = original_show_window
            mod.user32.SetForegroundWindow = original_set_foreground_window
            mod.user32.keybd_event = original_keybd_event
            mod.user32.PostMessageW = original_post_message
            mod.time.sleep = original_sleep

    def test_idle_tracker_uses_elapsed_time_not_loop_count(self):
        mod = load_module()
        tracker = mod.IdleTracker(required_seconds=0.6)

        self.assertFalse(tracker.observe(True, 10.0))
        self.assertFalse(tracker.observe(True, 10.3))
        self.assertTrue(tracker.observe(True, 10.6))
        self.assertTrue(tracker.consume_ready())
        self.assertFalse(tracker.consume_ready())

    def test_idle_tracker_resets_when_busy(self):
        mod = load_module()
        tracker = mod.IdleTracker(required_seconds=0.6)

        tracker.observe(True, 10.0)
        tracker.observe(False, 10.5)

        self.assertFalse(tracker.observe(True, 10.6))
        self.assertFalse(tracker.observe(True, 11.1))
        self.assertTrue(tracker.observe(True, 11.2))

    def test_title_match_ignores_auto_confirm_window(self):
        mod = load_module()

        self.assertFalse(mod.title_matches(r"C:\codex-auto-confirm\scripts\codex_auto_confirm.bat"))
        self.assertTrue(mod.title_matches("my-laptop - Codex CLI"))

    def test_action_required_title_matches_without_machine_name(self):
        mod = load_module()

        self.assertTrue(mod.action_required_title_matches("Action Required"))
        self.assertTrue(mod.action_required_title_matches("Action Required - Codex"))
        self.assertFalse(mod.action_required_title_matches("my-laptop - Codex CLI"))
        self.assertFalse(mod.action_required_title_matches(r"C:\codex-auto-confirm\scripts\codex_auto_confirm.bat"))

    def test_action_required_tracker_fires_once_until_title_clears(self):
        mod = load_module()
        tracker = mod.ActionRequiredTracker()

        self.assertTrue(tracker.observe("Action Required"))
        self.assertFalse(tracker.observe("Action Required - Codex"))
        self.assertFalse(tracker.observe("my-laptop - Codex CLI"))
        self.assertTrue(tracker.observe("Action Required"))

    def test_action_required_tracker_retries_by_default(self):
        mod = load_module()
        tracker = mod.ActionRequiredTracker()

        self.assertTrue(tracker.observe("Action Required", now=10.0))
        self.assertFalse(tracker.observe("Action Required - Codex", now=11.9))
        self.assertTrue(tracker.observe("Action Required - Codex", now=12.0))

    def test_batch_launcher_restarts_only_after_abnormal_exit(self):
        source = BATCH_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("if not defined codex_auto_confirm_python_exe", source)

        with tempfile.TemporaryDirectory(dir=MODULE_PATH.parent) as temp_dir:
            temp_path = Path(temp_dir)
            marker_path = temp_path / "attempts.txt"
            stub_path = temp_path / "exit_once.py"
            stub_path.write_text(
                "from pathlib import Path\n"
                "import os\n"
                "import sys\n"
                "marker = Path(os.environ['CODEX_AUTO_CONFIRM_TEST_MARKER'])\n"
                "attempt = int(marker.read_text() or '0') + 1 if marker.exists() else 1\n"
                "marker.write_text(str(attempt))\n"
                "sys.exit(7 if attempt == 1 else 0)\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update({
                "CODEX_AUTO_CONFIRM_PYTHON_EXE": sys.executable,
                "CODEX_AUTO_CONFIRM_SCRIPT": str(stub_path),
                "CODEX_AUTO_CONFIRM_RESTART_DELAY": "0",
                "CODEX_AUTO_CONFIRM_TEST_MARKER": str(marker_path),
            })

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(BATCH_PATH)],
                capture_output=True,
                check=False,
                env=env,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(marker_path.read_text(encoding="utf-8"), "2")
            self.assertIn("exited with code 7", result.stdout.lower())

    def test_action_required_tracker_retries_when_title_stays_visible(self):
        mod = load_module()
        tracker = mod.ActionRequiredTracker(retry_seconds=1.5)

        self.assertTrue(tracker.observe("Action Required", now=10.0))
        self.assertFalse(tracker.observe("Action Required - Codex", now=11.0))
        self.assertTrue(tracker.observe("Action Required - Codex", now=11.5))
        self.assertFalse(tracker.observe("Action Required - Codex", now=12.0))
        self.assertFalse(tracker.observe("pc-20260522 - Codex CLI", now=12.1))
        self.assertTrue(tracker.observe("Action Required", now=12.2))

    def test_plain_escape_does_not_exit_global_listener(self):
        mod = load_module()
        from pynput.keyboard import Key

        mod.running = True

        self.assertIsNone(mod.on_press(Key.esc))
        self.assertTrue(mod.running)

    def test_f10_exits_global_listener(self):
        mod = load_module()
        from pynput.keyboard import Key

        mod.running = True

        self.assertFalse(mod.on_press(Key.f10))
        self.assertFalse(mod.running)

    def test_main_returns_nonzero_when_listener_stops_unexpectedly(self):
        mod = load_module()
        mod.running = True
        listener = unittest.mock.MagicMock()
        listener.__enter__.return_value = listener

        with (
            patch.object(mod, "acquire_single_instance", return_value=True),
            patch("pynput.keyboard.Listener", return_value=listener),
            patch.object(mod.threading, "Thread"),
        ):
            self.assertEqual(mod.main(), 1)

    def test_main_returns_zero_after_intentional_shutdown(self):
        mod = load_module()
        mod.running = True
        listener = unittest.mock.MagicMock()
        listener.__enter__.return_value = listener
        listener.join.side_effect = lambda: setattr(mod, "running", False)

        with (
            patch.object(mod, "acquire_single_instance", return_value=True),
            patch("pynput.keyboard.Listener", return_value=listener),
            patch.object(mod.threading, "Thread"),
        ):
            self.assertEqual(mod.main(), 0)


if __name__ == "__main__":
    unittest.main()
