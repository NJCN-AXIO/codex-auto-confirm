#!/usr/bin/env python3
"""
Codex CLI auto confirm.

F9 toggles auto-confirm. F10 exits.
Terminal approvals require a current semantic UIA menu. Recovery requires a
current error snapshot. Window titles alone never authorize an Enter keypress.
"""

from __future__ import annotations

__version__ = "1.3.1"

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

TARGET_TITLE = os.environ.get("CODEX_AUTO_CONFIRM_TITLE", "codex").lower()
ACTION_REQUIRED_TITLE = os.environ.get("CODEX_AUTO_CONFIRM_ACTION_TITLE", "Action Required").lower()
IDLE_SECONDS = 1.2
LOOP_SECONDS = 0.15
NOT_FOUND_SLEEP_SECONDS = 0.15
AFTER_ENTER_SLEEP_SECONDS = 0.6
retry_enter_seconds_raw = os.environ.get("CODEX_AUTO_CONFIRM_RETRY_SECONDS", "2.0")
RETRY_ENTER_SECONDS = float(retry_enter_seconds_raw) if retry_enter_seconds_raw else None
RECOVERY_POLL_SECONDS = max(
    0.1,
    float(os.environ.get("CODEX_AUTO_CONFIRM_RECOVERY_POLL_SECONDS", "0.25")),
)
RECOVERY_SCAN_TIMEOUT_SECONDS = max(
    0.5,
    float(os.environ.get("CODEX_AUTO_CONFIRM_SCAN_TIMEOUT_SECONDS", "1.5")),
)
RECOVERY_HELPER_RESTART_BACKOFF_SECONDS = max(
    0.5,
    float(os.environ.get("CODEX_AUTO_CONFIRM_HELPER_RESTART_BACKOFF_SECONDS", "1.0")),
)
RECOVERY_DELIVERY_RETRY_SECONDS = max(
    0.1,
    float(os.environ.get("CODEX_AUTO_CONFIRM_DELIVERY_RETRY_SECONDS", "0.35")),
)
RECOVERY_SEMANTIC_RETRY_SECONDS = max(
    IDLE_SECONDS,
    float(os.environ.get("CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS", "3.0")),
)
RECOVERY_AUTH_UNAVAILABLE_RETRY_SECONDS = max(
    1.0, float(os.environ.get("CODEX_AUTO_CONFIRM_AUTH_UNAVAILABLE_RETRY_SECONDS", "5.0")),
)
RECOVERY_MISSING_WINDOW_GRACE_SCANS = max(
    1,
    int(os.environ.get("CODEX_AUTO_CONFIRM_MISSING_WINDOW_GRACE_SCANS", "4")),
)
RECOVERY_CONFIRMATION_TIMEOUT_SECONDS = max(
    RECOVERY_SEMANTIC_RETRY_SECONDS,
    float(os.environ.get("CODEX_AUTO_CONFIRM_CONFIRMATION_TIMEOUT_SECONDS", "5.0")),
)
RECOVERY_MAX_ATTEMPTS = max(
    1,
    min(
        5,
        int(os.environ.get("CODEX_AUTO_CONFIRM_MAX_ATTEMPTS", "3")),
    ),
)
DESKTOP_POLL_SECONDS = max(
    0.25,
    float(os.environ.get("CODEX_AUTO_CONFIRM_DESKTOP_POLL_SECONDS", "1.0")),
)
# Capacity errors keep a paced recovery pending until Working/Compacting is
# read back.  Other errors retain the one-shot episode latch.  Failed input
# posts remain bounded; drafting and physical input defer every capacity retry.
RECOVERY_RETRY_SECONDS = None
AUTO_CONTINUE_MESSAGE = "\u7ee7\u7eed\uff01"
RECOVERY_TEXT_ZH = AUTO_CONTINUE_MESSAGE
RECOVERY_TEXT_EN = "continue"
CONFIGURED_RECOVERY_TEXT = os.environ.get("CODEX_AUTO_CONFIRM_RECOVERY_TEXT") or None
TERMINAL_PROMPT_MARKERS = ("›", "»", ">")
if getattr(sys, "frozen", False):
    UIA_HELPER_SCRIPT_PATH = os.path.join(
        getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
        "codex_terminal_uia_reader.ps1",
    )
else:
    UIA_HELPER_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "codex_terminal_uia_reader.ps1")
POWERSHELL_EXE = os.environ.get("CODEX_AUTO_CONFIRM_POWERSHELL", "powershell.exe")

VK_RETURN = 0x0D
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
ENTER_KEY_LPARAM = 0x001C0001
ENTER_KEYUP_LPARAM = 0xC01C0001
INPUT_KEYBOARD = 1
PM_NOREMOVE = 0

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class INPUTUNION(ctypes.Union):
    _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (("type", wintypes.DWORD), ("union", INPUTUNION))


running = True
auto_confirm = True
_SINGLETON_MUTEX_NAME = "Local\\CodexAutoConfirmMonitor"
_singleton_mutex_handle = None

CDP_PORT = int(os.environ.get("CODEX_AUTO_CONFIRM_CDP_PORT", "27374"))
CDP_TIMEOUT_SECONDS = float(os.environ.get("CODEX_AUTO_CONFIRM_CDP_TIMEOUT", "0.8"))
ALLOW_ONCE_TOKENS = ("\u5141\u8bb8\u4e00\u6b21", "allow once")
DENY_TOKENS = ("\u62d2\u7edd", "deny")
PERMANENT_ALLOW_TOKENS = ("\u59cb\u7ec8\u5141\u8bb8", "always allow", "\u6c38\u4e45\u5141\u8bb8")

CODEX_HOST_PROCESS_NAMES = frozenset(
    value.strip().casefold()
    for value in os.environ.get(
        "CODEX_AUTO_CONFIRM_PROCESS_NAMES", "WindowsTerminal.exe,conhost.exe,codex.exe"
    ).split(",")
    if value.strip()
)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

DESKTOP_READ_EXPRESSION = r'''(() => {
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const text = (el) => (el.innerText || el.getAttribute("aria-label") || el.textContent || "").trim();
  return [...document.querySelectorAll('button,[role="dialog"]')]
    .filter(visible)
    .map((el) => ({text: text(el), visible: true}));
})()'''

def normalize_visible_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def acquire_single_instance() -> bool:
    """Allow only one monitor worker to send recovery input at a time."""
    global _singleton_mutex_handle
    if _singleton_mutex_handle:
        return True
    handle = kernel32.CreateMutexW(None, False, _SINGLETON_MUTEX_NAME)
    if not handle:
        return False
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _singleton_mutex_handle = handle
    return True


def release_single_instance() -> None:
    global _singleton_mutex_handle
    if not _singleton_mutex_handle:
        return
    try:
        kernel32.CloseHandle(_singleton_mutex_handle)
    finally:
        _singleton_mutex_handle = None


RECOVERY_ERROR_CONTEXT = (
    "unexpected status",
    "last status",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)
RECOVERY_ERROR_GLYPHS = ("\u25a0", "\u2716", "\u00d7", "\u26a0", "\u274c")
RECOVERY_STATUS_CODES = ("500", "501", "502", "503", "504")
RECOVERY_TERMINAL_STATUS_MARKERS = ("conversation interrupted",)
STREAM_DISCONNECT_MARKER = "stream disconnected before completion"
STREAM_DECODE_MARKER = "error decoding response body"
STRUCTURED_ERROR_FIELD = re.compile(r"[\"']error[\"']\s*:")
STRUCTURED_MESSAGE_FIELD = re.compile(r"[\"']message[\"']\s*:")
CODEX_TERMINAL_MARKERS = ("openai codex", "ask codex to do anything", "codex cli")
CODEX_TITLE_MARKER = re.compile(r"(?<![a-z0-9])codex(?![a-z0-9])")

# Since codex-cli 0.15x the approval UI is rendered inside the TUI instead of
# changing the Windows Terminal title to ``Action Required``.  Keep the
# matcher deliberately semantic: a heading plus a one-time/normal approval
# option must be visible in the same UIA viewport.  This avoids treating old
# transcript text, ``always allow`` options, or denial menus as approval.
APPROVAL_HEADINGS = (
    "would you like to run the following command?",
    "would you like to make the following edits?",
    "would you like to grant these permissions?",
    "would you like to send input to the existing terminal?",
    "do you want to approve network access to",
)
APPROVAL_ONCE_OPTIONS = (
    "yes, proceed",
    "yes, just this once",
    "allow once",
    "允许一次",
)
ACTION_REQUIRED_CONFIRMATION_FOOTER = "press enter to confirm or esc to cancel"


def normalize_terminal_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def parse_uia_snapshots(payload: str) -> list[dict] | None:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, dict)]


def eligible_codex_snapshot(snapshot: dict) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("class") != "CASCADIA_HOSTING_WINDOW_CLASS":
        return False
    try:
        hwnd = int(snapshot.get("hwnd", 0))
    except (TypeError, ValueError):
        return False
    if hwnd <= 0:
        return False
    title = str(snapshot.get("title", ""))
    text = str(snapshot.get("text", ""))
    haystack = normalize_terminal_text(f"{title}\n{text}")
    # Only the title identifies the monitor itself.  The terminal transcript
    # may legitimately mention this script while the real Codex window is
    # still the target.
    if "codex_auto_confirm" in normalize_terminal_text(title):
        return False
    # A second Codex window may keep the generic Windows Terminal title and
    # expose only the error line in UIA.  A recognized recovery error is a
    # stronger signal than the missing title marker, so keep that window in
    # the window-level recovery pass.  This remains scoped to the terminal
    # host class and the conservative matcher below; ordinary terminal text
    # is still ignored.
    has_recovery_error = bool(_unmasked_recovery_error_signature(text))
    has_action_required_menu = (
        action_required_title_matches(title)
        and action_required_options_visible(text)
    )
    return (
        any(marker in haystack for marker in CODEX_TERMINAL_MARKERS)
        or bool(CODEX_TITLE_MARKER.search(normalize_terminal_text(title)))
        # New approval overlays can appear in a newly titled terminal before
        # the title/body contains a Codex marker.  The semantic menu itself is
        # a stronger signal than a generic terminal title.
        or codex_approval_prompt_visible(text)
        or has_recovery_error
        or has_action_required_menu
        # Generic session titles still expose authoritative Codex status.
        # This admits a suppression/readback signal, never an input action.
        or _working_status_active(text)
    )


