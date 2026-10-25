from __future__ import annotations

import importlib.util
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm_recovery", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RecoveryMatcherTests(unittest.TestCase):
    def test_capacity_sentence_in_user_prose_is_not_an_error(self):
        mod = load_module()
        self.assertIsNone(mod.codex_recovery_error_signature(
            "怎么感觉又不太管用了，出现⚠ Selected model is at capacity. "
            "Please try a different model.继续！继续！"
        ))

    def test_wrapped_user_prompt_is_not_an_error(self):
        mod = load_module()
        for marker in ("›", "»"):
            with self.subTest(marker=marker):
                self.assertIsNone(mod.codex_recovery_error_signature(
                    f"OpenAI Codex\n{marker} 怎么感觉又不太管用了，出现⚠ Selected model is at capacity.\n"
                    "  Please try a different model.\n  ■ A provider failure copied into my draft"
                ))

    def test_latest_error_line_wins_when_old_capacity_line_remains_visible(self):
        mod = load_module()

        text = (
            "OpenAI Codex\n"
            "⚠ Selected model is at capacity. Please try a different model.\n"
            "■ unexpected status 503 Service Unavailable: auth_unavailable"
        )

        self.assertEqual(mod.codex_recovery_error_signature(text), "http-503")

    def test_matches_retry_limit_and_rate_limit_error_context(self):
        mod = load_module()

        self.assertIsNotNone(
            mod.codex_recovery_error_signature(
                "■ exceeded retry limit, last status: 429 Too Many Requests"
            )
        )

    def test_matches_gateway_status_and_model_capacity_errors(self):
        mod = load_module()

        for text in (
            "■ unexpected status 502 Bad Gateway",
            "■ unexpected status 503 Service Unavailable",
            "■ unexpected status 504 Gateway Timeout",
            "Selected model is at capacity. Please try a different model.",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(mod.codex_recovery_error_signature(text))

    def test_rejects_numbers_in_prompts_and_non_error_text(self):
        mod = load_module()

        for text in (
            "› Please explain 429 and 502 in this task",
            "request id 5020 / record 1502",
            "ordinary response code 429",
            "Allow once",
            "■ completed successfully",
            "› explain why Conversation interrupted appears",
        ):
            with self.subTest(text=text):
                self.assertIsNone(mod.codex_recovery_error_signature(text))

    def test_standalone_rate_limit_error_is_recoverable(self):
        mod = load_module()

        self.assertEqual(
            mod.codex_recovery_error_signature("429 Too Many Requests"),
            "http-429",
        )

    def test_structured_api_error_is_recoverable_without_error_specific_keyword(self):
        mod = load_module()

        text = '''OpenAI Codex
■ {
  "error": {
  "message": "Invalid 'input[54].id': 'item_044bc05b9fbcdeffae40534'. Expected an ID that begins with 'msg'.",
  "type": "invalid_request_error"
  }
}'''

        self.assertEqual(
            mod.codex_recovery_error_signature(text),
            "api-error",
        )

    def test_structured_api_error_uses_one_generic_recovery_signature(self):
        mod = load_module()

        text = '''OpenAI Codex
■ {
  "error": {
    "message": "A future server-side failure with a new message",
    "type": "new_error_type"
  }
}'''

        self.assertEqual(mod.codex_recovery_error_signature(text), "api-error")

    def test_unknown_error_glyph_uses_the_same_generic_recovery_path(self):
        mod = load_module()

        self.assertEqual(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\n■ A provider failure with wording introduced today"
            ),
            "visible-error",
        )


