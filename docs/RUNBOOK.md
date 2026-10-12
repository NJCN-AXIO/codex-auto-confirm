# Runbook — Codex Auto Confirm

## Scope

The utility confirms Codex desktop prompts only when a fresh visible UIA/CDP
readback contains an **allow-once** semantic (`Allow once`, `Yes, proceed`,
`Yes, just this once`). It does not infer completion from a configured label,
window title, or generic `Allow` text.

For inline TUI errors it posts the Chinese message `继续执行` plus <kbd>Enter</kbd>
when the current viewport shows a known transient failure, and waits for an
authoritative `Working (… • esc to interrupt)` or `Compacting context (…)` line
before re-arming.

## Safety rule

A desktop Enter is authorized only after the current read returns a visible
allow-once semantic or a known recoverable error signature.

- The Enter delivery is background-directed with `PostMessageW`; it never calls
  `SetForegroundWindow`, `SetFocus`, or global `SendInput`, so confirming a
  prompt cannot steal focus from the user's active application. CDP errors,
  missing targets, hidden controls, deny/reject text, and permanent-allow text
  fail closed and cause no keypress.
- Windows Terminal / ConPTY confirmation uses the host UI thread plus its
  `InputSite` child: the worker temporarily attaches to that UI thread and posts
  the Enter sequence without changing focus.
- `PseudoConsoleWindow` and top-level posting remain legacy fallbacks for older
  console hosts; they are not the primary Windows Terminal path.

## Controls

- <kbd>F9</kbd> toggles auto-confirm.
- <kbd>F10</kbd> exits intentionally; the batch supervisor does not restart an
  exit code `0` shutdown.
- `CODEX_AUTO_CONFIRM_CDP_PORT` overrides the default local port `27374`.
- `CODEX_AUTO_CONFIRM_RETRY_SECONDS` controls bounded retries while the same
  title-based signal remains visible.
- `CODEX_AUTO_CONFIRM_PROCESS_NAMES` limits Action Required detection to the
  Codex terminal host processes; the default is
  `WindowsTerminal.exe,conhost.exe,codex.exe`.

## Recoverable-error auto-recovery

The Windows Terminal branch reads only the current visible TermControl viewport
through `TextPattern.GetVisibleRanges()`. It requires an OpenAI Codex marker or a
standalone `Codex` terminal title before matching, and ignores the monitor's own
window.

### Inline TUI approvals (codex-cli 0.15.x+)

Recent CLI versions no longer reliably change the terminal title to
`Action Required`. The monitor therefore also recognizes a visible approval
heading such as `Would you like to run the following command?` together with the
normal one-shot option `Yes, proceed` or `Yes, just this once`, grouped by
terminal HWND.

Prompt text quoted in the user input, stale transcript lines,
`Yes, and don't ask again …`, and denial-only menus are ignored. Confirmation
still uses the background-directed Enter path and is edge-triggered once per
visible prompt.

### Error signatures that trigger one `继续执行` + Enter

A visible error-context line triggers exactly one background `继续执行`
message followed by Enter:

- `exceeded retry limit` (including `last status: 429 Too Many Requests`)
- `429 Too Many Requests`
- `Selected model is at capacity. Please try a different model.`
- contextual `502`, `503`, or `504` lines such as `unexpected status 502 Bad Gateway`
- contextual `500` or `501` lines such as `unexpected status 501 Not Implemented`
- `503` account-pool failures containing `auth_unavailable` or `账号池没有可用账号`
- `stream disconnected before completion` errors that include visible
  transport/decode context such as `error decoding response body`

`Reconnecting… 1/5` through `Reconnecting… 5/5` never trigger. A `Working (…)`
or `Compacting context (…)` duration line is also normal; natural-number
durations in seconds/minutes/hours (or localized `秒`/`分钟`/`小时`) are
accepted. Both statuses are authoritative only when they are the current status
line and include `esc to interrupt`.

When the viewport retains an older capacity/retry line and appends a newer
gateway line below it, the newest matching error line is authoritative.

### Delivery state machine

The first visible error sends exactly one `继续执行` + Enter per Codex window.
A successful post remains latched for that error occurrence and is never
semantically retried while the same error remains visible. This avoids filling
Codex's queued-input buffer when UIA status readback is delayed. Only an
explicit input-delivery failure is retried, at
`CODEX_AUTO_CONFIRM_DELIVERY_RETRY_SECONDS`, until delivery succeeds or an
authoritative status/clear ends the latch. The exception is an account-pool
`auth_unavailable` 503: a successful send is repeated every
`CODEX_AUTO_CONFIRM_AUTH_UNAVAILABLE_RETRY_SECONDS` (default 5 seconds) until
the current viewport reports an authoritative `Working (duration • esc to
interrupt)` or `Compacting context (…)` status. Reconnecting progress pauses
sends but does not end this retry policy.

Working, compacting, reconnecting, conversation interruption, an authoritative
clear, or <kbd>F9</kbd> off-state cancels pending sends. Each HWND is
independent, so one window's status cannot suppress another window's error.

The delivery path posts Unicode `WM_CHAR` messages for the four Chinese
characters, then the Enter sequence to the Windows Terminal input target. It
does not use the clipboard, `SetForegroundWindow`, global `SendInput`, or focus
stealing.

If the PowerShell UIA helper exits, emits malformed JSON, or stops answering
past the scan timeout, the reader replaces that helper in-process and continues.

## Tunables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CODEX_AUTO_CONFIRM_RECOVERY_POLL_SECONDS` | `0.25` | Recovery scan interval (floored at 0.1). |
| `CODEX_AUTO_CONFIRM_SCAN_TIMEOUT_SECONDS` | `1.5` | Bound for one in-flight UIA scan. |
| `CODEX_AUTO_CONFIRM_HELPER_RESTART_BACKOFF_SECONDS` | `1.0` | Throttle for relaunching the PowerShell helper. |
| `CODEX_AUTO_CONFIRM_DELIVERY_RETRY_SECONDS` | `0.35` | Interval after a failed input post. |
| `CODEX_AUTO_CONFIRM_AUTH_UNAVAILABLE_RETRY_SECONDS` | `5.0` | Interval after a successful send for an account-pool 503; retries continue until an authoritative working status appears (minimum 1 second). |
| `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS` | `0.8` | Compatibility setting; successful delivery is not semantically retried. |
| `CODEX_AUTO_CONFIRM_CONFIRMATION_TIMEOUT_SECONDS` | `5.0` | Compatibility setting; it does not trigger another send after successful delivery. |
| `CODEX_AUTO_CONFIRM_DESKTOP_POLL_SECONDS` | `1.0` | CDP desktop probe interval. |

## Troubleshooting

### "Another Codex auto-confirm monitor is already running"

This comes from a named Windows mutex, not a stale lock file. It means another
`codex_auto_confirm.py` process currently owns the monitor. Do not start a
second copy. To inspect the owner without changing state:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'codex_auto_confirm' } |
  Select-Object ProcessId, ParentProcessId, Name, CreationDate, CommandLine
```

Press <kbd>F10</kbd> once to let the existing worker and its batch supervisor
exit cleanly, then start one fresh copy. Only if the owner is no longer
responsive should its `python.exe`/`cmd.exe` pair be ended before restarting.

After editing `codex_auto_confirm.py`, restart the monitor — the running Python
worker does not hot-reload source changes.

### Run the regression suite

```powershell
python -m pytest scripts\ -q
```