def _selected_approval_option(text: str) -> str | None:
    """Distinguish a numbered menu selection from the identically marked composer.

    None means no numbered selection; an empty string means the selected row
    is not an authorized one-time option or lacks the rest of the menu.
    """
    # Some UIA ranges concatenate adjacent options, including their shortcut
    # suffixes. Restore those boundaries before checking the selected row.
    lines = re.sub(
        r"(?<=\))\s*(?=(?:[›»>]\s*)?\d+[.)]\s+(?:yes|no)\b)",
        "\n", text or "", flags=re.IGNORECASE,
    ).splitlines()
    selected = [
        (index, re.sub(r"^[›»>]\s*\d+[.)]\s*", "", normalize_visible_text(line)))
        for index, line in enumerate(lines)
        if re.match(r"^[›»>]\s*\d+[.)]\s+", normalize_visible_text(line))
    ]
    if not selected:
        return None
    index, option = selected[-1]
    if any(line.lstrip().startswith(TERMINAL_PROMPT_MARKERS) for line in lines[index + 1:]):
        return ""
    normal_option = any(option == token or option.startswith(token + " ") for token in APPROVAL_ONCE_OPTIONS)
    following = " ".join(normalize_visible_text(line) for line in lines[index + 1:])
    has_deny = bool(re.search(r"(?:^|\s)\d+[.)]\s+no,", following))
    has_confirmation_footer = ACTION_REQUIRED_CONFIRMATION_FOOTER in following
    # The Action Required provider can expose only the selected one-time row
    # and its confirmation footer; the visible No row is not guaranteed.  A
    # selected permanent option remains blocked even when that footer exists.
    return option if normal_option and (has_deny or has_confirmation_footer) else ""


def codex_approval_prompt_visible(text: str) -> bool:
    """Return whether the current visible TUI contains a one-shot approval.

    The heading and option are required together because UIA's visible range
    can include stale transcript lines while an unrelated prompt is active.
    """
    # Approval bodies can exceed the recovery status area's 40-row window.
    # UIA already supplied the visible viewport, so retain the full menu.
    lines = [normalize_visible_text(line) for line in _recovery_output_lines(text, status_area_only=False)]
    # Transcript bullets ("- Would you like...", "• Yes, proceed") are not
    # active controls.  Active approval overlays render these as standalone
    # lines without a transcript marker.
    lines = [line for line in lines if line and not line.startswith(TERMINAL_PROMPT_MARKERS + ("-", "•", "│"))]
    lines = [re.sub(r"^\d+[.)]\s+", "", line) for line in lines]
    has_heading = any(
        any(line == heading or line.startswith(heading + " ") for heading in APPROVAL_HEADINGS)
        for line in lines
    )
    selected = _selected_approval_option(text)
    if selected is not None:
        has_once_option = bool(selected)
    else:
        raw_lines = [normalize_visible_text(line) for line in (text or "").splitlines()]
        raw_headings = [
            index for index, line in enumerate(raw_lines)
            if any(line == heading or line.startswith(heading + " ") for heading in APPROVAL_HEADINGS)
        ]
        if raw_headings and any(
            line.startswith(TERMINAL_PROMPT_MARKERS)
            for line in raw_lines[raw_headings[-1] + 1:]
        ):
            return False
        has_once_option = any(
            any(line == option or line.startswith(option + " ") for option in APPROVAL_ONCE_OPTIONS)
            for line in lines
        )
    if not has_heading or not has_once_option:
        return False
    heading_index = max(
        index for index, line in enumerate(lines)
        if any(line == heading or line.startswith(heading + " ") for heading in APPROVAL_HEADINGS)
    )
    # A live menu supersedes status text painted above it. A newer processing
    # status below the menu means the menu is historical, so do not confirm it.
    return not _recovery_status_active("\n".join(lines[heading_index + 1:]))


def action_required_options_visible(text: str) -> bool:
    """Recognize an Action Required menu whose heading is outside UIA text.

    Windows Terminal can expose the title and the numbered options through
    different UIA providers. Preserve the selected row while parsing: the
    prompt marker is also used by the live composer and must not be discarded
    as an input row before the menu is classified.
    """
    lines = [
        normalize_visible_text(line)
        for line in (text or "").splitlines()
    ]
    if not lines:
        return False
    raw_lines = [normalize_visible_text(line) for line in (text or "").splitlines()]
    if any(
        line.startswith(TERMINAL_PROMPT_MARKERS)
        and not re.match(r"^[›»>]\s*\d+[.)]\s+", line)
        for line in raw_lines
    ):
        return False
    unmarked_lines = [re.sub(r"^[›»>]\s*", "", line) for line in lines]
    numbered_options = [
        re.sub(r"^\s*\d+[.)]\s*", "", line)
        for line in unmarked_lines
        if re.match(r"^\s*\d+[.)]\s+", line)
    ]
    has_once = any(
        option == allowed or option.startswith(allowed + " ")
        for option in numbered_options
        for allowed in APPROVAL_ONCE_OPTIONS
    )
    has_deny = any(
        option == "no" or option.startswith(("no,", "no:", "no "))
        for option in numbered_options
    )
    selected = _selected_approval_option(text)
    if selected is not None:
        # A selected one-time option plus the explicit confirmation footer is
        # sufficient when UIA omitted the No row.  The helper returns an empty
        # string for a selected permanent/deny option, so those stay blocked.
        return bool(selected) and (
            has_deny or ACTION_REQUIRED_CONFIRMATION_FOOTER in " ".join(lines)
        )
    # Without a selected marker retain the conservative legacy requirement:
    # both one-time and deny options must be visible.
    return has_once and has_deny