class RecoveryStatusPriorityTests(unittest.TestCase):
    def test_empty_live_placeholder_and_footer_allow_a_real_capacity_error(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex task",
            "text": (
                "OpenAI Codex\n⚠ Selected model is at\n  capacity. Please try a different model.\n"
                "\n› Ask Codex to do anything\n\n  gpt-6.1-sol high · project\n\n"
            ),
        }
        self.assertEqual(mod.process_codex_recovery_snapshots_multi(
            [error], {}, lambda hwnd: True), [(901, "model-capacity", True)])

    def test_astra_animated_empty_placeholder_allows_real_capacity_error(self):
        mod = load_module()
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "店铺容量清单",
            "text": (
                "⚠ Selected model is at capacity. Please try a different model.\n"
                "   ⢀  ⠈   ⠁ ⢀\n»⠁Ask Codex to do anything    ⠈     ⢀\n"
                "       ⢀⠐        ⠄\n  gpt-6-astra ultra · project"
            ),
        }
        self.assertEqual(mod.process_codex_recovery_snapshots_multi(
            [snapshot], {}, lambda hwnd: True), [(901, "model-capacity", True)])

    def test_recent_input_in_another_window_does_not_block_recovery(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex task", "text": "OpenAI Codex\n429 Too Many Requests\n› ",
        }
        with (
            patch.object(mod.user32, "GetForegroundWindow", return_value=902),
            patch.object(mod.user32, "GetLastInputInfo", return_value=0),
        ):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [error], {}, lambda hwnd: True), [(901, "http-429", True)])

    def test_single_window_entrypoint_also_protects_drafts(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex task", "text": "OpenAI Codex\n429 Too Many Requests\n› unfinished",
        }
        calls = []
        tracker = mod.ErrorRecoveryTracker()
        self.assertEqual(mod.process_codex_recovery_snapshots(
            [error], tracker, lambda hwnd: calls.append(hwnd) or True), (False, None, None))
        self.assertEqual(calls, [])
        self.assertEqual(tracker.delivery_attempts, 0)

    def test_recent_input_defers_without_using_delivery_attempts(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 901,
            "title": "Codex task", "text": "OpenAI Codex\n429 Too Many Requests\n› ",
        }
        trackers = {}
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True

        def recent_input(pointer):
            pointer._obj.dwTime = 9900
            return 1

        with (
            patch.object(mod.user32, "GetForegroundWindow", return_value=901),
            patch.object(mod.user32, "GetLastInputInfo", side_effect=recent_input),
            patch.object(mod.kernel32, "GetTickCount", return_value=10000),
        ):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi([error], trackers, sender), [])
            self.assertEqual(calls, [])
            self.assertEqual(trackers[901].delivery_attempts, 0)
            with patch.object(mod.kernel32, "GetTickCount", return_value=12000):
                self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                    [error], trackers, sender), [(901, "http-429", True)])
            self.assertEqual(calls, [901])

    def test_send_continue_rechecks_activity_before_posting_text_or_enter(self):
        mod = load_module()
        with (
            patch.object(mod.user32, "GetForegroundWindow", return_value=901),
            patch.object(mod.user32, "GetLastInputInfo", return_value=0),
            patch.object(mod, "_post_messages_via_attached_target", return_value=True) as sender,
            patch.object(mod.user32, "PostMessageW") as post,
        ):
            self.assertFalse(mod.send_continue(901))
            sender.assert_not_called()
            post.assert_not_called()

    def test_draft_defers_recovery_without_consuming_the_error_edge(self):
        mod = load_module()
        for draft in ("› 我还没有打完", "›\n  正在输入的第二行", "> my unfinished draft",
                      "» 我还没有打完", "»\n\n  正在输入的第二行"):
            with self.subTest(draft=draft):
                trackers = {}
                calls = []
                error = {
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                    "hwnd": 901,
                    "title": "Codex task",
                    "text": "OpenAI Codex\n⚠ Selected model is at capacity. Please try a different model.",
                }
                sender = lambda hwnd: calls.append(hwnd) or True
                self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                    [{**error, "text": error["text"] + "\n" + draft}], trackers, sender
                ), [])
                self.assertEqual(calls, [])
                self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                    [{**error, "text": error["text"] + "\n› "}], trackers, sender
                ), [(901, "model-capacity", True)])
                self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                    [{**error, "text": error["text"] + "\n› "}], trackers, sender
                ), [])
                self.assertEqual(calls, [901])

    def test_draft_sibling_blocks_only_its_own_window(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 901,
            "title": "Codex task",
            "text": "OpenAI Codex\n⚠ Selected model is at capacity. Please try a different model.",
        }
        calls = []
        self.assertEqual(mod.process_codex_recovery_snapshots_multi([
            error, {**error, "text": "› 我正在打字"}, {**error, "hwnd": 902}
        ], {}, lambda hwnd: calls.append(hwnd) or True), [(902, "model-capacity", True)])
        self.assertEqual(calls, [902])

    def test_plain_working_word_does_not_count_as_recovery_confirmation(self):
        mod = load_module()

        self.assertEqual(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\nWorking\n429 Too Many Requests"
            ),
            "http-429",
        )

    def test_prompt_quoting_working_status_does_not_confirm_recovery(self):
        mod = load_module()

        self.assertEqual(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\n› Working (12s • esc to interrupt)\n429 Too Many Requests"
            ),
            "http-429",
        )

    def test_conversation_interrupted_masks_stale_error_text(self):
        mod = load_module()

        text = (
            "OpenAI Codex\n"
            "■ unexpected status 503 Service Unavailable: auth_unavailable\n"
            "■ Conversation interrupted - tell the model what to do differently. "
            "Something went wrong? Hit `/feedback` to report the issue."
        )

        self.assertIsNone(mod.codex_recovery_error_signature(text))

    def test_working_window_does_not_mask_error_in_another_window(self):
        mod = load_module()
        trackers = {}
        calls = []

        working = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 901,
            "title": "Codex task A",
            "text": "OpenAI Codex\nWorking (12s • esc to interrupt)",
        }
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 902,
            "title": "Codex task B",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }

        events = mod.process_codex_recovery_snapshots_multi(
            [working, error], trackers, lambda hwnd: calls.append(hwnd) or True
        )

        self.assertEqual(events, [(902, "http-503", True)])
        self.assertEqual(calls, [902])


