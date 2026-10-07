#!/usr/bin/env python3
"""
Codex CLI auto confirm.

F9 toggles auto-confirm. F10 exits.
The detector watches for the Codex terminal title to change to "Action Required"
and retries a real Enter keypress while the prompt remains visible.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import urllib.request
import threading
import time
from ctypes import wintypes

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Window-title fragment used to locate the Codex terminal host on legacy builds
# that still rename the title bar to "Action Required". Override with the
# CODEX_AUTO_CONFIRM_TITLE environment variable if your terminal title does not
# contain "codex". The modern UIA scanner path does not depend on this value.
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
    0.25,
    float(os.environ.get("CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS", "0.8")),
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
# A visible recovery error remains eligible for another send until the current
# viewport proves Working/reconnecting/cancellation/clear.  The legacy
# RECOVERY_MAX_ATTEMPTS setting is retained for environment compatibility but
# does not cap status-gated recovery anymore.
RECOVERY_RETRY_SECONDS = None
# Locate the bundled UIA helper.  When frozen by PyInstaller, resources are
# unpacked into sys._MEIPASS; otherwise sit next to this .py file.
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
CODEX_TERMINAL_MARKERS = ("openai codex", "ask codex to do anything", "codex cli")
CODEX_TITLE_MARKER = re.compile(r"(?<![a-z0-9])codex(?![a-z0-9])")

# Recoverable-error "continue" message.  Older Codex builds show the prompt in
# Chinese and expect "继续执行"; English builds expect "continue".  The text is
# picked per-terminal from the visible viewport (any CJK glyph → Chinese), and
# can be pinned explicitly with CODEX_AUTO_CONFIRM_RECOVERY_TEXT.
RECOVERY_TEXT_ZH = "继续执行"
RECOVERY_TEXT_EN = "continue"
CONFIGURED_RECOVERY_TEXT = os.environ.get("CODEX_AUTO_CONFIRM_RECOVERY_TEXT") or None


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
    return (
        any(marker in haystack for marker in CODEX_TERMINAL_MARKERS)
        or bool(CODEX_TITLE_MARKER.search(normalize_terminal_text(title)))
        # New approval overlays can appear in a newly titled terminal before
        # the title/body contains a Codex marker.  The semantic menu itself is
        # a stronger signal than a generic terminal title.
        or codex_approval_prompt_visible(text)
    )


def codex_approval_prompt_visible(text: str) -> bool:
    """Return whether the current visible TUI contains a one-shot approval.

    The heading and option are required together because UIA's visible range
    can include stale transcript lines while an unrelated prompt is active.
    """
    lines = [normalize_visible_text(line) for line in (text or "").splitlines()]
    # Transcript bullets ("- Would you like...", "• Yes, proceed") are not
    # active controls.  Active approval overlays render these as standalone
    # lines without a transcript marker.
    lines = [line for line in lines if line and not line.startswith((">", "›", "-", "•", "│"))]
    lines = [re.sub(r"^\d+[.)]\s+", "", line) for line in lines]
    has_heading = any(
        any(line == heading or line.startswith(heading + " ") for heading in APPROVAL_HEADINGS)
        for line in lines
    )
    has_once_option = any(
        any(line == option or line.startswith(option + " ") for option in APPROVAL_ONCE_OPTIONS)
        for line in lines
    )
    return has_heading and has_once_option


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
        self._start_process()

    def _start_process(self) -> bool:
        if getattr(self, "_closed", False):
            return False
        now = time.monotonic()
        if now < getattr(self, "_next_restart_at", 0.0):
            return False
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
        except Exception:
            self._process = None
            self._next_restart_at = now + RECOVERY_HELPER_RESTART_BACKOFF_SECONDS
            return False
        self._process = process
        self._scan_in_flight = False
        self._scan_sent_at = None
        self._next_restart_at = 0.0
        self._reader_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._reader_thread.start()
        return True

    def _stop_process(self, process) -> None:
        if process is None:
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
        try:
            process.terminate()
        except (OSError, AttributeError):
            pass
        try:
            process.wait(timeout=0.5)
        except (subprocess.TimeoutExpired, OSError, AttributeError):
            pass

    def restart(self, *, force: bool = False) -> bool:
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
        if not force and time.monotonic() < getattr(self, "_next_restart_at", 0.0):
            return False
        old_process = getattr(self, "_process", None)
        self._process = None
        self._scan_in_flight = False
        self._scan_sent_at = None
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                break
        self._stop_process(old_process)
        self._next_restart_at = 0.0
        return self._start_process()

    def _drain_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                while True:
                    try:
                        self._responses.put_nowait(line)
                        break
                    except queue.Full:
                        try:
                            self._responses.get_nowait()
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
        if process is None or process.poll() is not None or process.stdin is None:
            # Drain a response that was written just before the helper exited
            # before replacing the process; otherwise the only evidence of a
            # short-lived visible error could be discarded.
            if not self._responses.empty():
                return False
            if not self.restart():
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
            self.restart(force=True)
            process = self._process
            if process is None or process.stdin is None:
                return False
        try:
            process.stdin.write("scan\n")
            process.stdin.flush()
            self._scan_in_flight = True
            self._scan_sent_at = now
            return True
        except (OSError, ValueError):
            self._scan_in_flight = False
            self._scan_sent_at = None
            self.restart(force=True)
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
            self.restart(force=True)
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


def _current_viewport_lines(text: str) -> list[str]:
    """Prefer the live status area over historical transcript lines."""
    lines = (text or "").splitlines()
    if not lines:
        return []
    marker_indexes = [
        index
        for index, raw_line in enumerate(lines)
        if "ask codex to do anything" in normalize_terminal_text(raw_line)
    ]
    if marker_indexes:
        marker = marker_indexes[-1]
        return lines[max(0, marker - 24) : marker + 1]
    return lines[-40:]


def _retry_progress(text: str) -> tuple[int, int] | None:
    match = re.search(r"reconnecting\s*\.\.\.\s*(\d+)\s*/\s*(\d+)", text.casefold())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _working_status_line(line: str) -> bool:
    """Return True for the visible Codex Working duration status line.

    Codex has used both English and localized duration units.  The status is
    authoritative even when an older error line remains in the same viewport.
    """
    lowered = normalize_terminal_text(line)
    if lowered.startswith(("›", ">")):
        return False
    return bool(
        re.search(
            r"^(?:[◦•]\s*)?(?:working|compacting\s+context)\s*\(\s*\d+"
            r"[^)]*\besc\s+to\s+interrupt\s*\)",
            lowered,
        )
    )


def _recovery_status_active(text: str) -> bool:
    lines = _current_viewport_lines(text)
    current_text = "\n".join(lines)
    if _retry_progress(current_text) is not None:
        return True
    if any(_working_status_line(raw_line) for raw_line in lines):
        return True
    for raw_line in lines:
        lowered = normalize_terminal_text(raw_line)
        if lowered.startswith(("›", ">")):
            continue
        if any(marker in lowered for marker in RECOVERY_TERMINAL_STATUS_MARKERS):
            return True
    return False


def _working_status_active(text: str) -> bool:
    return any(_working_status_line(raw_line) for raw_line in _current_viewport_lines(text))


def _unmasked_recovery_error_signature(text: str) -> str | None:
    latest_signature: str | None = None
    stream_disconnect_pending = False
    for raw_line in _current_viewport_lines(text):
        line = normalize_terminal_text(raw_line)
        if not line or line.startswith(("›", ">")):
            continue
        stripped_line = line.lstrip()
        starts_with_error_glyph = any(
            stripped_line.startswith(glyph) for glyph in RECOVERY_ERROR_GLYPHS
        )
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
        if "selected model is at capacity" in line and "please try a different model" in line:
            latest_signature = "model-capacity"
            continue
        if "429 too many requests" in line:
            latest_signature = "http-429"
            continue
        if _recovery_line_has_context(line):
            for status in RECOVERY_STATUS_CODES:
                if re.search(rf"(?<!\d){status}(?!\d)", line):
                    latest_signature = f"http-{status}"
                    break
    return latest_signature


def _recovery_state(text: str) -> tuple[str | None, bool, bool]:
    return (
        _unmasked_recovery_error_signature(text),
        _recovery_status_active(text),
        _working_status_active(text),
    )


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
    try:
        targets = discover_cdp_targets(port)
        if not targets:
            return False
        import websocket
        ws = websocket.create_connection(targets[0]["webSocketDebuggerUrl"], timeout=timeout_seconds, suppress_origin=True)
        expression = DESKTOP_READ_EXPRESSION
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break
        ws.close()
        elements = message.get("result", {}).get("result", {}).get("value", [])
        return desktop_allow_once_visible(elements if isinstance(elements, list) else [])
    except Exception:
        return False

class DesktopApprovalTracker:
    def __init__(self, retry_seconds: float | None = RETRY_ENTER_SECONDS) -> None:
        self.retry_seconds = retry_seconds; self.was_visible = False; self.last_fire_at = None
    def observe(self, is_visible: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not is_visible:
            self.was_visible = False; self.last_fire_at = None; return False
        should_fire = (not self.was_visible or self.last_fire_at is None or (self.retry_seconds is not None and now - self.last_fire_at >= self.retry_seconds - 1e-9))
        if should_fire: self.last_fire_at = now
        self.was_visible = True
        return should_fire

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
        self.confirmation_timeout_seconds = RECOVERY_CONFIRMATION_TIMEOUT_SECONDS
        self.max_delivery_attempts = RECOVERY_MAX_ATTEMPTS
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.last_delivery_at: float | None = None

    def observe(self, is_error: bool | None) -> bool:
        if is_error is None:
            return False
        return self.observe_error("error" if is_error else None)

    def observe_no_error(self) -> bool:
        """Clear only after recovery has been confirmed or no event was latched."""
        if self.latched_signature is not None and (
            self.delivery_pending or self.semantic_retry_pending
        ):
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
        now: float | None = None,
    ) -> bool:
        if retry_progress is not None:
            return False

        if status_active:
            self.delivery_pending = False
            self.semantic_retry_pending = False
            if working_active and self.latched_signature is not None:
                self.working_seen = True
            elif suppressed_signature is None and not working_active:
                self.reset()
            elif self.latched_signature is None:
                self.pending_signature = suppressed_signature
            return False

        if signature is None:
            self.reset()
            return False
        if self.working_seen:
            # Working confirms the previously latched occurrence. Keep
            # suppressing that same stale line, but allow a genuinely new
            # signature (for example model-capacity -> HTTP 503) to start a
            # fresh recovery edge in the same terminal window.
            if signature == self.latched_signature:
                return False
            self.working_seen = False
            self.latched_signature = None
            self.pending_signature = None
            self.delivery_attempts = 0
            self.delivery_pending = False
            self.semantic_retry_pending = False
            self.last_delivery_at = None
        if self.latched_signature == signature:
            if self.delivery_pending:
                retry_seconds = self.delivery_retry_seconds
            elif self.semantic_retry_pending:
                # PostMessage success only proves that Windows accepted the
                # input. Wait for the authoritative Working(duration) status
                # before considering another semantic attempt.
                retry_seconds = max(
                    self.semantic_retry_seconds,
                    self.confirmation_timeout_seconds,
                )
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

        self.latched_signature = signature
        self.pending_signature = None
        self.was_error = True
        self.last_sent_at = time.monotonic() if now is None else now
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.last_delivery_at = None
        return True

    def record_delivery(self, delivered: bool, now: float | None = None) -> None:
        now = self.last_sent_at if now is None and self.last_sent_at is not None else now
        now = time.monotonic() if now is None else now
        self.delivery_attempts += 1
        self.last_delivery_at = now
        self.last_sent_at = now
        self.delivery_pending = not delivered
        self.semantic_retry_pending = delivered

    def reset(self) -> None:
        self.was_error = False
        self.latched_signature = None
        self.pending_signature = None
        self.last_sent_at = None
        self.working_seen = False
        self.delivery_attempts = 0
        self.delivery_pending = False
        self.semantic_retry_pending = False
        self.last_delivery_at = None

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


class ApprovalPromptTracker:
    """Edge-trigger a semantic TUI approval prompt per terminal window."""

    def __init__(self, retry_seconds: float | None = RETRY_ENTER_SECONDS) -> None:
        self.retry_seconds = retry_seconds
        self.visible = False
        self.last_fire_at: float | None = None

    def observe(self, is_visible: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not is_visible:
            self.visible = False
            self.last_fire_at = None
            return False
        should_fire = (
            not self.visible
            or self.last_fire_at is None
            or (
                self.retry_seconds is not None
                and now - self.last_fire_at >= self.retry_seconds - 1e-9
            )
        )
        if should_fire:
            self.last_fire_at = now
        self.visible = True
        return should_fire


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


def _post_messages_via_attached_target(
    hwnd: int | None,
    messages: tuple[tuple[int, int, int], ...],
) -> bool:
    if not hwnd:
        return False
    attached = False
    target_thread = 0
    current_thread = 0
    try:
        target_hwnd = find_inputsite_target(hwnd)
        if not target_hwnd:
            return False
        target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        if not target_thread or not current_thread:
            return False

        # Ensure this worker owns a message queue before attaching to the
        # Windows Terminal input thread.  A transiently destroyed InputSite
        # should fail closed instead of killing the monitor thread.
        user32.PeekMessageW(None, None, 0, 0, PM_NOREMOVE)
        attached = current_thread != target_thread and bool(
            user32.AttachThreadInput(current_thread, target_thread, True)
        )
        if current_thread != target_thread and not attached:
            return False
        return all(
            user32.PostMessageW(target_hwnd, message, wparam, lparam)
            for message, wparam, lparam in messages
        )
    except Exception:
        return False
    finally:
        if attached:
            try:
                user32.AttachThreadInput(current_thread, target_thread, False)
            except Exception:
                pass


def send_enter_via_attached_post(hwnd: int | None) -> bool:
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
    return _post_messages_via_attached_target(
        hwnd,
        tuple((WM_CHAR, ord(character), 0) for character in text),
    )


def send_continue(hwnd: int | None, text: str | None = None) -> bool:
    if text is None:
        text = CONFIGURED_RECOVERY_TEXT or RECOVERY_TEXT_ZH
    if not send_text_via_attached_post(hwnd, text):
        return False
    return send_enter(hwnd)


def process_codex_recovery_snapshots(
    snapshots: list[dict] | None,
    tracker: ErrorRecoveryTracker,
    sender=send_continue,
) -> tuple[bool, str | None, bool | None]:
    if snapshots is None:
        tracker.observe(None)
        return False, None, None

    match: tuple[str, int] | None = None
    suppressed_signature: str | None = None
    status_active = False
    working_active = False
    for snapshot in snapshots:
        if not eligible_codex_snapshot(snapshot):
            continue
        text = str(snapshot.get("text", ""))
        raw_signature, snapshot_status_active, snapshot_working_active = _recovery_state(text)
        if snapshot_status_active:
            status_active = True
            working_active = working_active or snapshot_working_active
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
        )
        return False, None, None

    if match is None:
        tracker.observe_no_error()
        return False, None, None

    signature, hwnd, viewport_text = match
    if not tracker.observe_error(signature):
        return False, signature, None
    recovery_text = pick_recovery_text(viewport_text)
    try:
        try:
            delivered = bool(sender(hwnd, recovery_text))
        except TypeError:
            delivered = bool(sender(hwnd))
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
        for tracker in trackers.values():
            tracker.reset()
        return []

    grouped: dict[int, list[dict]] = {}
    for snapshot in snapshots:
        if not eligible_codex_snapshot(snapshot):
            continue
        try:
            hwnd = int(snapshot.get("hwnd", 0))
        except (TypeError, ValueError):
            continue
        if hwnd <= 0:
            continue
        grouped.setdefault(hwnd, []).append(snapshot)

    if not grouped:
        for tracker in trackers.values():
            tracker.reset()
        return []

    for stale_hwnd in set(trackers).difference(grouped):
        trackers.pop(stale_hwnd).reset()

    events: list[tuple[int, str, bool]] = []
    for hwnd, window_snapshots in grouped.items():
        if len(window_snapshots) == 1:
            candidate = window_snapshots[0]
        else:
            candidate = dict(window_snapshots[0])
            candidate["text"] = "\n".join(
                str(snapshot.get("text", "")) for snapshot in window_snapshots
            )
        tracker = trackers.setdefault(hwnd, ErrorRecoveryTracker())
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
    grouped: dict[int, bool] = {}
    for snapshot in snapshots:
        if not eligible_codex_snapshot(snapshot):
            continue
        try:
            hwnd = int(snapshot.get("hwnd", 0))
        except (TypeError, ValueError):
            continue
        if hwnd > 0:
            grouped[hwnd] = grouped.get(hwnd, False) or codex_approval_prompt_visible(
                str(snapshot.get("text", ""))
            )

    for stale_hwnd in set(trackers).difference(grouped):
        trackers.pop(stale_hwnd).observe(False)

    events: list[tuple[int, bool]] = []
    for hwnd, visible in grouped.items():
        tracker = trackers.setdefault(hwnd, ApprovalPromptTracker())
        if not tracker.observe(visible):
            continue
        try:
            delivered = bool(sender(hwnd))
        except Exception:
            delivered = False
        events.append((hwnd, delivered))
    return events


def send_enter(hwnd: int | None) -> bool:
    if not hwnd:
        return False

    if send_enter_via_attached_post(hwnd):
        return True

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
    tracker = ActionRequiredTracker()
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
                tracker.reset()
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
            approval_hwnds = {hwnd for hwnd, _delivered in approval_events}
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
                hwnd, title = find_action_required_window()
            except Exception as exc:
                print(
                    f"  Monitor iteration error (title detector): "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                hwnd, title = None, ""
            if hwnd and hwnd not in approval_hwnds and tracker.observe(title):
                enter_attempts += 1
                delivered = send_enter(hwnd)
                result = "ok" if delivered else "failed"
                print(f'  Action Required detected -> Enter attempt {enter_attempts} ({title}) [send_enter={result}]')
                last_state = 'sent' if delivered else 'send_failed'
                time.sleep(AFTER_ENTER_SLEEP_SECONDS)
            elif hwnd:
                tracker.observe(title)
            else:
                tracker.observe('')

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


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Codex CLI auto-confirm watchdog")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run as a background system-tray app (no console window). "
             "Default when launched as a PyInstaller exe.",
    )
    args, _unknown = parser.parse_known_args()

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

    try:
        try:
            from pynput.keyboard import Listener
        except ImportError:
            print("  Missing dependency: pynput. Run this with the same Python environment used by the shortcut.")
            return 1

        threading.Thread(target=auto_enter_loop, daemon=True).start()

        if tray_mode:
            # Global hotkeys still work, but on a background thread.
            threading.Thread(
                target=lambda: Listener(on_press=on_press).run(),
                daemon=True,
            ).start()
            from tray import run_tray
            import autostart

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
            )
            return 0

        with Listener(on_press=on_press) as listener:
            listener.join()

        if running:
            print("  Keyboard listener stopped unexpectedly")
            return 1
        return 0
    finally:
        release_single_instance()


if __name__ == "__main__":
    raise SystemExit(main())