class CodexTerminalReader:
    def __init__(
        self,
        helper_path: str = UIA_HELPER_SCRIPT_PATH,
        powershell_exe: str = POWERSHELL_EXE,
    ) -> None:
        self._responses: queue.Queue[str] = queue.Queue(maxsize=1)
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._scan_in_flight = False
        self._scan_sent_at: float | None = None
        self._helper_path = helper_path
        self._powershell_exe = powershell_exe
        self._closed = False
        self._next_restart_at = 0.0
        self._helper_failures = 0
        self._start_process()

    def _note_helper_failure(self, reason: str) -> None:
        self._helper_failures = getattr(self, "_helper_failures", 0) + 1
        if self._helper_failures == 1:
            print(f"  UIA helper unhealthy: {reason}; recovering", flush=True)
        # Permit one immediate recovery from a transient failure. Repeated
        # failures must wait, even when Popen itself keeps succeeding.
        delay = RECOVERY_HELPER_RESTART_BACKOFF_SECONDS if self._helper_failures > 1 else 0.0
        self._next_restart_at = time.monotonic() + delay

    def _start_process(self) -> bool:
        if getattr(self, "_closed", False):
            return False
        now = time.monotonic()
        if now < getattr(self, "_next_restart_at", 0.0):
            return False
        # A retired drain can still hold a line read before termination. Bind
        # each helper to its own queue so that line cannot replace fresh data.
        responses: queue.Queue[str] = queue.Queue(maxsize=1)
        self._responses = responses
        try:
            process = subprocess.Popen(
                [
                    self._powershell_exe,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    self._helper_path,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            self._process = None
            self._note_helper_failure(f"launch failed ({type(exc).__name__})")
            self._next_restart_at = max(
                self._next_restart_at, now + RECOVERY_HELPER_RESTART_BACKOFF_SECONDS
            )
            return False
        self._process = process
        self._scan_in_flight = False
        self._scan_sent_at = None
        self._reader_thread = threading.Thread(
            target=self._drain_stdout, args=(process, responses), daemon=True
        )
        self._reader_thread.start()
        return True

    def _stop_process(self, process) -> None:
        if process is None:
            return
        # The drain thread can hold stdout's buffer lock while waiting for a
        # silent helper. Closing that stream first would deadlock the monitor's
        # restart path. End the helper before touching either pipe.
        try:
            process.terminate()
        except (OSError, AttributeError):
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, OSError, AttributeError):
                return
        except (OSError, AttributeError):
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except (OSError, ValueError, AttributeError):
            pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except (OSError, ValueError, AttributeError):
            pass

    def restart(self, *, force: bool = False, reason: str | None = None) -> bool:
        """Replace an unresponsive UIA helper without restarting the monitor."""
        if getattr(self, "_closed", False):
            return False
        # Some focused tests construct the reader with ``object.__new__`` and
        # inject a fake process.  Preserve that lightweight seam while real
        # readers use the full process replacement path above.
        if not hasattr(self, "_powershell_exe"):
            self._scan_in_flight = False
            self._scan_sent_at = None
            return True
        # force requests a recycle, but never bypasses failure throttling.
        if reason is None and time.monotonic() < getattr(self, "_next_restart_at", 0.0):
            return False
        if reason is not None:
            self._note_helper_failure(reason)
        old_process = getattr(self, "_process", None)
        self._process = None
        self._scan_in_flight = False
        self._scan_sent_at = None
        # Detach retired output even when backoff postpones the next helper.
        self._responses = queue.Queue(maxsize=1)
        self._stop_process(old_process)
        return self._start_process()

    def _drain_stdout(self, process=None, responses=None) -> None:
        process = self._process if process is None else process
        responses = self._responses if responses is None else responses
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                while True:
                    try:
                        responses.put_nowait(line)
                        break
                    except queue.Full:
                        try:
                            responses.get_nowait()
                        except queue.Empty:
                            break
        except (OSError, ValueError, TypeError):
            # A helper that closes or exposes a broken pipe is unhealthy; the
            # foreground loop will observe the missing response and restart it.
            return

    def request_scan(self) -> bool:
        if getattr(self, "_closed", False):
            return False
        process = getattr(self, "_process", None)
        exit_code = process.poll() if process is not None else None
        if process is None or exit_code is not None or process.stdin is None:
            # Drain a response that was written just before the helper exited
            # before replacing the process; otherwise the only evidence of a
            # short-lived visible error could be discarded.
            if not self._responses.empty():
                return False
            reason = None if process is None else (
                f"exited with code {exit_code}" if exit_code is not None else "stdin unavailable"
            )
            if not self.restart(reason=reason):
                return False
            process = self._process
        if process is None or process.stdin is None:
            return False
        now = time.monotonic()
        scan_in_flight = getattr(self, "_scan_in_flight", False)
        scan_sent_at = getattr(self, "_scan_sent_at", None)
        if scan_in_flight:
            if not self._responses.empty():
                return False
            if (
                scan_sent_at is None
                or now - scan_sent_at < RECOVERY_SCAN_TIMEOUT_SECONDS
            ):
                return False
            while True:
                try:
                    self._responses.get_nowait()
                except queue.Empty:
                    break
            if not self.restart(force=True, reason="scan timed out"):
                return False
            process = self._process
            if process is None or process.stdin is None:
                return False
        try:
            process.stdin.write("scan\n")
            process.stdin.flush()
            self._scan_in_flight = True
            self._scan_sent_at = now
            return True
        except (OSError, ValueError) as exc:
            self._scan_in_flight = False
            self._scan_sent_at = None
            self.restart(force=True, reason=f"scan write failed ({type(exc).__name__})")
            return False

    def poll(self) -> list[dict] | None:
        latest: str | None = None
        while True:
            try:
                latest = self._responses.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._scan_in_flight = False
            self._scan_sent_at = None
        if latest is None:
            return None
        parsed = parse_uia_snapshots(latest)
        if parsed is None:
            self.restart(force=True, reason="invalid snapshot response")
        else:
            self._helper_failures = 0
            self._next_restart_at = 0.0
        return parsed

    def close(self) -> None:
        self._closed = True
        process = getattr(self, "_process", None)
        self._process = None
        self._scan_in_flight = False
        self._scan_sent_at = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write("quit\n")
                process.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
        self._stop_process(process)


def _recovery_line_has_context(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith(("›", ">")):
        return False
    if any(stripped.startswith(glyph) for glyph in RECOVERY_ERROR_GLYPHS):
        return True
    if any(token in line for token in RECOVERY_ERROR_CONTEXT):
        return True
    # Accept an explicit HTTP status form, but not monitor log text such as
    # ``http-503`` which can appear in the visible transcript after the
    # monitor has reported its own previous attempt.
    return bool(re.search(r"\bhttp(?:/\d(?:\.\d)?)?\s+50[0-4]\b", line))


def _structured_api_error_in_window(lines: list[str], index: int) -> bool:
    """Recognize a generic Codex API error envelope without enumerating messages.

    Codex renders API failures as a visible error-glyph line followed by a JSON
    object.  The message is intentionally not inspected: new server-side error
    wording must use the same recovery path as known errors.  Requiring both
    ``error`` and ``message`` fields within a short window keeps ordinary
    transcript prose and copied examples out of the matcher.
    """
    stripped = lines[index].lstrip()
    if not any(stripped.startswith(glyph) for glyph in RECOVERY_ERROR_GLYPHS):
        return False
    window = " ".join(
        normalize_terminal_text(part) for part in lines[index : index + 10]
    )
    return bool(
        STRUCTURED_ERROR_FIELD.search(window)
        and STRUCTURED_MESSAGE_FIELD.search(window)
    )


def _current_viewport_bounds(lines: list[str]) -> tuple[int, int]:
    marker_indexes = [
        index
        for index, raw_line in enumerate(lines)
        if "ask codex to do anything" in normalize_terminal_text(raw_line)
    ]
    if marker_indexes:
        marker = marker_indexes[-1]
        # UIA may expose the live status line immediately after the input
        # prompt marker.  Keep a short tail after the marker so Working is
        # authoritative even when the status and prompt are split into
        # separate TextPattern lines.
        return max(0, marker - 24), marker + 9
    return max(0, len(lines) - 40), len(lines)


def _current_viewport_lines(text: str) -> list[str]:
    """Prefer the live status area over historical transcript lines."""
    lines = (text or "").splitlines()
    start, end = _current_viewport_bounds(lines)
    return lines[start:end]


def _terminal_footer_line(line: str) -> bool:
    content = normalize_terminal_text(line)
    return bool(
        re.match(r"^(?:gpt-[\w.-]+|o\d[\w.-]*)\s+.*·", content)
        or re.match(r"^[\d%\s]+context left\b", content)
        or content.endswith("for shortcuts")
    )


def _terminal_footer_tail(lines: list[str]) -> bool:
    return all(
        not re.sub(r"[\s\u2800-\u28ff]", "", line)
        or _terminal_footer_line(line)
        for line in lines
    )


def _terminal_draft_visible(text: str) -> bool:
    """A nonempty composer belongs to the user, even while an error is visible."""
    lines = (text or "").splitlines()
    prompts = [i for i, line in enumerate(lines) if line.lstrip().startswith(TERMINAL_PROMPT_MARKERS)]
    if not prompts:
        return False
    # Wrapped Markdown quotes can begin with ">" too. Only a prompt at the
    # outer composer indentation can replace the current input boundary.
    prompt_indent = min(len(lines[i]) - len(lines[i].lstrip()) for i in prompts)
    index = next(
        i for i in reversed(prompts)
        if len(lines[i]) - len(lines[i].lstrip()) == prompt_indent
    )
    if _selected_approval_option(text) and (
        codex_approval_prompt_visible(text) or action_required_options_visible(text)
    ):
        return False
    # Transcript user messages use the same glyph as the live composer. An
    # unindented assistant/tool/status row below it proves it was submitted.
    # Wrapped draft rows stay indented and must never clear this protection.
    for line in lines[index + 1:]:
        if line and not line[0].isspace() and (
            line.startswith(("•", "◦", "■", "✔"))
            or normalize_terminal_text(line) in APPROVAL_HEADINGS
        ):
            return False
    content = normalize_terminal_text(lines[index].lstrip()[1:])
    # Astra's empty composer can contain decorative Braille particles. Only
    # the known placeholder is exempt; real user content remains a draft.
    if re.sub(r"[\u2800-\u28ff]", "", content).strip() == "ask codex to do anything":
        return not _terminal_footer_tail(lines[index + 1:])
    if content:
        return True
    # Blank rows belong to multiline input too. Only a recognized footer ends
    # the composer; a middle dot in the user's prose is not a footer.
    for row_index in range(index + 1, len(lines)):
        line = lines[row_index]
        content = normalize_terminal_text(line)
        if not content:
            continue
        if _terminal_footer_line(line):
            # A copied model/footer row inside a multiline draft is still
            # user content. The real footer ends the input at the viewport
            # tail, followed only by footer rows or decorative particles.
            if _terminal_footer_tail(lines[row_index + 1:]):
                break
            return True
        if not line[0].isspace():
            break
        return True
    return False


def _recovery_output_lines(text: str, *, status_area_only: bool = True) -> list[str]:
    """Exclude input rows and their wrapped continuation rows from error evidence."""
    output = []
    in_prompt = False
    lines = (text or "").splitlines()
    start, end = _current_viewport_bounds(lines) if status_area_only else (0, len(lines))
    # Establish prompt ownership before cropping. A long submitted user
    # message can begin above the status area and quote a status near its end.
    for index, line in enumerate(lines[:end]):
        if line.lstrip().startswith(TERMINAL_PROMPT_MARKERS):
            in_prompt = True
            continue
        if in_prompt and (not line.strip() or line[0].isspace()):
            continue
        in_prompt = False
        if index >= start:
            output.append(line)
    return output


def _retry_progress(text: str) -> tuple[int, int] | None:
    match = re.search(r"reconnecting\s*\.\.\.\s*(\d+)\s*/\s*(\d+)", text.casefold())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _conversation_interrupted_active(text: str) -> bool:
    """Return whether the current viewport reports a cancellation status."""
    for raw_line in _recovery_output_lines(text):
        lowered = normalize_terminal_text(raw_line)
        lowered = lowered.lstrip("".join(RECOVERY_ERROR_GLYPHS) + " \ufe0f")
        if any(lowered.startswith(marker) for marker in RECOVERY_TERMINAL_STATUS_MARKERS):
            return True
    return False


def _status_candidate(line: str) -> str:
    """Normalize a possible live status line without accepting prompt quotes."""
    lowered = normalize_terminal_text(line)
    # Codex has used several spinner/decorative prefixes across CLI releases.
    # Strip only leading decoration here; the error matcher keeps its own
    # strict glyph boundary and is unaffected.
    decoration = "\u25e6\u2022\u25aa\u25cf\u25c9\u25cb\u25a0\u2716\u00d7\u26a0\u274c"
    lowered = re.sub(rf"^[{re.escape(decoration)}\u2800-\u28ff\s]+", "", lowered)
    if lowered.startswith(TERMINAL_PROMPT_MARKERS):
        return ""
    return re.sub(r"^[◦•]\s*", "", lowered).strip()


def _working_status_line(line: str) -> bool:
    """Return True for the visible Codex Working duration status line.

    Codex has used both English and localized duration units.  The status is
    authoritative even when an older error line remains in the same viewport.
    """
    candidate = _status_candidate(line)
    if not candidate:
        return False
    # UIA may expose the spinner as its own range between the label and the
    # duration. Permit only known decorative/spinner characters there; an
    # arbitrary word such as ``Working foo (26s)`` remains ordinary prose.
    bridge = r"[\u25e6\u2022\u25aa\u25cf\u25c9\u25cb\u25a0\u2716\u00d7\u26a0\u274c\u2800-\u28ff\s]*"
    if re.match(rf"^working\s*{bridge}\(\s*\d+[^)]*\)", candidate):
        return True
    return bool(
        re.match(
            r"^(?:compacting\s+context|\u6b63\u5728\u538b\u7f29\u4e0a\u4e0b\u6587)"
            rf"\s*{bridge}(?:\([^)]*\))?(?:\s|$)",
            candidate,
        )
    )


def _recovery_status_active(text: str) -> bool:
    lines = _current_viewport_lines(text)
    current_text = "\n".join(lines)
    if _retry_progress(current_text) is not None:
        return True
    if _working_status_active(text):
        return True
    return _conversation_interrupted_active(text)


def _working_status_active(text: str) -> bool:
    lines = [line for line in _recovery_output_lines(text) if line.strip()]
    assistant_paragraph_indent = None
    # UIA can split the status label and its duration/interrupt suffix across
    # adjacent TermControl ranges.  Reassemble a short local window so a live
    # Working state cannot be mistaken for a stale error and trigger repeats.
    for index, raw_line in enumerate(lines):
        normalized = _status_candidate(raw_line)
        if not normalized:
            continue
        joined = " ".join(
            normalize_terminal_text(part) for part in lines[index : index + 3]
        )
        is_status = _working_status_line(joined)
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)
        if stripped.startswith(("•", "◦")) and not is_status:
            assistant_paragraph_indent = indent
        elif assistant_paragraph_indent is not None and indent <= assistant_paragraph_indent:
            assistant_paragraph_indent = None
        if is_status:
            # Indented examples under an assistant paragraph are transcript
            # text. Independent indented statuses and explicit UIA status
            # bullets still retain their existing suppression priority.
            if (
                assistant_paragraph_indent is not None
                and indent > assistant_paragraph_indent
                and not stripped.startswith(("•", "◦"))
            ):
                continue
            return True

    # UIA can place a live Working/Compacting row just outside the cropped
    # current viewport when a long transcript and the composer are exposed by
    # separate ranges.  The row is still authoritative if it has the exact
    # duration form, so make one conservative full-text pass before treating
    # the older error as actionable.  Prompt-prefixed rows are rejected by
    # _status_candidate; this remains fail-closed for a user's draft.
    # Apply the same prompt ownership rules as the normal viewport pass so a
    # quoted/indented Working example in a submitted message cannot suppress
    # a real current error. This still retains live status rows above the
    # cropped viewport.
    full_lines = [
        line for line in _recovery_output_lines(text, status_area_only=False)
        if line.strip()
    ]
    full_assistant_paragraph_indent = None
    for index, raw_line in enumerate(full_lines):
        normalized = _status_candidate(raw_line)
        if not normalized:
            continue
        joined = " ".join(
            normalize_terminal_text(part) for part in full_lines[index : index + 3]
        )
        is_status = _working_status_line(joined)
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)
        if stripped.startswith(("\u2022", "\u25e6")) and not is_status:
            full_assistant_paragraph_indent = indent
        elif (
            full_assistant_paragraph_indent is not None
            and indent <= full_assistant_paragraph_indent
        ):
            full_assistant_paragraph_indent = None
        if is_status and not (
            full_assistant_paragraph_indent is not None
            and indent > full_assistant_paragraph_indent
            and not stripped.startswith(("\u2022", "\u25e6"))
        ):
            return True
    return False