class RecoveryStatusAndCancellationTests(unittest.TestCase):
    def test_working_duration_outside_cropped_viewport_blocks_continue(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        # A long transcript can place the visible Working row above the
        # current composer viewport returned by UIA.  It is still a live
        # status and must suppress an old capacity error.
        text = "OpenAI Codex\nWorking (26s • esc to interrupt)\n"
        text += "historical output\n" * 45
        text += (
            "Selected model is at capacity. Please try a different model.\n"
            "› Ask Codex to do anything"
        )
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 935,
            "title": "Codex task",
            "text": text,
        }
        sender = lambda hwnd: calls.append(hwnd) or True
        self.assertTrue(mod._working_status_active(text))
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(calls, [])

    def test_capacity_windows_retry_independently_and_accept_untitled_normal_status(self):
        mod = load_module()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 933, "title": "店铺容量清单",
            "text": "⚠ Selected model is at capacity. Please try a different model\n\n› ",
        }
        other = {**error, "hwnd": 934, "title": "Windows Terminal"}
        trackers = {}
        sender = lambda hwnd: True
        with patch.object(mod.time, "monotonic", return_value=0.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [error, other], trackers, sender), [(933, "model-capacity", True), (934, "model-capacity", True)])
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 3.0
        with patch.object(mod.time, "monotonic", return_value=4.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi([
                {**error, "text": "◦ Working (12s • esc to interrupt)\n\n› Ask Codex to do anything"}, other
            ], trackers, sender), [(934, "model-capacity", True)])
        with patch.object(mod.time, "monotonic", return_value=5.0):
            self.assertEqual(mod.process_codex_recovery_snapshots_multi(
                [error, other], trackers, sender), [(933, "model-capacity", True)])

    def test_capacity_retries_until_live_processing_readback_in_any_titled_window(self):
        mod = load_module()
        for title in ("店铺容量清单", "Windows Terminal", "PowerShell"):
            for normal in (
                "◦ Working (12s • esc to interrupt)",
                "Compacting context (26s • esc to interrupt)",
                "◦ Compacting context (26s • esc to interrupt)",
            ):
                with self.subTest(title=title, normal=normal):
                    tracker = mod.ErrorRecoveryTracker()
                    tracker.semantic_retry_seconds = 3.0
                    tracker.max_delivery_attempts = 1
                    error = {
                        "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 930,
                        "title": title,
                        "text": "⚠ Selected model is at capacity. Please try a different model\n\n› Ask Codex to do anything",
                    }
                    calls = []
                    sender = lambda hwnd: calls.append(hwnd) or True
                    with patch.object(mod.time, "monotonic", return_value=0.0):
                        self.assertEqual(mod.process_codex_recovery_snapshots(
                            [error], tracker, sender), (True, "model-capacity", True))
                    for now, expected in ((2.9, False), (3.0, True), (6.0, True)):
                        with patch.object(mod.time, "monotonic", return_value=now):
                            self.assertEqual(mod.process_codex_recovery_snapshots(
                                [error], tracker, sender), (expected, "model-capacity", True if expected else None))
                    with patch.object(mod.time, "monotonic", return_value=7.0):
                        self.assertEqual(mod.process_codex_recovery_snapshots(
                            [{**error, "text": normal + "\n" + error["text"]}], tracker, sender),
                            (False, None, None))
                    with patch.object(mod.time, "monotonic", return_value=20.0):
                        self.assertEqual(mod.process_codex_recovery_snapshots(
                            [error], tracker, sender), (False, "model-capacity", None))
                    self.assertEqual(calls, [930, 930, 930])

    def test_capacity_retry_waits_while_a_draft_is_present(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 3.0
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 931, "title": "店铺容量清单",
            "text": "⚠ Selected model is at capacity. Please try a different model\n\n› ",
        }
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        with patch.object(mod.time, "monotonic", return_value=0.0):
            mod.process_codex_recovery_snapshots([error], tracker, sender)
        with patch.object(mod.time, "monotonic", return_value=10.0):
            self.assertEqual(mod.process_codex_recovery_snapshots(
                [{**error, "text": error["text"] + "我没打完"}], tracker, sender), (False, None, None))
            self.assertEqual(mod.process_codex_recovery_snapshots(
                [error], tracker, sender), (True, "model-capacity", True))
        self.assertEqual(calls, [931, 931])

    def test_capacity_can_recur_after_a_clean_working_readback(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 932, "title": "店铺容量清单",
            "text": "⚠ Selected model is at capacity. Please try a different model\n\n› ",
        }
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        mod.process_codex_recovery_snapshots([error], tracker, sender)
        mod.process_codex_recovery_snapshots(
            [{**error, "text": "◦ Working (8s • esc to interrupt)\n\n› Ask Codex to do anything"}],
            tracker, sender)
        self.assertEqual(mod.process_codex_recovery_snapshots(
            [error], tracker, sender), (True, "model-capacity", True))
        self.assertEqual(calls, [932, 932])

    def test_new_error_after_working_confirmation_is_not_suppressed(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        capacity = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 919,
            "title": "Codex task",
            "text": "OpenAI Codex\nSelected model is at capacity. Please try a different model.",
        }
        working = {
            **capacity,
            "text": (
                "OpenAI Codex\nWorking (2s • esc to interrupt)\n"
                "Selected model is at capacity. Please try a different model."
            ),
        }
        new_error = {
            **capacity,
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([capacity], tracker, sender),
            (True, "model-capacity", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([working], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([new_error], tracker, sender),
            (True, "http-503", True),
        )
        self.assertEqual(calls, [919, 919])

    def test_unknown_error_uses_the_single_continue_delivery_path(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 925,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ Provider returned a new fatal condition",
        }

        self.assertEqual(
            mod.process_codex_recovery_snapshots(
                [snapshot], tracker, lambda hwnd: calls.append(hwnd) or True
            ),
            (True, "visible-error", True),
        )
        self.assertEqual(calls, [925])

    def test_only_working_or_compacting_status_confirms_unknown_error_recovery(self):
        mod = load_module()

        for status in (
            "Working (12s)",
            "Compacting context (26s • esc to interrupt)",
        ):
            with self.subTest(status=status):
                self.assertIsNone(
                    mod.codex_recovery_error_signature(
                        "OpenAI Codex\n"
                        f"{status}\n"
                        "■ Provider returned a new fatal condition"
                    )
                )

    def test_chinese_compacting_context_is_a_normal_status(self):
        mod = load_module()

        self.assertIsNone(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\n"
                "\u6b63\u5728\u538b\u7f29\u4e0a\u4e0b\u6587\n"
                "■ Provider returned a new fatal condition"
            )
        )

    def test_changed_error_does_not_start_a_second_edge_without_normal_status(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        capacity = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 920,
            "title": "Codex task",
            "text": "OpenAI Codex\n⚠ Selected model is at capacity. Please try a different model.",
        }
        appended_503 = {
            **capacity,
            "text": (
                capacity["text"]
                + "\n■ unexpected status 503 Service Unavailable: auth_unavailable"
            ),
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([capacity], tracker, sender),
            (True, "model-capacity", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([appended_503], tracker, sender),
            (False, "http-503", None),
        )
        self.assertEqual(calls, [920])

    def test_failed_delivery_gets_one_bounded_follow_up(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.delivery_retry_seconds = 0.0
        tracker.max_delivery_attempts = 2
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 907,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        sender = lambda hwnd: calls.append(hwnd) or len(calls) == 2

        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-503", False),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-503", True),
        )
        self.assertEqual(calls, [907, 907])

    def test_persistent_error_does_not_repeat_after_successful_post(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        tracker.max_delivery_attempts = 2
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 912,
            "title": "Codex task",
            "text": "OpenAI Codex\n429 Too Many Requests",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(calls, [912])

    def test_successful_error_delivery_is_one_shot_even_when_legacy_cap_is_one(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        tracker.max_delivery_attempts = 1
        calls = []
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 921,
            "title": "Codex task",
            "text": "OpenAI Codex\n429 Too Many Requests",
        }
        working = {
            **error,
            "text": "OpenAI Codex\nWorking (12s • esc to interrupt)\n429 Too Many Requests",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([working], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(calls, [921])

    def test_error_does_not_rearm_from_ready_without_visible_working_status(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 10.0
        tracker.max_delivery_attempts = 2
        calls = []
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 913,
            "title": "Codex task",
            "text": "OpenAI Codex\n429 Too Many Requests",
        }
        ready = {**error, "text": "OpenAI Codex\nReady"}
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([ready], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(calls, [913])

    def test_cancellation_cancels_a_pending_delivery_follow_up(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.delivery_retry_seconds = 0.0
        calls = []
        initial = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 908,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        cancelled = {
            **initial,
            "text": (
                initial["text"]
                + "\n■ Conversation interrupted - tell the model what to do differently. "
                "Something went wrong? Hit `/feedback` to report the issue."
            ),
        }
        sender = lambda hwnd: calls.append(hwnd) or False

        self.assertEqual(
            mod.process_codex_recovery_snapshots([initial], tracker, sender),
            (True, "http-503", False),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([cancelled], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([initial], tracker, sender),
            (False, "http-503", None),
        )
        self.assertEqual(calls, [908])

    def test_same_visible_503_retries_until_working_status(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker(retry_seconds=30.0)
        tracker.semantic_retry_seconds = 30.0
        tracker.max_delivery_attempts = 1
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 903,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        sender = lambda hwnd: calls.append(hwnd) or True
        working = {
            **snapshot,
            "text": "OpenAI Codex\nWorking (12s - esc to interrupt)",
        }

        with patch.object(mod.time, "monotonic", side_effect=(0.0, 31.0, 62.0)):
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([working], tracker, sender),
                (False, None, None),
            )

        self.assertEqual(calls, [903, 903, 903])

    def test_cancelled_conversation_does_not_retrigger_stale_error(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker(retry_seconds=30.0)
        calls = []
        initial = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 904,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        cancelled = {
            **initial,
            "text": (
                initial["text"]
                + "\n■ Conversation interrupted - tell the model what to do differently. "
                "Something went wrong? Hit `/feedback` to report the issue."
            ),
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        with patch.object(mod.time, "monotonic", side_effect=(0.0, 31.0)):
            self.assertEqual(
                mod.process_codex_recovery_snapshots([initial], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([cancelled], tracker, sender),
                (False, None, None),
            )

        self.assertEqual(calls, [904])


    def test_each_error_window_has_its_own_one_shot_tracker(self):
        mod = load_module()
        trackers = {}
        calls = []
        snapshots = [
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 905,
                "title": "Codex task A",
                "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
            },
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 906,
                "title": "Codex task B",
                "text": "OpenAI Codex\nSelected model is at capacity. Please try a different model.",
            },
        ]

        events = mod.process_codex_recovery_snapshots_multi(
            snapshots, trackers, lambda hwnd: calls.append(hwnd) or True
        )
        repeat = mod.process_codex_recovery_snapshots_multi(
            snapshots, trackers, lambda hwnd: calls.append(hwnd) or True
        )

        self.assertEqual(events, [(905, "http-503", True), (906, "model-capacity", True)])
        self.assertEqual(repeat, [])
        self.assertEqual(calls, [905, 906])

    def test_capacity_retries_independently_of_one_shot_rate_limit_window(self):
        mod = load_module()
        trackers = {
            914: mod.ErrorRecoveryTracker(),
            915: mod.ErrorRecoveryTracker(),
        }
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
            tracker.max_delivery_attempts = 2
        calls = []
        snapshots = [
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 914,
                "title": "Codex task A",
                "text": "OpenAI Codex\n429 Too Many Requests",
            },
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 915,
                "title": "Codex task B",
                "text": "OpenAI Codex\nSelected model is at capacity. Please try a different model.",
            },
        ]
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(914, "http-429", True), (915, "model-capacity", True)],
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(915, "model-capacity", True)],
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(915, "model-capacity", True)],
        )
        self.assertEqual(calls, [914, 915, 915, 915])

    def test_503_retries_independently_of_one_shot_429(self):
        mod = load_module()
        trackers = {922: mod.ErrorRecoveryTracker(), 923: mod.ErrorRecoveryTracker()}
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
            tracker.max_delivery_attempts = 1
        calls = []
        snapshots = [
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 922,
                "title": "Codex task A",
                "text": "OpenAI Codex\n429 Too Many Requests",
            },
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": 923,
                "title": "Codex task B",
                "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable",
            },
        ]
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(922, "http-429", True), (923, "http-503", True)],
        )
        for _ in range(3):
            self.assertEqual(
                mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
                [(923, "http-503", True)],
            )

        self.assertEqual(calls, [922, 923, 923, 923, 923])

    def test_other_error_families_keep_one_shot_policy(self):
        mod = load_module()
        for text, signature in (
            ("OpenAI Codex\n■ exceeded retry limit", "retry-limit"),
            ("OpenAI Codex\n■ unexpected status 502 Bad Gateway", "http-502"),
            ("OpenAI Codex\n■ unexpected status 504 Gateway Timeout", "http-504"),
        ):
            with self.subTest(signature=signature):
                tracker = mod.ErrorRecoveryTracker()
                tracker.semantic_retry_seconds = 0.0
                tracker.max_delivery_attempts = 1
                calls = []
                snapshot = {
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                    "hwnd": 924,
                    "title": "Codex task",
                    "text": text,
                }
                sender = lambda hwnd: calls.append(hwnd) or True
                self.assertEqual(
                    mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                    (True, signature, True),
                )
                for _ in range(2):
                    self.assertEqual(
                        mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                        (False, signature, None),
                    )
                self.assertEqual(calls, [924])

    def test_three_503_windows_retry_independently(self):
        mod = load_module()
        trackers = {hwnd: mod.ErrorRecoveryTracker() for hwnd in (916, 917, 918)}
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
        calls = []
        snapshots = [
            {
                "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                "hwnd": hwnd,
                "title": f"Codex task {hwnd}",
                "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
            }
            for hwnd in (916, 917, 918)
        ]
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(916, "http-503", True), (917, "http-503", True), (918, "http-503", True)],
        )
        for _ in range(3):
            self.assertEqual(
                mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
                [(916, "http-503", True), (917, "http-503", True), (918, "http-503", True)],
            )

        self.assertEqual(
            calls,
            [916, 917, 918] * 4,
        )

    def test_closed_window_tracker_is_pruned_before_hwnd_reuse(self):
        mod = load_module()
        trackers = {}
        calls = []
        error_a = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 910,
            "title": "Codex task A",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable: auth_unavailable",
        }
        normal_b = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 911,
            "title": "Codex task B",
            "text": "OpenAI Codex\nReady",
        }

        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(
                [error_a], trackers, lambda hwnd: calls.append(hwnd) or True
            ),
            [(910, "http-503", True)],
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(
                [normal_b], trackers, lambda hwnd: calls.append(hwnd) or True
            ),
            [],
        )
        reused = {**error_a, "text": error_a["text"]}
        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(
                [reused], trackers, lambda hwnd: calls.append(hwnd) or True
            ),
            [(910, "http-503", True)],
        )
        self.assertEqual(calls, [910, 910])

    def test_working_duration_status_masks_old_error_text(self):
        mod = load_module()

        for status in (
            "Working (12s • esc to interrupt)",
            "Working (3 minutes • esc to interrupt)",
            "Working (2 hours 4 seconds • esc to interrupt)",
            "Working (7分钟• esc to interrupt)",
            "Working (1小时2秒• esc to interrupt)",
        ):
            with self.subTest(status=status):
                self.assertIsNone(
                    mod.codex_recovery_error_signature(
                        f"OpenAI Codex\n{status}\n■ unexpected status 502 Bad Gateway"
                    )
                )

    def test_working_status_with_uia_bullet_prefix_masks_old_error_text(self):
        mod = load_module()

        self.assertIsNone(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\n◦ Working (5m 12s • esc to interrupt)\n"
                "■ unexpected status 503 Service Unavailable"
            )
        )

    def test_all_reconnecting_progress_attempts_mask_old_error_text(self):
        mod = load_module()

        for attempt in range(1, 6):
            with self.subTest(attempt=attempt):
                self.assertIsNone(
                    mod.codex_recovery_error_signature(
                        f"OpenAI Codex\nReconnecting... {attempt}/5\n"
                        "■ unexpected status 503 Service Unavailable"
                    )
                )

    def test_status_then_final_error_triggers_only_after_status_disappears(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True

        status_snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 901,
            "title": "Codex task",
            "text": (
                "OpenAI Codex\nWorking (12s • esc to interrupt)\n"
                "■ unexpected status 502 Bad Gateway"
            ),
        }
        reconnecting_snapshot = {
            **status_snapshot,
            "text": (
                "OpenAI Codex\nReconnecting... 5/5\n"
                "■ unexpected status 502 Bad Gateway"
            ),
        }
        final_snapshot = {
            **status_snapshot,
            "text": "OpenAI Codex\n■ unexpected status 502 Bad Gateway",
        }

        self.assertEqual(
            mod.process_codex_recovery_snapshots([status_snapshot], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([reconnecting_snapshot], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([final_snapshot], tracker, sender),
            (True, "http-502", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([final_snapshot], tracker, sender),
            (False, "http-502", None),
        )
        self.assertEqual(calls, [901])

    def test_working_overlay_does_not_duplicate_a_latched_error(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        sender = lambda hwnd: calls.append(hwnd) or True
        error = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 902,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 504 Gateway Timeout",
        }
        working_with_old_error = {
            **error,
            "text": (
                "OpenAI Codex\nWorking (2 minutes • esc to interrupt)\n"
                "■ unexpected status 504 Gateway Timeout"
            ),
        }

        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (True, "http-504", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([working_with_old_error], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-504", None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots(
                [{**error, "text": "OpenAI Codex\nReady"}], tracker, sender
            ),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-504", None),
        )
        mod.process_codex_recovery_snapshots(
            [{**error, "text": "› Ask Codex to do anything\n82% context left · ? for shortcuts"}],
            tracker, sender,
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (True, "http-504", True),
        )
        self.assertEqual(calls, [902, 902])

    def test_working_sibling_blocks_capacity_sibling(self):
        mod = load_module()
        trackers = {}
        calls = []
        working = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 926,
            "title": "Codex task",
            "text": "OpenAI Codex\nWorking (12s - esc to interrupt)",
        }
        capacity = {
            **working,
            "text": (
                "OpenAI Codex\n"
                "Selected model is at capacity. Please try a different model."
            ),
        }

        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(
                [working, capacity], trackers, lambda hwnd: calls.append(hwnd) or True
            ),
            [],
        )
        self.assertEqual(calls, [])


class RecoveryTrackerTests(unittest.TestCase):
    def test_tracker_is_one_shot_and_rearms_only_after_known_clear(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()

        self.assertTrue(tracker.observe(True))
        self.assertFalse(tracker.observe(True))
        self.assertFalse(tracker.observe(None))
        self.assertFalse(tracker.observe(True))
        self.assertFalse(tracker.observe(False))
        self.assertTrue(tracker.observe(True))


class TerminalReaderTests(unittest.TestCase):
    def test_reader_restarts_a_stalled_helper_before_sending_next_scan(self):
        mod = load_module()

        class FakeStdin:
            def __init__(self):
                self.writes = []
                self.closed = False

            def write(self, value):
                self.writes.append(value)

            def flush(self):
                return None

            def close(self):
                self.closed = True

        class FakeStdout:
            def close(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = FakeStdout()
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

        first = FakeProcess()
        second = FakeProcess()
        with patch.object(mod.subprocess, "Popen", side_effect=[first, second]):
            reader = mod.CodexTerminalReader(helper_path="helper.ps1", powershell_exe="powershell")
            self.assertTrue(reader.request_scan())
            reader._scan_sent_at = 0.0
            with patch.object(mod.time, "monotonic", return_value=10.0):
                self.assertTrue(reader.request_scan())

            self.assertTrue(first.terminated)
            self.assertEqual(first.stdin.writes, ["scan\n"])
            self.assertEqual(second.stdin.writes, ["scan\n"])
            reader.close()

    def test_reader_restarts_after_helper_process_exit(self):
        mod = load_module()

        class FakeStdin:
            def __init__(self):
                self.writes = []

            def write(self, value):
                self.writes.append(value)

            def flush(self):
                return None

            def close(self):
                return None

        class FakeStdout:
            def close(self):
                return None

        class FakeProcess:
            def __init__(self, exit_code=None):
                self.stdin = FakeStdin()
                self.stdout = FakeStdout()
                self.exit_code = exit_code
                self.terminated = False

            def poll(self):
                return self.exit_code

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

        first = FakeProcess(exit_code=1)
        second = FakeProcess()
        with patch.object(mod.subprocess, "Popen", side_effect=[first, second]):
            reader = mod.CodexTerminalReader(helper_path="helper.ps1", powershell_exe="powershell")
            self.assertTrue(reader.request_scan())
            self.assertEqual(first.stdin.writes, [])
            self.assertEqual(second.stdin.writes, ["scan\n"])
            reader.close()

    def test_reader_drains_last_response_before_replacing_exited_helper(self):
        mod = load_module()

        class FakeStdin:
            def write(self, value):
                return None

            def flush(self):
                return None

            def close(self):
                return None

        class FakeStdout:
            def close(self):
                return None

        class FakeProcess:
            def poll(self):
                return 1

        reader = object.__new__(mod.CodexTerminalReader)
        reader._responses = queue.Queue(maxsize=1)
        reader._process = FakeProcess()
        reader._scan_in_flight = True
        reader._scan_sent_at = 0.0
        reader._responses.put("[]\n")

        with patch.object(mod, "time") as clock:
            clock.monotonic.return_value = 10.0
            self.assertFalse(reader.request_scan())

        self.assertEqual(reader.poll(), [])

    def test_scan_requests_are_coalesced_until_response_arrives(self):
        mod = load_module()

        class FakeStdin:
            def __init__(self):
                self.writes = []

            def write(self, value):
                self.writes.append(value)

            def flush(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = None

            def poll(self):
                return None

        reader = object.__new__(mod.CodexTerminalReader)
        reader._responses = queue.Queue(maxsize=1)
        reader._process = FakeProcess()
        reader._reader_thread = None

        self.assertTrue(reader.request_scan())
        self.assertFalse(reader.request_scan())
        self.assertEqual(reader._process.stdin.writes, ["scan\n"])

        reader._responses.put("[]\n")
        self.assertEqual(reader.poll(), [])
        self.assertTrue(reader.request_scan())
        self.assertEqual(reader._process.stdin.writes, ["scan\n", "scan\n"])

    def test_stalled_scan_is_released_after_timeout_without_queueing(self):
        mod = load_module()

        class FakeStdin:
            def __init__(self):
                self.writes = []

            def write(self, value):
                self.writes.append(value)

            def flush(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = None

            def poll(self):
                return None

        reader = object.__new__(mod.CodexTerminalReader)
        reader._responses = queue.Queue(maxsize=1)
        reader._process = FakeProcess()
        reader._reader_thread = None

        with patch.object(mod.time, "monotonic", side_effect=(0.0, 0.1, 2.0)):
            self.assertTrue(reader.request_scan())
            self.assertFalse(reader.request_scan())
            self.assertTrue(reader.request_scan())

        self.assertEqual(reader._process.stdin.writes, ["scan\n", "scan\n"])

    def test_timed_out_scan_preserves_response_already_waiting_to_be_read(self):
        mod = load_module()

        class FakeStdin:
            def __init__(self):
                self.writes = []

            def write(self, value):
                self.writes.append(value)

            def flush(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = None

            def poll(self):
                return None

        reader = object.__new__(mod.CodexTerminalReader)
        reader._responses = queue.Queue(maxsize=1)
        reader._process = FakeProcess()
        reader._reader_thread = None

        with patch.object(mod.time, "monotonic", side_effect=(0.0, 2.0)):
            self.assertTrue(reader.request_scan())
            reader._responses.put("[]\n")
            self.assertFalse(reader.request_scan())

        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader._process.stdin.writes, ["scan\n"])

    def test_eligible_codex_snapshot_requires_marker_and_excludes_monitor(self):
        mod = load_module()
        good = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 123,
            "title": "task",
            "text": "OpenAI Codex\n› continue",
        }
        self.assertTrue(mod.eligible_codex_snapshot(good))
        self.assertFalse(
            mod.eligible_codex_snapshot(
                {**good, "title": "codex_auto_confirm - monitor"}
            )
        )
        self.assertFalse(mod.eligible_codex_snapshot({**good, "text": "PowerShell only"}))

    def test_codex_title_is_authoritative_when_viewport_has_only_error(self):
        mod = load_module()
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 124,
            "title": "Codex - task",
            "text": "■ unexpected status 503 Service Unavailable: auth_unavailable",
        }

        self.assertTrue(mod.eligible_codex_snapshot(snapshot))

    def test_parse_uia_snapshots_fails_closed_on_malformed_payload(self):
        mod = load_module()
        payload = json.dumps(
            [
                {
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                    "hwnd": 123,
                    "title": "task",
                    "text": "OpenAI Codex",
                }
            ]
        )
        self.assertEqual(len(mod.parse_uia_snapshots(payload)), 1)
        self.assertIsNone(mod.parse_uia_snapshots("{not-json"))


class RecoveryLoopTests(unittest.TestCase):
    def test_process_recovery_sends_once_then_rearms_after_clear(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 777,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 502 Bad Gateway",
        }
        working = {
            **snapshot,
            "text": "OpenAI Codex\nWorking (12s • esc to interrupt)\n"
            "■ unexpected status 502 Bad Gateway",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-502", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([working], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (False, "http-502", None),
        )
        mod.process_codex_recovery_snapshots(
            [{**snapshot, "text": "› Ask Codex to do anything\n82% context left · ? for shortcuts"}],
            tracker, sender,
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-502", True),
        )
        self.assertEqual(calls, [777, 777])

    def test_process_recovery_keeps_latch_on_unknown_read(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 888,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ exceeded retry limit, last status: 429 Too Many Requests",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "retry-limit", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots(None, tracker, sender),
            (False, None, None),
        )
        self.assertEqual(calls, [888])


class RetryStabilityTests(unittest.TestCase):
    def test_reconnecting_progress_is_not_an_error_trigger(self):
        mod = load_module()
        self.assertIsNone(mod.codex_recovery_error_signature("Reconnecting... 3/5"))

    def test_tracker_suppresses_all_retry_progress_until_final_error(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker(required_retry_attempts=5)
        for attempt in (1, 2, 3, 4, 5):
            with self.subTest(attempt=attempt):
                self.assertFalse(
                    tracker.observe_error("http-503", retry_progress=(attempt, 5))
                )
        self.assertTrue(tracker.observe_error("http-503", retry_progress=None))
        self.assertFalse(tracker.observe_error("http-503", retry_progress=None))

    def test_fresh_tracker_sends_continue_for_final_429_retry_limit(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 889,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ exceeded retry limit, last status: 429 Too Many Requests",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "retry-limit", True),
        )
        self.assertEqual(calls, [889])

    def test_error_stays_latched_until_working_then_clears(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 890,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable",
        }
        working_snapshot = {
            **snapshot,
            "text": (
                "OpenAI Codex\nWorking (12s • esc to interrupt)\n"
                "■ unexpected status 503 Service Unavailable"
            ),
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        with patch.object(mod.time, "monotonic", return_value=0.0):
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (False, "http-503", None),
            )
        self.assertEqual(calls, [890])

        self.assertEqual(
            mod.process_codex_recovery_snapshots([working_snapshot], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (False, "http-503", None),
        )
        self.assertEqual(calls, [890])


class ContinueDeliveryTests(unittest.TestCase):
    def test_send_enter_fails_closed_when_input_target_changes(self):
        mod = load_module()
        with patch.object(mod, "find_inputsite_target", side_effect=OSError("window vanished")):
            self.assertFalse(mod.send_enter_via_attached_post(12345))

    def test_send_text_fails_closed_when_input_target_changes(self):
        mod = load_module()
        with patch.object(mod, "find_inputsite_target", side_effect=OSError("window vanished")):
            self.assertFalse(mod.send_text_via_attached_post(12345, "\u7ee7\u7eed"))

    def test_send_text_posts_unicode_chars_to_attached_target(self):
        mod = load_module()
        calls = []
        thread_queries = []
        originals = {
            "find_inputsite_target": mod.find_inputsite_target,
            "GetWindowThreadProcessId": mod.user32.GetWindowThreadProcessId,
            "GetCurrentThreadId": mod.kernel32.GetCurrentThreadId,
            "AttachThreadInput": mod.user32.AttachThreadInput,
            "PostMessageW": mod.user32.PostMessageW,
        }
        try:
            mod.find_inputsite_target = lambda hwnd: 67890
            mod.user32.GetWindowThreadProcessId = (
                lambda hwnd, _unused: thread_queries.append(hwnd) or 1
            )
            mod.kernel32.GetCurrentThreadId = lambda: 2
            mod.user32.AttachThreadInput = lambda *_args: 1
            mod.user32.PostMessageW = (
                lambda hwnd, message, wparam, lparam: calls.append(
                    (hwnd, message, wparam, lparam)
                )
                or 1
            )
            self.assertTrue(mod.send_text_via_attached_post(12345, "\u7ee7\u7eed"))
        finally:
            mod.find_inputsite_target = originals["find_inputsite_target"]
            mod.user32.GetWindowThreadProcessId = originals["GetWindowThreadProcessId"]
            mod.kernel32.GetCurrentThreadId = originals["GetCurrentThreadId"]
            mod.user32.AttachThreadInput = originals["AttachThreadInput"]
            mod.user32.PostMessageW = originals["PostMessageW"]

        self.assertEqual(
            calls,
            [
                (67890, mod.WM_CHAR, ord("\u7ee7"), 0),
                (67890, mod.WM_CHAR, ord("\u7eed"), 0),
            ],
        )
        self.assertEqual(thread_queries, [67890])

    def test_send_continue_writes_distinct_message_before_enter(self):
        mod = load_module()
        calls = []

        with (
            patch.object(
                mod,
                "_post_messages_via_attached_target",
                side_effect=lambda hwnd, messages: calls.append((hwnd, messages)) or True,
            ),
        ):
            self.assertTrue(mod.send_continue(12345))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 12345)
        self.assertEqual(
            "".join(chr(wparam) for message, wparam, _ in calls[0][1] if message == mod.WM_CHAR),
            "\u7ee7\u7eed\uff01",
        )
        self.assertEqual(calls[0][1][-2:], (
            (mod.WM_KEYDOWN, mod.VK_RETURN, mod.ENTER_KEY_LPARAM),
            (mod.WM_KEYUP, mod.VK_RETURN, mod.ENTER_KEYUP_LPARAM),
        ))

    def test_failed_continue_batch_never_uses_a_second_enter_sender(self):
        mod = load_module()
        with (
            patch.object(mod, "_post_messages_via_attached_target", return_value=False),
            patch.object(mod, "send_enter") as send_enter,
        ):
            self.assertFalse(mod.send_continue(12345))
        send_enter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
