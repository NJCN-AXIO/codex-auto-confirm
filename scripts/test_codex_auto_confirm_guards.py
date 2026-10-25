import contextlib
import importlib.util
import io
import json
import queue
import subprocess
import sys
import threading
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
    def test_crashing_helpers_back_off_until_a_valid_response_recovers(self):
        module = load_module()
        real_popen = subprocess.Popen
        children = []
        clock = [100.0]
        output = io.StringIO()

        def create_helper(*_args, **_kwargs):
            code = (
                "raise SystemExit(7)" if len(children) < 3 else
                "import sys,time; sys.stdin.readline(); print('[]'); time.sleep(30)"
            )
            process = real_popen(
                [sys.executable, "-u", "-c", code],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            children.append(process)
            return process

        reader = None
        try:
            with (
                patch.object(module.subprocess, "Popen", side_effect=create_helper),
                patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
                contextlib.redirect_stdout(output),
            ):
                reader = module.CodexTerminalReader()
                reader._process.wait(timeout=3)
                self.assertTrue(reader.request_scan())  # One immediate recovery is allowed.
                reader._process.wait(timeout=3)
                self.assertFalse(reader.request_scan())
                for _ in range(4):
                    self.assertFalse(reader.request_scan())
                    self.assertFalse(reader.restart(force=True))
                self.assertEqual(len(children), 2)
                self.assertEqual(output.getvalue().count("UIA helper unhealthy"), 1)

                clock[0] += module.RECOVERY_HELPER_RESTART_BACKOFF_SECONDS
                self.assertTrue(reader.request_scan())
                reader._process.wait(timeout=3)
                # Starting a replacement is not proof of recovery.
                self.assertFalse(reader.request_scan())
                self.assertEqual(len(children), 3)

                clock[0] += module.RECOVERY_HELPER_RESTART_BACKOFF_SECONDS
                self.assertTrue(reader.request_scan())
                response = reader._responses.get(timeout=3)
                reader._responses.put_nowait(response)
                self.assertEqual(reader.poll(), [])
                reader._process.kill()
                reader._process.wait(timeout=3)
                # A valid response re-arms immediate recovery for a new failure.
                self.assertTrue(reader.request_scan())
                self.assertEqual(len(children), 5)
                self.assertEqual(output.getvalue().count("UIA helper unhealthy"), 2)
        finally:
            if reader is not None:
                reader.close()
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)

    def test_restarted_reader_ignores_old_helpers_delayed_response(self):
        self._check_delayed_helper_response(retire_during_backoff=False)

    def test_backoff_reader_ignores_old_helpers_delayed_response(self):
        self._check_delayed_helper_response(retire_during_backoff=True)

    def _check_delayed_helper_response(self, *, retire_during_backoff):
        module = load_module()
        real_popen = subprocess.Popen
        children = []
        old_response_read = threading.Event()
        release_old_response = threading.Event()

        def create_helper(*_args, **_kwargs):
            label = "old" if not children else "new"
            payload = json.dumps([{"hwnd": 111 if label == "old" else 222, "text": label}])
            process = real_popen(
                [sys.executable, "-u", "-c",
                 "import sys,time; sys.stdin.readline(); "
                 f"print({payload!r}); time.sleep(30)"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            children.append(process)
            return process

        reader = None
        old_drain = None
        try:
            with patch.object(module.subprocess, "Popen", side_effect=create_helper):
                reader = module.CodexTerminalReader()
                old_drain = reader._reader_thread
                old_queue = reader._responses
                old_put = old_queue.put_nowait

                def delay_old_response(line):
                    if '"old"' in line:
                        old_response_read.set()
                        release_old_response.wait(timeout=5)
                    return old_put(line)

                # Only freeze scheduling after the real pipe read. The helper
                # process, drain, restart, queue and poll paths stay real.
                with patch.object(old_queue, "put_nowait", side_effect=delay_old_response):
                    self.assertTrue(reader.request_scan())
                    self.assertTrue(old_response_read.wait(timeout=3))
                    if retire_during_backoff:
                        reader._helper_failures = 1
                        self.assertFalse(reader.restart(force=True, reason="scan timed out"))
                        release_old_response.set()
                        old_drain.join(timeout=2)
                        self.assertFalse(old_drain.is_alive())
                        self.assertIsNone(reader.poll())
                        self.assertFalse(reader.restart(force=True))
                        return
                    self.assertTrue(reader.restart(force=True))
                    self.assertTrue(reader.request_scan())
                    fresh_response = reader._responses.get(timeout=3)
                    self.assertEqual(json.loads(fresh_response)[0]["text"], "new")
                    reader._responses.put_nowait(fresh_response)
                    release_old_response.set()
                    old_drain.join(timeout=2)
                    self.assertFalse(old_drain.is_alive())
                    self.assertEqual(reader.poll(), [{"hwnd": 222, "text": "new"}])
        finally:
            release_old_response.set()
            if reader is not None:
                reader.close()
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
            if old_drain is not None:
                old_drain.join(timeout=2)

    def test_hidden_uia_helper_emits_utf8_terminal_glyphs(self):
        module = load_module()
        expected = "\u203a \u2022 \u26a0 \u7ee7\u7eed\uff01"
        helper_path = module.UIA_HELPER_SCRIPT_PATH.replace("'", "''")
        characters = ",".join(f"[char]{ord(char)}" for char in expected)
        # Execute the real helper's initializer without scanning or delivering
        # input. A hidden PowerShell otherwise inherits the Windows OEM codec.
        command = (
            f". '{helper_path}'; "
            f"[Console]::Out.WriteLine((-join @({characters})))"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", command],
            input=b"quit\n",
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.decode("utf-8", errors="replace").strip(), expected)

    def test_reader_stop_terminates_helper_with_blocked_stdout_reader(self):
        module = load_module()
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        reader = object.__new__(module.CodexTerminalReader)
        reader._process = process
        reader._responses = queue.Queue(maxsize=1)
        drain = threading.Thread(target=reader._drain_stdout, daemon=True)
        stopper = threading.Thread(target=reader._stop_process, args=(process,), daemon=True)
        drain.start()
        try:
            self.assertEqual(reader._responses.get(timeout=5), "ready\n")
            # Let the real pipe reader enter its next read, which cannot finish
            # until this quiet helper exits. No monitor or terminal is touched.
            threading.Event().wait(0.05)
            stopper.start()
            stopper.join(timeout=1.5)
            self.assertFalse(
                stopper.is_alive(),
                "Stopping a silent helper blocked while closing its stdout pipe",
            )
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if stopper.ident is not None:
                stopper.join(timeout=2)
            drain.join(timeout=2)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()

    def test_selected_approval_option_is_not_a_user_draft(self):
        module = load_module()
        text = (
            "OpenAI Codex\nWould you like to run the following command?\n"
            "  $ rtk git status\n› 1. Yes, proceed (y)\n"
            "  2. Yes, and don't ask again (a)\n"
            "  3. No, and tell Codex what to do differently (esc)"
        )
        self.assertTrue(module.codex_approval_prompt_visible(text))
        self.assertFalse(module._terminal_draft_visible(text))
        sender = unittest.mock.Mock(return_value=True)
        self.assertEqual(module.process_codex_approval_snapshots_multi([{
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
            "title": "Action Required", "text": text,
        }], {}, sender), [(2718, True)])
        sender.assert_called_once_with(2718)

    def test_selected_deny_or_permanent_allow_is_never_confirmed(self):
        module = load_module()
        for options in (
            "1. Yes, proceed (y)\n› 2. No, and tell Codex what to do differently (esc)",
            "1. Yes, proceed (y)\n› 2. Yes, and don't ask again (a)\n3. No, and tell Codex what to do differently (esc)",
        ):
            with self.subTest(options=options):
                self.assertFalse(module.codex_approval_prompt_visible(
                    "Would you like to run the following command?\n" + options))

    def test_menu_quote_followed_by_a_live_composer_cannot_be_approved(self):
        module = load_module()
        self.assertFalse(module.codex_approval_prompt_visible(
            "Would you like to run the following command?\n› 1. Yes, proceed (y)\n"
            "2. No, and tell Codex what to do differently (esc)\n\n› unfinished message"
        ))

    def test_new_working_below_an_old_menu_cannot_be_approved(self):
        module = load_module()
        self.assertFalse(module.codex_approval_prompt_visible(
            "Would you like to run the following command?\n1. Yes, proceed (y)\n"
            "2. No, and tell Codex what to do differently (esc)\n\n"
            "◦ Working (26s • esc to interrupt)\n\n› Ask Codex to do anything"
        ))

    def test_old_working_above_active_menu_does_not_block_approval(self):
        module = load_module()
        text = (
            "OpenAI Codex\n◦ Working (26s • esc to interrupt)\n\n"
            "Would you like to run the following command?\n"
            "1. Yes, proceed (y)\n2. No, and tell Codex what to do differently (esc)"
        )
        self.assertEqual(module.process_codex_approval_snapshots_multi([{
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
            "title": "Codex", "text": text,
        }], {}, lambda hwnd: True), [(2718, True)])

    def test_title_cannot_submit_a_draft_or_send_without_fresh_approval(self):
        for text in (
            "OpenAI Codex\n› 我还在打字",
            "OpenAI Codex\nWorking (2s • esc to interrupt)\n› Ask Codex to do anything",
            None,
        ):
            with self.subTest(text=text):
                module = load_module()
                snapshots = None if text is None else [{
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
                    "title": "Action Required | fixture", "text": text,
                }]
                reader = unittest.mock.Mock()
                reader.poll.return_value = snapshots
                module.running = True
                module.auto_confirm = True
                with (
                    patch.object(module, "CodexTerminalReader", return_value=reader),
                    patch.object(module, "find_action_required_window", return_value=(2718, "Action Required | fixture")),
                    patch.object(module, "read_desktop_allow_once", return_value=False),
                    patch.object(module, "send_enter", return_value=True) as sender,
                    patch.object(module.time, "sleep", side_effect=lambda _: setattr(module, "running", False)),
                ):
                    module.auto_enter_loop()
                sender.assert_not_called()

    def test_action_required_title_accepts_options_only_viewport(self):
        module = load_module()
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 2718,
            "title": "Action Required",
            "text": (
                "1. Yes, proceed (y)\n"
                "2. No, continue without running it (n)"
            ),
        }
        sender = unittest.mock.Mock(return_value=True)
        self.assertEqual(
            module.process_codex_approval_snapshots_multi([snapshot], {}, sender),
            [(2718, True)],
        )
        sender.assert_called_once_with(2718)

    def test_inline_approval_cannot_submit_sibling_draft_and_resumes_after_clear(self):
        module = load_module()
        prompt = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
            "title": "Codex", "text": "Would you like to run the following command?\n1. Yes, proceed",
        }
        trackers = {}
        sender = unittest.mock.Mock(return_value=True)
        self.assertEqual(module.process_codex_approval_snapshots_multi(
            [prompt, {**prompt, "text": "› unfinished message"}], trackers, sender), [])
        sender.assert_not_called()
        self.assertEqual(module.process_codex_approval_snapshots_multi([prompt], trackers, sender), [(2718, True)])

    def test_wrapped_approval_example_inside_draft_is_not_a_prompt(self):
        module = load_module()
        self.assertFalse(module.codex_approval_prompt_visible(
            "› Please explain this menu:\n  Would you like to run the following command?\n  1. Yes, proceed"
        ))

    def test_blank_rows_and_middle_dot_do_not_hide_multiline_draft(self):
        module = load_module()
        self.assertTrue(module._terminal_draft_visible("›\n\n  我在写 A · B\n\n  gpt-6.1-sol high · project"))

    def test_all_enter_delivery_rechecks_recent_input(self):
        module = load_module()
        with (
            patch.object(module, "recovery_input_busy", return_value=True),
            patch.object(module, "send_enter_via_attached_post", return_value=True) as sender,
            patch.object(module.user32, "PostMessageW") as post,
        ):
            self.assertFalse(module.send_enter(2718))
            sender.assert_not_called()
            post.assert_not_called()

    def test_historical_user_message_does_not_block_a_real_approval(self):
        module = load_module()
        prompt = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
            "title": "Codex", "text": (
                "› 修复这个问题\n\n• I will run a check.\n\n"
                "Would you like to run the following command?\n1. Yes, proceed"
            ),
        }
        self.assertEqual(module.process_codex_approval_snapshots_multi(
            [prompt], {}, lambda hwnd: True), [(2718, True)])

    def test_one_prompt_is_not_sent_again_by_the_title_branch(self):
        module = load_module()
        prompt = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
            "title": "Action Required | fixture",
            "text": (
                "Would you like to run the following command?\n› 1. Yes, proceed (y)\n"
                "2. No, and tell Codex what to do differently (esc)"
            ),
        }
        reader = unittest.mock.Mock()
        reader.poll.return_value = [prompt]
        module.running = module.auto_confirm = True
        ticks = []
        clock = [0.0]
        def stop_after_ticks(_seconds):
            ticks.append(1)
            clock[0] += module.RETRY_ENTER_SECONDS + 0.1
            if len(ticks) >= 3:
                module.running = False
        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
            patch.object(module, "find_action_required_window", return_value=(2718, prompt["title"])),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module, "send_enter", return_value=True) as sender,
            patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(module.time, "sleep", side_effect=stop_after_ticks),
        ):
            module.auto_enter_loop()
        self.assertEqual(sender.call_count, 1)

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
        reader = unittest.mock.Mock()
        reader.poll.return_value = [{
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718, "title": "Codex",
            "text": "Would you like to run the following command?\n1. Yes, proceed",
        }]
        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
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
            patch.object(module, "find_codex_desktop_window", return_value=1234),
            patch.object(module, "read_desktop_allow_once", desktop_probe),
            patch.object(module.time, "sleep", side_effect=stop_after_three),
        ):
            module.auto_enter_loop()

        self.assertEqual(desktop_probe.call_count, 1)

    def test_absent_desktop_does_not_delay_new_terminal_approval(self):
        module = load_module()
        module.running = module.auto_confirm = True
        clock = [0.0]
        sent_at = []
        prompt = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718, "title": "Codex",
            "text": "Would you like to run the following command?\n$ echo CHECK\n"
                    "› 1. Yes, proceed (y)\n2. No, and tell Codex what to do differently (esc)",
        }

        def desktop_timeout():
            clock[0] += 0.8
            return False

        def send(hwnd):
            sent_at.append(clock[0])
            module.running = False
            return True

        def sleep(seconds):
            clock[0] += seconds
            if clock[0] > 5:
                module.running = False

        reader = unittest.mock.Mock()
        reader.poll.side_effect = lambda: [prompt] if clock[0] >= 0.25 else []
        with (
            patch.object(module, "CodexTerminalReader", return_value=reader),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "find_codex_desktop_window", return_value=None),
            patch.object(module, "read_desktop_allow_once", side_effect=desktop_timeout) as desktop_probe,
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "send_enter", side_effect=send),
            patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(module.time, "sleep", side_effect=sleep),
        ):
            module.auto_enter_loop()
        self.assertEqual(len(sent_at), 1)
        self.assertLessEqual(sent_at[0] - 0.25, module.RECOVERY_POLL_SECONDS)
        desktop_probe.assert_not_called()

    def test_consecutive_approvals_do_not_sleep_after_each_enter(self):
        module = load_module()
        module.running = module.auto_confirm = True
        clock = [0.0]
        sent_at = []

        def send(hwnd):
            sent_at.append(clock[0])
            if len(sent_at) == 3:
                module.running = False
            return True

        def sleep(seconds):
            clock[0] += seconds
            if clock[0] > 5:
                module.running = False

        class Reader:
            pending = False
            number = 0

            def request_scan(self):
                self.pending = True
                return True

            def poll(self):
                if not self.pending:
                    return None
                self.pending = False
                self.number += 1
                return [{"class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 2718,
                         "title": "Codex", "text":
                         "Would you like to run the following command?\n"
                         f"$ echo CHECK_{self.number}\n› 1. Yes, proceed (y)\n"
                         "2. No, and tell Codex what to do differently (esc)"}]

            def close(self):
                pass

        with (
            patch.object(module, "CodexTerminalReader", return_value=Reader()),
            patch.object(module, "find_action_required_window", return_value=(None, "")),
            patch.object(module, "find_codex_desktop_window", return_value=None),
            patch.object(module, "read_desktop_allow_once", return_value=False),
            patch.object(module, "recovery_input_busy", return_value=False),
            patch.object(module, "send_enter", side_effect=send),
            patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(module.time, "sleep", side_effect=sleep),
        ):
            module.auto_enter_loop()
        self.assertEqual(len(sent_at), 3)
        self.assertLessEqual(max(b - a for a, b in zip(sent_at, sent_at[1:], strict=False)),
                             module.RECOVERY_POLL_SECONDS + module.LOOP_SECONDS)

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