def _unmasked_recovery_error_signature(text: str) -> str | None:
    latest_signature: str | None = None
    stream_disconnect_pending = False
    lines = _recovery_output_lines(text)
    for index, raw_line in enumerate(lines):
        line = normalize_terminal_text(raw_line)
        if not line or line.startswith(TERMINAL_PROMPT_MARKERS):
            continue
        # TextPattern can wrap the capacity sentence across adjacent lines.
        # Inspect a short forward window while preserving the normal
        # bottom-most-error-wins scan below, so a newer gateway line can still
        # replace the capacity signature.
        capacity_line = line.lstrip("".join(RECOVERY_ERROR_GLYPHS) + " \ufe0f")
        if capacity_line.startswith("selected model is at"):
            wrapped = " ".join(
                normalize_terminal_text(part)
                for part in lines[index : index + 3]
            )
            if (
                "selected model is at capacity" in wrapped
                and "please try a different model" in wrapped
            ):
                latest_signature = "model-capacity"
                continue
        stripped_line = line.lstrip()
        starts_with_error_glyph = any(
            stripped_line.startswith(glyph) for glyph in RECOVERY_ERROR_GLYPHS
        )
        if starts_with_error_glyph and _structured_api_error_in_window(lines, index):
            latest_signature = "api-error"
            continue
        if starts_with_error_glyph and STREAM_DISCONNECT_MARKER in line:
            stream_disconnect_pending = True
            if STREAM_DECODE_MARKER in line:
                latest_signature = "stream-disconnected"
            continue
        if stream_disconnect_pending:
            if STREAM_DECODE_MARKER in line:
                latest_signature = "stream-disconnected"
            stream_disconnect_pending = False
        if "exceeded retry limit" in line:
            # Keep scanning: a newer error line may be appended below an old
            # retry-limit message in the same visible viewport.
            latest_signature = "retry-limit"
            continue
        if "429 too many requests" in line:
            latest_signature = "http-429"
            continue
        status_match = False
        if _recovery_line_has_context(line):
            for status in RECOVERY_STATUS_CODES:
                if re.search(rf"(?<!\d){status}(?!\d)", line):
                    latest_signature = f"http-{status}"
                    status_match = True
                    break
        # Error glyphs are the terminal's semantic boundary for failures.  Do
        # not require a growing keyword list: a newly introduced provider or
        # protocol error must use the same single Continue! recovery path.
        if (
            starts_with_error_glyph
            and "completed successfully" not in line
            and not status_match
        ):
            latest_signature = "visible-error"
    return latest_signature


def _recovery_state(text: str) -> tuple[str | None, bool, bool]:
    signature = _unmasked_recovery_error_signature(text)
    working_active = _working_status_active(text)
    status_active = _recovery_status_active(text)
    interrupted_active = _conversation_interrupted_active(text)
    # An explicit Conversation interrupted status is a user stop.  It wins
    # over every stale error, including a capacity line; only a live Working
    # duration can represent an active task.
    if signature == "model-capacity" and not working_active and not interrupted_active:
        status_active = False
    return (signature, status_active, working_active)


def codex_recovery_error_signature(text: str) -> str | None:
    signature, status_active, _working_active = _recovery_state(text)
    if status_active:
        return None
    return signature

def desktop_allow_once_visible(elements: list[dict]) -> bool:
    for element in elements:
        if not element.get("visible"):
            continue
        text = normalize_visible_text(str(element.get("text", "")))
        if not text or any(token in text for token in DENY_TOKENS + PERMANENT_ALLOW_TOKENS):
            continue
        if any(token in text for token in ALLOW_ONCE_TOKENS):
            return True
    return False

def codex_page_targets(targets: list[dict]) -> list[dict]:
    return [target for target in targets if target.get("type") == "page" and normalize_visible_text(str(target.get("title", ""))) == "codex" and target.get("webSocketDebuggerUrl")]

def discover_cdp_targets(port: int = CDP_PORT) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=CDP_TIMEOUT_SECONDS) as response:
        return codex_page_targets(json.load(response))

def read_desktop_allow_once(port: int = CDP_PORT, timeout_seconds: float = CDP_TIMEOUT_SECONDS) -> bool:
    ws = None
    try:
        targets = discover_cdp_targets(port)
        if not targets:
            return False
        import websocket
        ws = websocket.create_connection(targets[0]["webSocketDebuggerUrl"], timeout=timeout_seconds, suppress_origin=True)
        expression = DESKTOP_READ_EXPRESSION
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            ws.settimeout(remaining)
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break
        elements = message.get("result", {}).get("result", {}).get("value", [])
        return desktop_allow_once_visible(elements if isinstance(elements, list) else [])
    except Exception:
        return False
    finally:
        if ws is not None:
            try:
                ws.close(timeout=0)
            except Exception:
                pass

