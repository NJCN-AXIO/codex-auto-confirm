from __future__ import annotations

import importlib.util
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("codex_auto_confirm.py")
STREAM_ERROR = (
    "■ stream disconnected before completion: Transport error: network error: "
    "error decoding response body"
)
POOL_ERROR = (
    "■ unexpected status 503 Service Unavailable: auth_unavailable: "
    "账号池没有可用账号：候选 1 个，不可用 1 个，模型排除 0 个，额度保留拦截 0\n"
    "个，生图策略拦截 0 个。请前往 Cockpit Tools 查看账号池诊断详情。, "
    "url: http://localhost:57119/v1/responses"
)


def load_module():
    spec = importlib.util.spec_from_file_location("codex_auto_confirm_recovery", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RecoveryMatcherTests(unittest.TestCase):
    def test_stream_disconnect_transport_error_is_recoverable(self):
        mod = load_module()
        self.assertEqual(mod.codex_recovery_error_signature(STREAM_ERROR), "stream-disconnected")

    def test_wrapped_stream_disconnect_is_recoverable(self):
        mod = load_module()
        self.assertEqual(
            mod.codex_recovery_error_signature(STREAM_ERROR.replace(": Transport", ":\nTransport")),
            "stream-disconnected",
        )

    def test_full_auth_unavailable_pool_error_is_recoverable(self):
        mod = load_module()
        self.assertEqual(mod.codex_recovery_error_signature(POOL_ERROR), "http-503")

    def test_stream_error_in_prompt_prose_code_or_monitor_log_is_not_evidence(self):
        mod = load_module()
        for text in (
            "› " + STREAM_ERROR,
            "> " + STREAM_ERROR,
            "The reported error was " + STREAM_ERROR,
            '    "' + STREAM_ERROR + '",',
            "Recoverable error stream-disconnected detected -> Continue attempt 1",
            "network error: error decoding response body",
        ):
            with self.subTest(text=text):
                self.assertIsNone(mod.codex_recovery_error_signature(text))

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

    def test_monitor_output_status_codes_are_not_recovery_errors(self):
        mod = load_module()

        text = (
            "OpenAI Codex\n"
            "• Recoverable error http-503 detected -> Continue attempt 1 "
            "[send_continue=ok]\n"
            "› Ask Codex to do anything"
        )

        self.assertIsNone(mod.codex_recovery_error_signature(text))

    def test_contextual_501_gateway_error_is_recoverable(self):
        mod = load_module()

        self.assertEqual(
            mod.codex_recovery_error_signature(
                "OpenAI Codex\n■ unexpected status 501 Not Implemented"
            ),
            "http-501",
        )


class RecoveryStatusPriorityTests(unittest.TestCase):
    def test_compacting_duration_masks_current_recoverable_errors(self):
        mod = load_module()
        for error in (POOL_ERROR, STREAM_ERROR, "429 Too Many Requests"):
            for status in ("◦ Compacting context (1m 03s • esc to interrupt)",
                           "Compacting context (12s • esc to interrupt)"):
                with self.subTest(error=error, status=status):
                    text = error + "\n" + status + "\n› Ask Codex to do anything"
                    self.assertIsNone(mod.codex_recovery_error_signature(text))
                    self.assertTrue(mod._working_status_active(text))

    def test_compacting_quote_or_missing_duration_does_not_confirm_recovery(self):
        mod = load_module()
        for status in (
            "Compacting context",
            "› Compacting context (1m 03s • esc to interrupt)",
            "The log showed Compacting context (1m 03s • esc to interrupt)",
            '    "Compacting context (1m 03s • esc to interrupt)",',
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    mod.codex_recovery_error_signature(status + "\n" + POOL_ERROR),
                    "http-503",
                )

    def test_historical_compacting_does_not_mask_current_error(self):
        mod = load_module()
        text = ("◦ Compacting context (1m 03s • esc to interrupt)\n"
                + "historical transcript\n" * 45 + POOL_ERROR
                + "\n› Ask Codex to do anything")
        self.assertEqual(mod.codex_recovery_error_signature(text), "http-503")

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

    def test_stale_working_line_far_above_current_error_does_not_mask_it(self):
        mod = load_module()

        text = (
            "OpenAI Codex\n"
            "Working (2m 10s • esc to interrupt)\n"
            + ("historical transcript\n" * 45)
            + "■ unexpected status 503 Service Unavailable\n"
            + "› Ask Codex to do anything"
        )

        self.assertEqual(mod.codex_recovery_error_signature(text), "http-503")

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
    def test_reported_errors_retry_without_click_until_compacting_or_working(self):
        mod = load_module()
        for error, signature in ((STREAM_ERROR, "stream-disconnected"), (POOL_ERROR, "http-503")):
            for status in ("◦ Compacting context (1m 03s • esc to interrupt)",
                           "◦ Working (12s • esc to interrupt)"):
                with self.subTest(signature=signature, status=status):
                    trackers = {}
                    calls = []
                    snapshot = {
                        "class": "CASCADIA_HOSTING_WINDOW_CLASS", "hwnd": 930,
                        "title": "Codex task", "text": error + "\n› Ask Codex to do anything",
                    }
                    sender = lambda hwnd: calls.append(hwnd) or True
                    for now, expected in ((0.0, [(930, signature, True)]), (0.8, []),
                                          (4.9, []), (5.0, [(930, signature, True)])):
                        with patch.object(mod.time, "monotonic", return_value=now):
                            self.assertEqual(
                                mod.process_codex_recovery_snapshots_multi([snapshot], trackers, sender),
                                expected,
                            )
                    active = {**snapshot, "text": error + "\n" + status + "\n› Ask Codex to do anything"}
                    for now in (6.0, 12.0, 60.0):
                        with patch.object(mod.time, "monotonic", return_value=now):
                            self.assertEqual(
                                mod.process_codex_recovery_snapshots_multi([active], trackers, sender), [],
                            )
                    self.assertEqual(calls, [930, 930])
                    self.assertTrue(trackers[930].working_seen)

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

    def test_appended_503_after_capacity_starts_a_new_recovery_attempt(self):
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
            (True, "http-503", True),
        )
        self.assertEqual(calls, [920, 920])

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

    def test_persistent_error_continues_after_successful_post(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        tracker.confirmation_timeout_seconds = 0.0
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
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
            (True, "http-429", True),
        )
        self.assertEqual(calls, [912, 912, 912])

    def test_persistent_429_continues_until_working_even_when_legacy_cap_is_one(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        tracker.confirmation_timeout_seconds = 0.0
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
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (True, "http-429", True),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([working], tracker, sender),
            (False, None, None),
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots([error], tracker, sender),
            (False, "http-429", None),
        )
        self.assertEqual(calls, [921, 921, 921])

    def test_successful_delivery_waits_for_working_before_semantic_follow_up(self):
        mod = load_module()
        tracker = mod.ErrorRecoveryTracker()
        tracker.semantic_retry_seconds = 0.0
        tracker.confirmation_timeout_seconds = 5.0
        calls = []
        snapshot = {
            "class": "CASCADIA_HOSTING_WINDOW_CLASS",
            "hwnd": 925,
            "title": "Codex task",
            "text": "OpenAI Codex\n■ unexpected status 503 Service Unavailable",
        }
        sender = lambda hwnd: calls.append(hwnd) or True

        with patch.object(mod.time, "monotonic", side_effect=(0.0, 1.0, 6.0)):
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (False, "http-503", None),
            )
            self.assertEqual(
                mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                (True, "http-503", True),
            )

        self.assertEqual(calls, [925, 925])

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

    def test_same_visible_error_continues_until_working_status(self):
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

    def test_two_persistent_error_windows_keep_following_up(self):
        mod = load_module()
        trackers = {
            914: mod.ErrorRecoveryTracker(),
            915: mod.ErrorRecoveryTracker(),
        }
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
            tracker.confirmation_timeout_seconds = 0.0
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
            [(914, "http-429", True), (915, "model-capacity", True)],
        )
        self.assertEqual(
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender),
            [(914, "http-429", True), (915, "model-capacity", True)],
        )
        self.assertEqual(calls, [914, 915, 914, 915, 914, 915])

    def test_two_windows_keep_sending_all_recognized_errors_until_working(self):
        mod = load_module()
        trackers = {922: mod.ErrorRecoveryTracker(), 923: mod.ErrorRecoveryTracker()}
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
            tracker.confirmation_timeout_seconds = 0.0
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

        for _ in range(4):
            events = mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender)
            self.assertEqual(
                events,
                [(922, "http-429", True), (923, "http-503", True)],
            )

        self.assertEqual(calls, [922, 923, 922, 923, 922, 923, 922, 923])

    def test_recognized_error_families_use_the_same_continuous_policy(self):
        mod = load_module()
        for text, signature in (
            ("OpenAI Codex\n■ exceeded retry limit", "retry-limit"),
            (
                "OpenAI Codex\nSelected model is at capacity. Please try a different model.",
                "model-capacity",
            ),
            ("OpenAI Codex\n■ unexpected status 502 Bad Gateway", "http-502"),
            ("OpenAI Codex\n■ unexpected status 504 Gateway Timeout", "http-504"),
        ):
            with self.subTest(signature=signature):
                tracker = mod.ErrorRecoveryTracker()
                tracker.semantic_retry_seconds = 0.0
                tracker.confirmation_timeout_seconds = 0.0
                tracker.max_delivery_attempts = 1
                calls = []
                snapshot = {
                    "class": "CASCADIA_HOSTING_WINDOW_CLASS",
                    "hwnd": 924,
                    "title": "Codex task",
                    "text": text,
                }
                sender = lambda hwnd: calls.append(hwnd) or True
                for _ in range(3):
                    self.assertEqual(
                        mod.process_codex_recovery_snapshots([snapshot], tracker, sender),
                        (True, signature, True),
                    )
                self.assertEqual(calls, [924, 924, 924])

    def test_three_persistent_503_windows_keep_following_up(self):
        mod = load_module()
        trackers = {hwnd: mod.ErrorRecoveryTracker() for hwnd in (916, 917, 918)}
        for tracker in trackers.values():
            tracker.semantic_retry_seconds = 0.0
            tracker.confirmation_timeout_seconds = 0.0
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

        for _ in range(4):
            mod.process_codex_recovery_snapshots_multi(snapshots, trackers, sender)

        self.assertEqual(
            calls,
            [916, 917, 918, 916, 917, 918, 916, 917, 918, 916, 917, 918],
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
            (True, "http-504", True),
        )
        self.assertEqual(calls, [902, 902])


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
    def test_main_exits_cleanly_when_an_existing_monitor_owns_the_singleton(self):
        mod = load_module()
        with (
            patch.object(mod, "acquire_single_instance", return_value=False),
            patch("pynput.keyboard.Listener") as listener,
            patch.object(mod.threading, "Thread") as thread,
        ):
            self.assertEqual(mod.main(), 0)
        listener.assert_not_called()
        thread.assert_not_called()

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
                "send_text_via_attached_post",
                side_effect=lambda hwnd, text: calls.append(("text", hwnd, text)) or True,
            ),
            patch.object(
                mod,
                "send_enter",
                side_effect=lambda hwnd: calls.append(("enter", hwnd)) or True,
            ),
        ):
            self.assertTrue(mod.send_continue(12345))

        self.assertEqual(calls, [("text", 12345, "\u7ee7\u7eed\u6267\u884c"), ("enter", 12345)])

    def test_send_continue_fails_closed_when_text_delivery_fails(self):
        mod = load_module()
        with (
            patch.object(mod, "send_text_via_attached_post", return_value=False),
            patch.object(mod, "send_enter") as send_enter,
        ):
            self.assertFalse(mod.send_continue(12345))
        send_enter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