class DesktopApprovalTracker:
    def __init__(
        self,
        retry_seconds: float | None = RETRY_ENTER_SECONDS,
        *,
        delivery_retry_seconds: float = RECOVERY_DELIVERY_RETRY_SECONDS,
        max_delivery_attempts: int = RECOVERY_MAX_ATTEMPTS,
    ) -> None:
        self.retry_seconds = retry_seconds
        # Keep the legacy retry_seconds argument for callers that construct
        # this tracker directly.  A successful desktop Enter is latched until
        # the DOM readback clears the allow-once control; only failed posts
        # receive bounded timed retries.
        self.delivery_retry_seconds = max(0.1, float(delivery_retry_seconds))
        self.max_delivery_attempts = max(1, int(max_delivery_attempts))
        self.was_visible = False
        self.last_fire_at: float | None = None
        self.last_delivery_at: float | None = None
        self.delivery_attempts = 0
        self.delivery_pending = False

    def observe(self, is_visible: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not is_visible:
            self.was_visible = False
            self.last_fire_at = None
            self.last_delivery_at = None
            self.delivery_attempts = 0
            self.delivery_pending = False
            return False
        if self.was_visible:
            if not self.delivery_pending:
                return False
            if self.delivery_attempts >= self.max_delivery_attempts:
                return False
            if (
                self.last_delivery_at is not None
                and now - self.last_delivery_at < self.delivery_retry_seconds - 1e-9
            ):
                return False
        should_fire = True
        if should_fire: self.last_fire_at = now
        self.was_visible = True
        return should_fire

    def record_delivery(self, delivered: bool, now: float | None = None) -> None:
        now = self.last_fire_at if now is None and self.last_fire_at is not None else now
        now = time.monotonic() if now is None else now
        self.last_delivery_at = now
        self.last_fire_at = now
        self.delivery_attempts += 1
        self.delivery_pending = not delivered

    def reset(self) -> None:
        self.was_visible = False
        self.last_fire_at = None
        self.last_delivery_at = None
        self.delivery_attempts = 0
        self.delivery_pending = False

class IdleTracker:
    def __init__(self, required_seconds: float) -> None:
        self.required_seconds = required_seconds
        self.idle_since: float | None = None
        self.ready = False

    def observe(self, is_idle: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not is_idle:
            self.idle_since = None
            self.ready = False
            return False

        if self.idle_since is None:
            self.idle_since = now

        self.ready = now - self.idle_since >= self.required_seconds - 1e-9
        return self.ready

    def consume_ready(self) -> bool:
        if not self.ready:
            return False
        self.ready = False
        self.idle_since = None
        return True

    def reset(self) -> None:
        self.idle_since = None
        self.ready = False


def pick_recovery_text(viewport_text: str) -> str:
    """Return the 'continue' command that matches the terminal's UI language.

    An explicit CODEX_AUTO_CONFIRM_RECOVERY_TEXT always wins.  Otherwise a single
    CJK glyph anywhere in the visible viewport is treated as evidence that the
    Codex UI is localized to Chinese.
    """
    if CONFIGURED_RECOVERY_TEXT:
        return CONFIGURED_RECOVERY_TEXT
    for ch in viewport_text or "":
        if "一" <= ch <= "鿿":
            return RECOVERY_TEXT_ZH
    return RECOVERY_TEXT_EN


def _auth_unavailable_pool_error(text: str) -> bool:
    """Identify an account-pool 503 that should be retried until Working."""
    lines = _recovery_output_lines(text)
    status_503_indexes = [
        index
        for index, raw_line in enumerate(lines)
        if re.search(r"(?<!\d)503(?!\d)", normalize_terminal_text(raw_line))
        and _recovery_line_has_context(normalize_terminal_text(raw_line))
    ]
    if not status_503_indexes:
        return False

    error_start = status_503_indexes[-1]
    error_end = len(lines)
    for index in range(error_start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith(TERMINAL_PROMPT_MARKERS) or any(
            stripped.startswith(glyph) for glyph in RECOVERY_ERROR_GLYPHS
        ):
            error_end = index
            break
    error_detail = normalize_terminal_text("\n".join(lines[error_start:error_end]))
    return "auth_unavailable" in error_detail or "账号池没有可用账号" in error_detail


class ErrorRecoveryTracker:
    def __init__(
        self,
        required_retry_attempts: int = 5,
        retry_seconds: float | None = RECOVERY_RETRY_SECONDS,
    ) -> None:
        self.was_error = False
        self.latched_signature: str | None = None
        self.pending_signature: str | None = None
        self.required_retry_attempts = required_retry_attempts
        self.retry_seconds = retry_seconds
        self.last_sent_at: float | None = None
        self.working_seen = False
        self.delivery_retry_seconds = RECOVERY_DELIVERY_RETRY_SECONDS
        self.semantic_retry_seconds = RECOVERY_SEMANTIC_RETRY_SECONDS
        self.auth_unavailable_retry_seconds = RECOVERY_AUTH_UNAVAILABLE_RETRY_SECONDS
        self.confirmation_timeout_seconds = RECOVERY_CONFIRMATION_TIMEOUT_SECONDS
        self.max_delivery_attempts = RECOVERY_MAX_ATTEMPTS
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.retry_successful_delivery = False
        self.last_delivery_at: float | None = None
        self.cancellation_seen = False
        self.reconnecting_seen = False
        self.missing_snapshot_scans = 0

    def observe(self, is_error: bool | None) -> bool:
        if is_error is None:
            return False
        return self.observe_error("error" if is_error else None)

    def observe_no_error(self) -> bool:
        """Keep the episode latched until a normal status confirms recovery."""
        if self.cancellation_seen:
            return False
        if not self.working_seen:
            return False
        self.reset()
        return False

    def observe_error(
        self,
        signature: str | None,
        retry_progress: tuple[int, int] | None = None,
        status_active: bool = False,
        suppressed_signature: str | None = None,
        working_active: bool = False,
        cancellation_active: bool = False,
        now: float | None = None,
        retry_successful_delivery: bool = False,
    ) -> bool:
        if retry_progress is not None and not status_active:
            return False

        if status_active:
            if (self.retry_successful_delivery and retry_progress is not None
                    and not working_active and not cancellation_active):
                # Reconnecting cannot bypass the account-pool retry interval.
                return False
            self.delivery_pending = False
            self.semantic_retry_pending = False
            if retry_progress is not None and not working_active and not cancellation_active:
                # Reconnecting is a temporary transport state.  Pause sends
                # while it is visible, then treat the same final error as a
                # fresh edge once reconnecting disappears.
                if (
                    self.latched_signature is not None
                    or self.working_seen
                    or self.pending_signature is not None
                ):
                    self.reconnecting_seen = True
            if cancellation_active:
                # Conversation interrupted is an explicit user stop.  Keep a
                # barrier even when no send happened yet; otherwise the stale
                # error line would re-arm as soon as the status disappears.
                self.cancellation_seen = True
                self.working_seen = False
                self.reconnecting_seen = False
                if self.latched_signature is None:
                    self.pending_signature = suppressed_signature
                return False
            if working_active:
                # A fresh Working/Compacting status is the user's explicit
                # resume point after ESC, even when no previous error was
                # latched in this HWND.
                self.cancellation_seen = False
                if (
                    suppressed_signature is None
                    and (
                        self.latched_signature == "model-capacity"
                        or self.retry_successful_delivery
                        or self.pending_signature is not None
                    )
                ):
                    # A clean live status proves the capacity episode ended.
                    # A later identical error is a new occurrence, even if no
                    # intervening Ready snapshot was captured.
                    self.reset()
                    return False
            if working_active:
                # A live Working/Compacting row is a status barrier even when
                # the same viewport still contains an older capacity line.
                # UIA can briefly drop the status row on the next scan; keep
                # that barrier so the stale error cannot create a new send.
                self.working_seen = True
                self.reconnecting_seen = False
                if self.latched_signature is None and suppressed_signature is not None:
                    self.pending_signature = suppressed_signature
            elif suppressed_signature is None:
                self.reset()
            elif self.latched_signature is None:
                self.pending_signature = suppressed_signature
            return False

        if signature is None:
            self.reset()
            return False
        if self.cancellation_seen:
            # Do not turn an explicit user stop into a new automatic
            # continuation merely because the stale error line remains after
            # the interruption marker scrolls away.  observe_no_error() or a
            # fresh terminal lifecycle clears this barrier.
            return False
        if self.reconnecting_seen:
            self.reconnecting_seen = False
            self.working_seen = False
            self.latched_signature = None
            self.pending_signature = None
            self.delivery_attempts = 0
            self.delivery_pending = False
            self.semantic_retry_pending = False
            self.last_delivery_at = None
        if self.working_seen:
            # Working confirms the previously latched occurrence. Keep
            # suppressing that same stale line, but allow a genuinely new
            # signature to start a fresh recovery edge in the same terminal
            # window.  A stale copy of the same line never reactivates after
            # Working; an authoritative clear is required first.
            if signature == self.latched_signature or (
                self.latched_signature is None
                and signature == self.pending_signature
            ):
                return False
            self.working_seen = False
            self.latched_signature = None
            self.pending_signature = None
            self.delivery_attempts = 0
            self.delivery_pending = False
            self.semantic_retry_pending = False
            self.last_delivery_at = None
        if self.latched_signature == signature:
            self.retry_successful_delivery |= retry_successful_delivery
            if self.delivery_pending:
                if self.delivery_attempts >= self.max_delivery_attempts:
                    # A failed post is retried only a bounded number of
                    # times.  Keeping the latch without more sends prevents
                    # a broken input target from flooding the terminal.
                    return False
                retry_seconds = self.delivery_retry_seconds
            elif self.semantic_retry_pending and self.retry_successful_delivery:
                retry_seconds = self.auth_unavailable_retry_seconds
            elif self.semantic_retry_pending and signature == "model-capacity":
                retry_seconds = self.semantic_retry_seconds
            else:
                return False
            now = time.monotonic() if now is None else now
            if (
                self.last_delivery_at is None
                or now - self.last_delivery_at < retry_seconds - 1e-9
            ):
                return False
            # Keep the signature latched so a user pressing Escape cannot
            # create a new edge, but keep the current delivery mode eligible
            # for another timed send until an authoritative status clears it.
            self.last_sent_at = now
            return True

        if self.latched_signature is not None:
            # A changed error line is still part of the same visible failure
            # episode until Working/Compacting proves that the task resumed.
            # Do not turn appended or reformatted server text into a second
            # automatic Continue message.
            return False

        self.retry_successful_delivery = retry_successful_delivery
        self.latched_signature = signature
        self.pending_signature = None
        self.was_error = True
        self.last_sent_at = time.monotonic() if now is None else now
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.last_delivery_at = None
        self.cancellation_seen = False
        self.reconnecting_seen = False
        self.missing_snapshot_scans = 0
        return True

    def record_delivery(self, delivered: bool, now: float | None = None) -> None:
        now = self.last_sent_at if now is None and self.last_sent_at is not None else now
        now = time.monotonic() if now is None else now
        if delivered and (self.latched_signature == "model-capacity" or self.retry_successful_delivery):
            # The delivery budget counts consecutive failed posts. Successful
            # but unacknowledged capacity activations use the paced interval.
            self.delivery_attempts = 0
        else:
            self.delivery_attempts += 1
        self.last_delivery_at = now
        self.last_sent_at = now
        self.delivery_pending = not delivered
        # Posting input is not proof that Codex resumed.  Only the two live
        # processing statuses stop capacity retries.  Every retry still needs
        # a fresh error snapshot and passes the draft/physical-input guards.
        self.semantic_retry_pending = delivered and (
            self.latched_signature == "model-capacity" or self.retry_successful_delivery
        )

    def reset(self) -> None:
        self.was_error = False
        self.latched_signature = None
        self.pending_signature = None
        self.last_sent_at = None
        self.working_seen = False
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.retry_successful_delivery = False
        self.last_delivery_at = None
        self.cancellation_seen = False
        self.reconnecting_seen = False
        self.missing_snapshot_scans = 0

class ActionRequiredTracker:
    def __init__(self, retry_seconds: float | None = RETRY_ENTER_SECONDS) -> None:
        self.retry_seconds = retry_seconds
        self.was_action_required = False
        self.last_fire_at: float | None = None

    def observe(self, title: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        is_action_required = action_required_title_matches(title)
        should_fire = False

        if is_action_required:
            should_fire = (
                not self.was_action_required
                or self.last_fire_at is None
                or (
                    self.retry_seconds is not None
                    and now - self.last_fire_at >= self.retry_seconds - 1e-9
                )
            )
            if should_fire:
                self.last_fire_at = now
        else:
            self.last_fire_at = None

        self.was_action_required = is_action_required
        return should_fire

    def reset(self) -> None:
        self.was_action_required = False
        self.last_fire_at = None


def _approval_request_key(text: str) -> str | None:
    """Identify request content, excluding earlier transcript and menu redraws."""
    lines = (text or "").splitlines()
    headings = [
        index for index, line in enumerate(lines)
        if any(normalize_terminal_text(line) == heading
               or normalize_terminal_text(line).startswith(heading + " ")
               for heading in APPROVAL_HEADINGS)
    ]
    if not headings:
        return None
    start = headings[-1]
    selected = [index for index in range(start + 1, len(lines))
                if re.match(r"^[›»>]\s*\d+[.)]\s+", normalize_terminal_text(lines[index]))]
    option = selected[-1] if selected else next((
        index for index in range(start + 1, len(lines))
        if re.match(r"^\d+[.)]\s+", normalize_terminal_text(lines[index]))
        and any(
            re.sub(r"^\d+[.)]\s+", "", normalize_terminal_text(lines[index])) == allowed
            or re.sub(r"^\d+[.)]\s+", "", normalize_terminal_text(lines[index])).startswith(allowed + " ")
            for allowed in APPROVAL_ONCE_OPTIONS
        )
    ), None)
    if option is None or not any(line.strip() for line in lines[start + 1:option]):
        # A readable menu may still have its command body clipped by UIA.
        return None
    heading = normalize_terminal_text(lines[start])
    if heading != "would you like to run the following command?":
        # Other overlays lack a verified stable request-body boundary. Keep
        # their existing episode latch rather than identify volatile ranges.
        return None
    command = next((index for index in range(start + 1, option)
                    if lines[index].lstrip().startswith("$ ")), None)
    if command is None:
        return None
    # Thread/Environment/Reason ranges can disappear independently. The
    # command itself identifies this request without those volatile rows.
    start = command
    body = [line.rstrip() for line in lines[start:option]]
    while body and not body[-1].strip():
        body.pop()
    padding = min(len(line) - len(line.lstrip()) for line in body if line.strip())
    return heading + "\n" + "\n".join(line[padding:] for line in body)


def _approval_prompt_cleared(text: str) -> bool:
    """Require a later processing status or an empty composer, not missing UIA."""
    lines = (text or "").splitlines()
    for index in range(len(lines) - 1, -1, -1):
        line = normalize_terminal_text(lines[index])
        if line.startswith(TERMINAL_PROMPT_MARKERS):
            content = re.sub(r"[\u2800-\u28ff]", "", line[1:]).strip()
            tail = lines[index + 1:]
            if content in ("", "ask codex to do anything") and (
                any(_terminal_footer_line(row) for row in tail)
                and _terminal_footer_tail(tail)
            ):
                return True
            break
    last_menu_row = -1
    for index, raw_line in enumerate(lines):
        line = normalize_terminal_text(raw_line)
        if (
            any(line == heading or line.startswith(heading + " ") for heading in APPROVAL_HEADINGS)
            or re.match(r"^(?:[›»>]\s*)?\d+[.)]\s+(?:yes|no)\b", line)
            or ACTION_REQUIRED_CONFIRMATION_FOOTER in line
        ):
            last_menu_row = index
    return _working_status_active("\n".join(lines[last_menu_row + 1:]))


class ApprovalPromptTracker:
    """Edge-trigger a semantic TUI approval prompt per terminal window."""

    def __init__(
        self,
        retry_seconds: float | None = RETRY_ENTER_SECONDS,
        *,
        delivery_retry_seconds: float = RECOVERY_DELIVERY_RETRY_SECONDS,
        max_delivery_attempts: int = RECOVERY_MAX_ATTEMPTS,
    ) -> None:
        self.retry_seconds = retry_seconds
        # retry_seconds is retained for constructor compatibility with old
        # callers, but a successful PostMessage is not retried on a timer.
        # Only a failed delivery may use the bounded delivery retry budget.
        self.delivery_retry_seconds = max(0.1, float(delivery_retry_seconds))
        self.max_delivery_attempts = max(1, int(max_delivery_attempts))
        self.visible = False
        self.last_fire_at: float | None = None
        self.last_delivery_at: float | None = None
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.request_key: str | None = None
        self.request_states: dict[str, tuple] = {}

    def observe(self, is_visible: bool | None, now: float | None = None,
                *, request_key: str | None = None) -> bool:
        if is_visible is None:
            return False
        now = time.monotonic() if now is None else now
        if not is_visible:
            self.reset()
            return False

        if request_key is not None and request_key != self.request_key:
            if self.visible and self.request_key is None:
                # First full body after an options-only read is the same menu.
                self.request_key = request_key
                self._remember_request()
            else:
                if request_key not in self.request_states and len(self.request_states) >= 128:
                    # Never evict delivered identities and reauthorize old text.
                    return False
                state = self.request_states.get(request_key, (False, None, None, 0, False))
                (self.visible, self.last_fire_at, self.last_delivery_at,
                 self.delivery_attempts, self.delivery_pending) = state
                self.request_key = request_key

        if self.visible:
            if not self.delivery_pending:
                # A delivered prompt remains latched until UIA reads it away.
                return False
            if self.delivery_attempts >= self.max_delivery_attempts:
                return False
            if (
                self.last_delivery_at is not None
                and now - self.last_delivery_at < self.delivery_retry_seconds - 1e-9
            ):
                return False
            should_fire = True
        else:
            should_fire = True

        if should_fire:
            self.last_fire_at = now
        self.visible = True
        return should_fire

    def record_delivery(self, delivered: bool, now: float | None = None) -> None:
        now = self.last_fire_at if now is None and self.last_fire_at is not None else now
        now = time.monotonic() if now is None else now
        self.last_delivery_at = now
        self.last_fire_at = now
        self.delivery_attempts += 1
        self.delivery_pending = not delivered
        self._remember_request()

    def _remember_request(self) -> None:
        if self.request_key is not None:
            self.request_states[self.request_key] = (
                self.visible, self.last_fire_at, self.last_delivery_at,
                self.delivery_attempts, self.delivery_pending,
            )

    def reset(self) -> None:
        self.visible = False
        self.last_fire_at = None
        self.last_delivery_at = None
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.request_key = None
        self.request_states.clear()


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def window_process_name(hwnd: int) -> str:
    try:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""
        kernel32.OpenProcess.restype = ctypes.c_void_p
        process_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
        if not process_handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            if not kernel32.QueryFullProcessImageNameW(process_handle, 0, buffer, ctypes.byref(length)):
                return ""
            return os.path.basename(buffer.value[:length.value]).casefold()
        finally:
            kernel32.CloseHandle(process_handle)
    except Exception:
        return ""


def is_codex_process_window(hwnd: int) -> bool:
    return window_process_name(hwnd).casefold() in CODEX_HOST_PROCESS_NAMES
def title_matches(title: str) -> bool:
    lowered = title.lower()
    if "codex_auto_confirm" in lowered:
        return False
    return TARGET_TITLE in lowered


def action_required_title_matches(title: str) -> bool:
    lowered = title.lower()
    if "codex_auto_confirm" in lowered:
        return False
    return ACTION_REQUIRED_TITLE in lowered


def find_window_by_title(predicate, *, window_guard=None):
    result_hwnd = None
    result_pid = None
    result_title = ""

    def enum_callback(hwnd, _):
        nonlocal result_hwnd, result_pid, result_title
        if not user32.IsWindowVisible(hwnd):
            return True

        title = window_title(hwnd)
        if title and predicate(title):
            if window_guard is not None and not window_guard(hwnd):
                return True
            result_hwnd = hwnd
            result_title = title
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result_pid = pid.value
            return False
        return True

    wnd_enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(wnd_enum_proc(enum_callback), 0)
    return result_pid, result_hwnd, result_title


def find_codex_process():
    pid, hwnd, _ = find_window_by_title(title_matches)
    return pid, hwnd, None


def find_action_required_window():
    _, hwnd, title = find_window_by_title(action_required_title_matches, window_guard=is_codex_process_window)
    return hwnd, title


def find_codex_desktop_window() -> int | None:
    _, hwnd, title = find_window_by_title(lambda value: normalize_visible_text(value) == 'codex')
    return hwnd if title else None



INPUT_WINDOW_CLASS_HINTS = ("inputsitewindowclass", "windows.ui.input.inputsite.windowclass")
PSEUDOCONSOLE_WINDOW_CLASS = "pseudoconsolewindow"
GW_OWNER = 4

def window_class(hwnd: int) -> str:
    length = 256
    buf = ctypes.create_unicode_buffer(length)
    user32.GetClassNameW(hwnd, buf, length)
    return buf.value


def find_input_target(hwnd: int | None) -> int | None:
    if not hwnd:
        return None

    # In Windows Terminal, the ConPTY input window is an owned top-level
    # PseudoConsoleWindow, not an EnumChildWindows descendant of the host.
    pseudoconsole_hwnd = None

    def enum_windows_callback(candidate_hwnd, _):
        nonlocal pseudoconsole_hwnd
        if window_class(candidate_hwnd).casefold() != PSEUDOCONSOLE_WINDOW_CLASS:
            return True
        owner_hwnd = user32.GetWindow(candidate_hwnd, GW_OWNER)
        if not owner_hwnd:
            owner_hwnd = user32.GetParent(candidate_hwnd)
        if int(owner_hwnd) == int(hwnd):
            pseudoconsole_hwnd = candidate_hwnd
            return False
        return True

    wnd_enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(wnd_enum_proc(enum_windows_callback), 0)
    if pseudoconsole_hwnd:
        return pseudoconsole_hwnd

    inputsite_hwnd = None

    def enum_child_callback(child_hwnd, _):
        nonlocal inputsite_hwnd
        lowered_class = window_class(child_hwnd).casefold()
        if inputsite_hwnd is None and any(hint in lowered_class for hint in INPUT_WINDOW_CLASS_HINTS):
            inputsite_hwnd = child_hwnd
        return True

    child_enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(hwnd, child_enum_proc(enum_child_callback), 0)
    return inputsite_hwnd or hwnd

def find_inputsite_target(hwnd: int | None) -> int | None:
    if not hwnd:
        return None

    result_hwnd = None
    def enum_callback(child_hwnd, _):
        nonlocal result_hwnd
        lowered_class = window_class(child_hwnd).casefold()
        if any(hint in lowered_class for hint in INPUT_WINDOW_CLASS_HINTS):
            result_hwnd = child_hwnd
            return False
        return True

    child_enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(hwnd, child_enum_proc(enum_callback), 0)
    return result_hwnd or hwnd


def recovery_window_is_alive(hwnd: int) -> bool:
    """Distinguish a closed HWND from a transiently missing UIA snapshot."""
    try:
        return bool(user32.IsWindow(hwnd))
    except Exception:
        # If the readback API is unavailable, preserve the latch.  Resetting
        # on uncertainty is what causes duplicate recovery messages.
        return True


def _post_messages_via_attached_target(
    hwnd: int | None,
    messages: tuple[tuple[int, int, int], ...],
) -> bool | None:
    """Post one sequence to one resolved target.

    None means no input was posted, so a legacy fallback is still safe.
    False means delivery was partial/uncertain and must never be replayed.
    """
    if not hwnd:
        return None
    attached = False
    target_thread = 0
    current_thread = 0
    posted = False
    pending_key_release = None
    try:
        target_hwnd = find_inputsite_target(hwnd)
        if not target_hwnd:
            return None
        target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        if not target_thread or not current_thread:
            return None

        # Ensure this worker owns a message queue before attaching to the
        # Windows Terminal input thread.  A transiently destroyed InputSite
        # should fail closed instead of killing the monitor thread.
        user32.PeekMessageW(None, None, 0, 0, PM_NOREMOVE)
        attached = current_thread != target_thread and bool(
            user32.AttachThreadInput(current_thread, target_thread, True)
        )
        if current_thread != target_thread and not attached:
            return None
        for message, wparam, lparam in messages:
            if not user32.PostMessageW(target_hwnd, message, wparam, lparam):
                return False if posted else None
            posted = True
            if message == WM_KEYDOWN:
                pending_key_release = next(
                    (row for row in messages if row[0] == WM_KEYUP and row[1] == wparam), None,
                )
            elif message == WM_KEYUP:
                pending_key_release = None
        return True
    except Exception:
        return False if posted else None
    finally:
        # A failed character/keyup must release an already posted key-down;
        # never replay its text or Enter to accomplish that cleanup.
        if pending_key_release is not None:
            try:
                user32.PostMessageW(target_hwnd, *pending_key_release)
            except Exception:
                pass
        if attached:
            try:
                user32.AttachThreadInput(current_thread, target_thread, False)
            except Exception:
                pass


def send_enter_via_attached_post(hwnd: int | None) -> bool | None:
    return _post_messages_via_attached_target(
        hwnd,
        (
            (WM_KEYDOWN, VK_RETURN, ENTER_KEY_LPARAM),
            (WM_CHAR, VK_RETURN, ENTER_KEY_LPARAM),
            (WM_KEYUP, VK_RETURN, ENTER_KEYUP_LPARAM),
        ),
    )


def send_text_via_attached_post(hwnd: int | None, text: str) -> bool:
    if not hwnd or not text:
        return False
    return bool(_post_messages_via_attached_target(
        hwnd,
        tuple((WM_CHAR, ord(character), 0) for character in text),
    ))


def send_continue(hwnd: int | None, text: str | None = None) -> bool:
    text = text if text is not None else CONFIGURED_RECOVERY_TEXT or AUTO_CONTINUE_MESSAGE
    if recovery_input_busy(hwnd):
        return False
    # Keep text and Enter on the same InputSite attachment. Resolving again
    # after typing can send Enter to a different tab/pane after a UI redraw.
    return bool(_post_messages_via_attached_target(
        hwnd,
        tuple((WM_CHAR, ord(character), 0) for character in text)
        + (
            (WM_KEYDOWN, VK_RETURN, ENTER_KEY_LPARAM),
            (WM_CHAR, VK_RETURN, ENTER_KEY_LPARAM),
            (WM_KEYUP, VK_RETURN, ENTER_KEYUP_LPARAM),
        ),
    ))


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))


def recovery_input_busy(hwnd: int | None) -> bool:
    """Recheck physical input at delivery time; never store the user's keys."""
    if not hwnd:
        return True
    try:
        if int(user32.GetForegroundWindow() or 0) != int(hwnd):
            return False
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return True
        elapsed_ms = (int(kernel32.GetTickCount()) - info.dwTime) & 0xFFFFFFFF
        return elapsed_ms < IDLE_SECONDS * 1000
    except Exception:
        return True


def process_codex_recovery_snapshots(
    snapshots: list[dict] | None,
    tracker: ErrorRecoveryTracker,
    sender=send_continue,
) -> tuple[bool, str | None, bool | None]:
    if snapshots is None:
        tracker.observe(None)
        return False, None, None

    if any(
        snapshot.get("input_ambiguous")
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ):
        # A parent HWND does not identify which pane would receive input.
        # Neither errors nor status from an ambiguous pane may change state.
        return False, None, None

    # The same viewport can retain a previous error above a current approval.
    # Only the approval path may act on that menu: recovery would otherwise
    # type Continue into it and post an extra Enter from this same snapshot.
    if any(
        eligible_codex_snapshot(snapshot)
        and codex_approval_prompt_visible(str(snapshot.get("text", "")))
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ):
        return False, None, None

    match: tuple[str, int, str] | None = None
    suppressed_signature: str | None = None
    status_active = False
    working_active = False
    cancellation_active = False
    retry_progress: tuple[int, int] | None = None
    for snapshot in snapshots:
        if not eligible_codex_snapshot(snapshot):
            continue
        text = str(snapshot.get("text", ""))
        raw_signature, snapshot_status_active, snapshot_working_active = _recovery_state(text)
        if snapshot_status_active:
            status_active = True
            working_active = working_active or snapshot_working_active
            retry_progress = retry_progress or _retry_progress(
                "\n".join(_current_viewport_lines(text))
            )
            cancellation_active = cancellation_active or _conversation_interrupted_active(text)
            suppressed_signature = suppressed_signature or raw_signature
            continue
        signature = raw_signature
        if signature is None:
            continue
        try:
            hwnd = int(snapshot.get("hwnd", 0))
        except (TypeError, ValueError):
            continue
        if hwnd > 0:
            match = (signature, hwnd, text)
            break

    if status_active:
        tracker.observe_error(
            None,
            status_active=True,
            suppressed_signature=suppressed_signature,
            working_active=working_active,
            cancellation_active=cancellation_active,
            retry_progress=retry_progress,
        )
        return False, None, None

    if any(
        _terminal_draft_visible(str(snapshot.get("text", "")))
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ):
        return False, None, None

    if match is None:
        tracker.observe_no_error()
        return False, None, None

    signature, hwnd, viewport_text = match
    if recovery_input_busy(hwnd):
        return False, signature, None
    if not tracker.observe_error(
        signature,
        retry_successful_delivery=(
            signature == "http-503" and _auth_unavailable_pool_error(viewport_text)
        ),
    ):
        return False, signature, None
    try:
        delivered = bool(sender(hwnd, pick_recovery_text(viewport_text))
                         if sender is send_continue else sender(hwnd))
    except Exception:
        delivered = False
    tracker.record_delivery(delivered)
    return True, signature, delivered


def process_codex_recovery_snapshots_multi(
    snapshots: list[dict] | None,
    trackers: dict[int, ErrorRecoveryTracker],
    sender=send_continue,
) -> list[tuple[int, str, bool]]:
    """Process each eligible terminal independently.

    A Working/cancelled status in one Codex window must not suppress a fresh
    recoverable error in another window.  The helper can also expose more than
    one TermControl for a HWND, so those texts are combined before one tracker
    observes the window.
    """
    if snapshots is None:
        return []
    if not snapshots:
        # The UIA helper can briefly return an empty list while Windows
        # Terminal is redrawing or replacing a TermControl.  That is an
        # unknown read, not authoritative evidence that every visible error
        # cleared.  Resetting here creates a fresh edge on the next scan and
        # can enqueue duplicate ``continue`` messages.
        for stale_hwnd in list(trackers):
            if not recovery_window_is_alive(stale_hwnd):
                trackers.pop(stale_hwnd, None)
        return []

    grouped: dict[int, list[dict]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("class") != "CASCADIA_HOSTING_WINDOW_CLASS":
            continue
        try:
            hwnd = int(snapshot.get("hwnd", 0))
        except (TypeError, ValueError):
            continue
        if hwnd <= 0:
            continue
        grouped.setdefault(hwnd, []).append(snapshot)

    # Eligibility is a window-level decision, not a per-TermControl decision.
    # A sibling UIA snapshot may contain only the live Working/status line and
    # therefore lack the Codex marker required to identify a window by itself.
    # Keep all snapshots for an HWND whenever at least one sibling establishes
    # that the host is Codex, so the status snapshot can suppress stale errors.
    eligible_grouped: dict[int, list[dict]] = {}
    for hwnd, window_snapshots in grouped.items():
        if any(eligible_codex_snapshot(snapshot) for snapshot in window_snapshots):
            eligible_grouped[hwnd] = window_snapshots
            continue
        # A redraw can split one visible error across sibling TermControls.
        # Evaluate the combined text before discarding the HWND; otherwise a
        # generic-title window whose two controls contain the two halves of
        # the capacity sentence is lost before the merge below.
        combined = dict(window_snapshots[0])
        combined["text"] = "\n".join(
            str(snapshot.get("text", "")) for snapshot in window_snapshots
        )
        if eligible_codex_snapshot(combined):
            eligible_grouped[hwnd] = window_snapshots
    grouped = eligible_grouped

    if not grouped:
        # Keep the same fail-closed rule for a well-formed scan that contains
        # no eligible terminal.  A later authoritative snapshot for a known
        # HWND will clear its tracker through ``observe_no_error``.
        for stale_hwnd in list(trackers):
            if not recovery_window_is_alive(stale_hwnd):
                trackers.pop(stale_hwnd, None)
        return []

    for stale_hwnd in set(trackers).difference(grouped):
        if not recovery_window_is_alive(stale_hwnd):
            trackers.pop(stale_hwnd, None)
        # Missing UIA evidence is not a completed recovery or a cleared ESC
        # stop. Keep both latches while the HWND is alive, even after a long
        # redraw; a missing-scan timeout must never manufacture a new edge.

    events: list[tuple[int, str, bool]] = []
    for hwnd, window_snapshots in grouped.items():
        if any(snapshot.get("input_ambiguous") for snapshot in window_snapshots):
            continue
        if any(
            codex_approval_prompt_visible(str(snapshot.get("text", "")))
            for snapshot in window_snapshots
        ):
            # Preserve the recovery episode while the approval path owns the
            # current menu. Check siblings before merging their viewports.
            continue
        if len(window_snapshots) == 1:
            candidate = window_snapshots[0]
        else:
            candidate = dict(window_snapshots[0])
            candidate["text"] = "\n".join(
                str(snapshot.get("text", "")) for snapshot in window_snapshots
            )
        tracker = trackers.setdefault(hwnd, ErrorRecoveryTracker())
        tracker.missing_snapshot_scans = 0

        # A single Windows Terminal HWND can expose multiple TermControl
        # snapshots (for example during a pane/tab redraw).  Do not decide
        # whether the window is Working only after concatenating their text:
        # a longer stale viewport can push the live Working line outside the
        # 24-line current-view window.  Each snapshot is an independent
        # authoritative read for this HWND, so any active status must freeze
        # the tracker before the merged error text is considered.
        snapshot_states = [
            _recovery_state(str(snapshot.get("text", "")))
            for snapshot in window_snapshots
        ]
        cancellation_active = any(
            _conversation_interrupted_active(str(snapshot.get("text", "")))
            for snapshot in window_snapshots
        )
        status_active = any(state[1] for state in snapshot_states)
        if status_active:
            retry_progress = next(
                (
                    progress
                    for snapshot in window_snapshots
                    for progress in (
                        _retry_progress(
                            "\n".join(
                                _current_viewport_lines(str(snapshot.get("text", "")))
                            )
                        ),
                    )
                    if progress is not None
                ),
                None,
            )
            suppressed_signature = next(
                (state[0] for state in snapshot_states if state[0] is not None),
                None,
            )
            working_active = any(state[2] for state in snapshot_states)
            tracker.observe_error(
                None,
                status_active=True,
                suppressed_signature=suppressed_signature,
                working_active=working_active,
                cancellation_active=cancellation_active,
                retry_progress=retry_progress,
            )
            continue

        # Check every sibling before merging: another pane's long transcript
        # must not hide the user's current draft.  Deferral preserves the edge
        # and the delivery budget so clearing the draft can resume recovery.
        if any(
            _terminal_draft_visible(str(snapshot.get("text", "")))
            for snapshot in window_snapshots
        ):
            continue

        triggered, signature, delivered = process_codex_recovery_snapshots(
            [candidate], tracker, sender
        )
        if triggered and signature is not None:
            events.append((hwnd, signature, bool(delivered)))
    return events


def process_codex_approval_snapshots_multi(
    snapshots: list[dict] | None,
    trackers: dict[int, ApprovalPromptTracker],
    sender=None,
) -> list[tuple[int, bool]]:
    """Confirm new-style inline TUI approvals, independently per HWND."""
    if sender is None:
        sender = send_enter
    if snapshots is None:
        return []
    grouped: dict[int, list[dict]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or snapshot.get("class") != "CASCADIA_HOSTING_WINDOW_CLASS":
            continue
        try:
            hwnd = int(snapshot.get("hwnd", 0))
        except (TypeError, ValueError):
            continue
        if hwnd > 0:
            grouped.setdefault(hwnd, []).append(snapshot)

    for stale_hwnd in set(trackers).difference(grouped):
        if not recovery_window_is_alive(stale_hwnd):
            trackers.pop(stale_hwnd).observe(False)
        # An absent UIA viewport is an unknown read, not proof that the menu
        # closed. Preserve the retry interval until an actual clear is read.

    events: list[tuple[int, bool]] = []
    for hwnd, window_snapshots in grouped.items():
        if any(snapshot.get("input_ambiguous") for snapshot in window_snapshots):
            continue
        tracker = trackers.setdefault(hwnd, ApprovalPromptTracker())
        if any(_terminal_draft_visible(str(item.get("text", ""))) for item in window_snapshots):
            continue
        menus = [
            item for item in window_snapshots
            if (
            eligible_codex_snapshot(item)
            and (
                codex_approval_prompt_visible(str(item.get("text", "")))
                or (
                    action_required_title_matches(str(item.get("title", "")))
                    and action_required_options_visible(str(item.get("text", "")))
                )
            )
            )
        ]
        visible = bool(menus) and not any(
            _recovery_status_active(str(item.get("text", "")))
            and not codex_approval_prompt_visible(str(item.get("text", "")))
            for item in window_snapshots
        )
        if visible and recovery_input_busy(hwnd):
            continue
        keys = {_approval_request_key(str(item.get("text", ""))) for item in menus}
        keys.discard(None)
        if len(keys) > 1:
            continue
        observed = True if visible else (
            False if not menus and any(
                _approval_prompt_cleared(str(item.get("text", "")))
                for item in window_snapshots
            ) else None
        )
        if not tracker.observe(observed, request_key=next(iter(keys), None)):
            continue
        try:
            delivered = bool(sender(hwnd))
        except Exception:
            delivered = False
        tracker.record_delivery(delivered)
        events.append((hwnd, delivered))
    return events


def send_enter(hwnd: int | None) -> bool:
    if not hwnd or recovery_input_busy(hwnd):
        return False

    attached_result = send_enter_via_attached_post(hwnd)
    if attached_result is not None:
        return bool(attached_result)

    # Keep a message fallback for classic Win32 consoles and older hosts.
    try:
        target_hwnd = find_input_target(hwnd)
        if not target_hwnd:
            return False
        messages = (
            (WM_KEYDOWN, ENTER_KEY_LPARAM),
            (WM_CHAR, ENTER_KEY_LPARAM),
            (WM_KEYUP, ENTER_KEYUP_LPARAM),
        )
        return all(
            user32.PostMessageW(target_hwnd, message, VK_RETURN, lparam)
            for message, lparam in messages
        )
    except Exception:
        return False

def auto_enter_loop() -> None:
    approval_trackers: dict[int, ApprovalPromptTracker] = {}
    desktop_tracker = DesktopApprovalTracker()
    recovery_trackers: dict[int, ErrorRecoveryTracker] = {}
    terminal_reader = CodexTerminalReader()
    next_recovery_scan = 0.0
    next_desktop_probe = 0.0
    desktop_visible = False
    last_state = None
    enter_attempts = 0

    try:
        while running:
            if not auto_confirm:
                desktop_tracker.observe(False)
                for recovery_tracker in recovery_trackers.values():
                    recovery_tracker.reset()
                recovery_trackers.clear()
                for approval_tracker in approval_trackers.values():
                    approval_tracker.observe(False)
                approval_trackers.clear()
                desktop_visible = False
                try:
                    terminal_reader.poll()
                except Exception as exc:
                    print(
                        f"  Monitor iteration error (recovery reader off-state): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    try:
                        terminal_reader.restart()
                    except Exception:
                        pass
                enter_attempts = 0
                time.sleep(LOOP_SECONDS)
                continue

            now = time.monotonic()
            if now >= next_recovery_scan:
                try:
                    terminal_reader.request_scan()
                except Exception as exc:
                    print(
                        f"  Monitor iteration error (recovery reader request): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    try:
                        terminal_reader.restart()
                    except Exception:
                        pass
                next_recovery_scan = now + RECOVERY_POLL_SECONDS
            try:
                terminal_snapshots = terminal_reader.poll()
            except Exception as exc:
                print(
                    f"  Monitor iteration error (recovery reader poll): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                try:
                    terminal_reader.restart()
                except Exception:
                    pass
                terminal_snapshots = None
            try:
                recovery_events = process_codex_recovery_snapshots_multi(
                    terminal_snapshots,
                    recovery_trackers,
                )
            except Exception as exc:
                print(
                    f"  Monitor iteration error (recovery state): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                recovery_events = []
            for recovery_hwnd, recovery_signature, recovery_delivered in recovery_events:
                enter_attempts += 1
                result = "ok" if recovery_delivered else "failed"
                print(
                    f"  Recoverable error {recovery_signature} detected -> "
                    f"Continue attempt {enter_attempts} hwnd={recovery_hwnd} "
                    f"[send_continue={result}]"
                )
                last_state = "sent" if recovery_delivered else "send_failed"
                time.sleep(
                    min(
                        LOOP_SECONDS,
                        RECOVERY_SEMANTIC_RETRY_SECONDS
                        if recovery_delivered
                        else RECOVERY_DELIVERY_RETRY_SECONDS,
                    )
                )

            try:
                approval_events = process_codex_approval_snapshots_multi(
                    terminal_snapshots,
                    approval_trackers,
                )
            except Exception as exc:
                print(
                    f"  Monitor iteration error (approval state): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                approval_events = []
            for approval_hwnd, approval_delivered in approval_events:
                enter_attempts += 1
                result = "ok" if approval_delivered else "failed"
                print(
                    f"  Inline approval detected -> Enter attempt {enter_attempts} "
                    f"hwnd={approval_hwnd} [send_enter={result}]",
                    flush=True,
                )
                last_state = "sent" if approval_delivered else "send_failed"
                time.sleep(AFTER_ENTER_SLEEP_SECONDS)

            try:
                hwnd, _title = find_action_required_window()
            except Exception as exc:
                print(
                    f"  Monitor iteration error (title detector): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                hwnd, _title = None, ""
            # A title may remain stale after a dialog disappears. All terminal
            # approval input belongs to the semantic snapshot path above and
            # its per-HWND tracker; titles are informational only. A separate
            # title sender could submit drafts or duplicate the same approval.

            desktop_probe_fresh = False
            if time.monotonic() >= next_desktop_probe:
                try:
                    desktop_visible = read_desktop_allow_once()
                except Exception as exc:
                    print(
                        f"  Monitor iteration error (desktop detector): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    desktop_visible = False
                next_desktop_probe = time.monotonic() + DESKTOP_POLL_SECONDS
                desktop_probe_fresh = True
            try:
                desktop_hwnd = find_codex_desktop_window() if desktop_probe_fresh and desktop_visible else None
            except Exception as exc:
                print(
                    f"  Monitor iteration error (desktop target): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                desktop_hwnd = None
            if desktop_probe_fresh and desktop_tracker.observe(desktop_visible) and desktop_hwnd:
                enter_attempts += 1
                delivered = send_enter(desktop_hwnd)
                desktop_tracker.record_delivery(delivered)
                result = "ok" if delivered else "failed"
                print(f'  Desktop allow-once detected -> Enter attempt {enter_attempts} [send_enter={result}]')
                last_state = 'sent' if delivered else 'send_failed'
                time.sleep(AFTER_ENTER_SLEEP_SECONDS)
            elif desktop_visible:
                last_state = 'holding'

            if not hwnd and not desktop_visible and not recovery_events and not approval_events:
                enter_attempts = 0
                if last_state != 'waiting':
                    print('  Waiting for Action Required, desktop allow-once, or recoverable error')
                    last_state = 'waiting'
                time.sleep(NOT_FOUND_SLEEP_SECONDS)
                continue

            time.sleep(LOOP_SECONDS)
    finally:
        terminal_reader.close()


def on_press(key):
    global auto_confirm, running
    try:
        from pynput.keyboard import Key

        if key == Key.f9:
            auto_confirm = not auto_confirm
            print(f"\n  Auto Confirm: {'ON' if auto_confirm else 'OFF'}")
        elif key == Key.f10:
            print("\n  Exit")
            running = False
            return False
    except Exception:
        pass
    return None


def _setup_log_tee() -> str:
    r"""Mirror stdout/stderr to %APPDATA%\codex-auto-confirm\watchdog.log.

    Returns the log file path.  In windowed (PyInstaller) mode the original
    stdout is None; the tee then only writes to the file.  Skipped under pytest
    so test capture keeps working.
    """
    if "_pytest" in sys.modules or "pytest" in sys.modules:
        return ""
    import datetime
    log_dir = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "codex-auto-confirm",
    )
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "watchdog.log")

    class _Tee:
        def __init__(self, *streams):
            self._streams = [st for st in streams if st is not None]
        def write(self, data):
            for st in self._streams:
                try:
                    st.write(data)
                except Exception:
                    pass
        def flush(self):
            for st in self._streams:
                try:
                    st.flush()
                except Exception:
                    pass
        def __getattr__(self, name):
            return getattr(self._streams[0], name) if self._streams else None

    try:
        f = open(log_path, "a", encoding="utf-8", errors="replace")
        f.write("\n===== session start %s =====\n" % datetime.datetime.now().isoformat(timespec="seconds"))
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
    except Exception:
        pass
    return log_path


def main() -> int:
    global running
    import argparse
    parser = argparse.ArgumentParser(description="Codex CLI auto-confirm watchdog")
    parser.add_argument(
        "--version",
        action="version",
        version=f"codex-auto-confirm {__version__}",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run as a background system-tray app (no console window). "
             "Default when launched as a PyInstaller exe.",
    )
    args, _unknown = parser.parse_known_args()

    _setup_log_tee()
    tray_mode = args.tray or bool(getattr(sys, "frozen", False))

    if not acquire_single_instance():
        if not tray_mode:
            print("  Another Codex auto-confirm monitor is already running")
        return 0

    if not tray_mode:
        print("=" * 55)
        print("  Codex CLI Auto Confirm")
        _, hwnd, _ = find_codex_process()
        print(f"  Codex: {'found' if hwnd else 'not found'}")
        print(f"  Trigger title: {ACTION_REQUIRED_TITLE}")
        print(f"  Auto Confirm: {'ON' if auto_confirm else 'OFF'}")
        print("  F9=toggle  F10=exit")
        print("=" * 55)

    worker = None
    listener = None
    try:
        try:
            from pynput.keyboard import Listener
        except ImportError:
            print("  Missing dependency: pynput. Run this with the same Python environment used by the shortcut.")
            return 1

        worker = threading.Thread(target=auto_enter_loop, daemon=True)
        worker.start()

        if tray_mode:
            # Global hotkeys still work, but on a background thread.
            listener = Listener(on_press=on_press)
            listener.start()
            import autostart
            from tray import run_tray

            def _toggle():
                global auto_confirm
                auto_confirm = not auto_confirm

            def _shutdown():
                global running
                running = False

            run_tray(
                is_on=lambda: auto_confirm,
                toggle=_toggle,
                is_autostart=autostart.is_enabled,
                set_autostart=lambda on: autostart.enable() if on else autostart.disable(),
                shutdown=_shutdown,
                keep_running=lambda: running and worker.is_alive() and listener.is_alive(),
            )
            if running:
                print("  Monitor worker or keyboard listener stopped unexpectedly", flush=True)
                return 1
            return 0

        with Listener(on_press=on_press) as listener:
            while running:
                listener.join(timeout=LOOP_SECONDS)
                if not running:
                    break
                if not worker.is_alive():
                    print("  Monitor worker stopped unexpectedly", flush=True)
                    return 1
                if not listener.is_alive():
                    print("  Keyboard listener stopped unexpectedly", flush=True)
                    return 1
        return 0
    finally:
        running = False
        if listener is not None:
            listener.stop()
        if worker is not None and worker.is_alive():
            worker.join(timeout=RECOVERY_SCAN_TIMEOUT_SECONDS + 1.0)
        release_single_instance()


if __name__ == "__main__":
    raise SystemExit(main())
