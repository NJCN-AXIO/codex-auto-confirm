# Runbook — Codex Auto Confirm

## Scope and input ownership

Terminal approvals require a fresh visible UIA menu with a selected one-time
option. Desktop approvals require a fresh visible CDP `Allow once` semantic;
that path remains experimental. Window titles and successful Windows message
delivery are not completion evidence.

`Action Required` alone cannot authorize input. Its compatibility fallback
requires numbered one-time and denial choices, or a selected one-time choice
plus `Press enter to confirm or esc to cancel`. Permanent/denial selections,
historical menus and drafts block delivery.

The semantic snapshot processor owns terminal input. A current approval defers
recovery in the same window. Successful approval posts await authoritative
readback; queuing Windows input is not proof that the approval was accepted.

For a stable command key, two fresh complete safe menu reads after at least
two seconds authorize another post, with a total three-post budget including
failed posts. `CODEX_AUTO_CONFIRM_RETRY_SECONDS` may lengthen that wait but
cannot shorten it below two seconds. Failed posts retain their 0.35 s interval.
Unknown or blocked new observations interrupt the two-read evidence without
resetting budgets. `poll() == None` means no new response, so it neither advances
nor interrupts evidence; observations separated by the scan timeout start again.
Anonymous/non-command menus do not retry successful posts.

A previously unseen complete command key or authoritative clear confirms the
prior successful post. A historical known key only interrupts evidence; it
cannot acknowledge a newer pending request. Retries run synchronously from
fresh UIA observations with all input guards, never from a background timer.
UIA and Windows input posting are not atomic; delayed/stale observations must
not be described as accepted input. Logs explicitly say awaiting menu readback.

Command requests are identified from the latest heading and the `$ command`
block, preserving command case, internal spacing and line breaks. Transcript
prefixes and independently missing Thread/Environment/Reason ranges do not
create requests. Each command keeps its own delivery latch and failure budget,
so A/B/A redraws cannot replay A. Without a stable command body, including
non-command overlays, retain the existing episode latch. At 128 remembered
requests input pauses until a processing/empty-composer clear; identities are
never evicted to make old requests eligible again.

Empty, heading-only, options-only or footer-only reads are unknown. A later
Working/Compacting status or an empty composer with a recognized terminal
footer proves clear. Old Working text above a current menu cannot clear it.

## Drafts, panes and focus

- Nonempty composer rows (`›`, `»`, `>`), wrapped text, multiline drafts and
  nested quotes are protected. Only the exact empty placeholder is exempt.
- Physical input in the foreground target defers all Enter paths for 1.2 s.
  Input elsewhere does not block this target. No key contents are collected;
  unavailable activity reads fail closed.
- Multiple TermControls under one HWND set `input_ambiguous=true`, even when
  one control cannot be read. Input and state changes pause for that window
  until one target remains. Independent windows continue.
- Text and Enter share one resolved InputSite and attachment. Partial delivery
  cannot replay through a fallback. Background PostMessage never uses the
  clipboard, SetForegroundWindow, SetFocus or global SendInput.

UIA reads and Windows message posting are separate operations. These guards
reduce timing races; they do not make the Windows message queue atomic.

## Recovery policy

The scanner reads visible UIA ranges and ignores its own monitor. A Codex
marker/title is preferred; a recognized live error or processing status can
also identify a generically titled terminal window. Current contextual HTTP
429/500–504 errors, capacity warnings, stream errors, structured API error
envelopes and error-glyph output lines are recognized. Drafts, quoted examples,
user prose and historical monitor logs are not error evidence.

Language selection sends `继续！` for Chinese and `continue` for English.
`CODEX_AUTO_CONFIRM_RECOVERY_TEXT` overrides both. Chinese punctuation identifies
automatic activations.

| Current error | Successful delivery policy |
| --- | --- |
| Model capacity warning | Retry every 3 s while a fresh warning persists. |
| Account-pool 503 with `auth_unavailable` or `账号池没有可用账号` | Retry every 5 s; reconnecting preserves the interval. |
| Other error | One successful continuation per visible episode. |

Failed posts retry every 0.35 s, up to three consecutive failures. Successful
paced retries do not consume that budget. Every retry needs fresh evidence and
passes draft/typing guards. Changed wording does not create a second send within
the same episode. Each HWND is independent.

### Authoritative status and stop barriers

- Current `Working (duration)` or `Compacting context (duration)` stops retries.
  Seconds/minutes/hours and localized units are accepted; `esc to interrupt`
  is optional. Known spinners may split label and duration, including blank UIA
  ranges between them. Both scans join at most three nonempty rows and retain
  the existing decoration/prose guards. Quoted/indented
  examples and arbitrary prose never qualify.
- Working/Compacting binds a still-visible old error to a barrier. If redraw
  drops that row, the stale signature stays quiet. A clean processing readback
  re-arms a later real error.
- `Reconnecting... n/5` pauses recovery. For account-pool retries it preserves
  last-send time so a redraw cannot bypass the five-second interval.
- `Conversation interrupted` is an intentional ESC stop. Its barrier survives
  scrolling until a later real Working/Compacting status. Draft quotes cannot
  create this barrier.
- Empty, missing, malformed or incomplete scans are unknown reads. They cannot
  clear live HWND state or its ESC barrier. Only closed HWNDs are pruned.
- F9 off resets trackers. An unrelated window's status cannot suppress another.

## Reader and process health

Hidden PowerShell pipes explicitly use UTF-8 without BOM. Process/queue generations
are isolated; old drain threads cannot overwrite new responses. Helper failures
are paced and logged. Valid responses clear the failure episode. Helpers are
terminated/reaped before pipes close, preventing shutdown deadlocks. Desktop
CDP reads have a total deadline and close failed sockets.

Console and tray modes detect dead monitor and keyboard listener threads and
exit nonzero. The portable batch supervisor honors its delay even with redirected
stdin by using noninteractive PowerShell. F10 or tray Exit is intentional and
exits zero. The standalone EXE exits on failure; it has no batch supervisor
unless the operator supplies one.

Frozen builds find the helper under `sys._MEIPASS`. Source autostart uses the
current Python and sibling `codex_auto_confirm.py --tray`. Logs are written to
`%APPDATA%\codex-auto-confirm\watchdog.log`.

## Controls and tunables

F9 toggles monitoring. F10 exits. Tray menus also toggle startup and open logs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_AUTO_CONFIRM_RECOVERY_POLL_SECONDS` | `0.25` | UIA interval; minimum 0.1 s. |
| `CODEX_AUTO_CONFIRM_SCAN_TIMEOUT_SECONDS` | `1.5` | One in-flight scan timeout. |
| `CODEX_AUTO_CONFIRM_HELPER_RESTART_BACKOFF_SECONDS` | `1.0` | Pace helper replacement. |
| `CODEX_AUTO_CONFIRM_DELIVERY_RETRY_SECONDS` | `0.35` | Failed-post retry interval. |
| `CODEX_AUTO_CONFIRM_MAX_ATTEMPTS` | `3` | Failure budget; clamped to 1–5. |
| `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS` | `3.0` | Capacity interval; minimum 1.2 s. |
| `CODEX_AUTO_CONFIRM_AUTH_UNAVAILABLE_RETRY_SECONDS` | `5.0` | Account-pool interval; minimum 1 s. |
| `CODEX_AUTO_CONFIRM_RECOVERY_TEXT` | automatic | Override recovery text. |
| `CODEX_AUTO_CONFIRM_DESKTOP_POLL_SECONDS` | `1.0` | CDP probe interval. |
| `CODEX_AUTO_CONFIRM_CDP_PORT` | `27374` | Desktop CDP port. |
| `CODEX_AUTO_CONFIRM_POWERSHELL` | `powershell.exe` | Helper interpreter. |
| `CODEX_AUTO_CONFIRM_RESTART_DELAY` | `2` | Batch restart delay in seconds. |

`CODEX_AUTO_CONFIRM_CONFIRMATION_TIMEOUT_SECONDS` and
`CODEX_AUTO_CONFIRM_MISSING_WINDOW_GRACE_SCANS` remain compatibility settings;
they cannot manufacture recovery or discard a live window's barrier.

## Troubleshooting and release acceptance

"Another Codex auto-confirm monitor is already running" comes from the named
mutex. Do not delete a lock file or start a second worker. Use F10 or tray Exit,
then launch one fresh copy after updating; workers do not hot-reload.

```powershell
python -X utf8 -m pytest scripts/ -q
ruff check scripts/
python scripts/codex_auto_confirm.py --version
git diff --check
```

The October 21 update reproduced old runtime failures before merging the new
stability suites: approval latches, Working redraw barriers and hidden restart
timing. Integration tests cover account-pool pacing through reconnecting,
single-target language delivery, frozen resources, autostart, tray worker/listener
failure and intentional exit. No test sends input to a real Codex conversation.

Publish main after these checks pass. Require Windows Tests for the exact commit
before tagging. The existing Release workflow builds the Windows EXE; read back
the tag SHA, successful workflow and nonempty `codex-auto-confirm.exe` asset
before claiming publication.

The v1.3.1 follow-up records deterministic RED/GREEN replays for split Working,
consecutive requests, partial menus, metadata loss and per-request retry budgets.
A reported stuck live window was captured with a complete eligible menu, no
draft and an unambiguous target. After the corrected local monitor was reloaded,
read-only UIA showed the menu gone and Working active. Initial passive sampling
had not captured a failure; recording-sender tests never inject test messages
into real conversations.

## README screenshot provenance

On 2026-10-22, the README's drawn schematic was replaced with actual Windows
Terminal screenshots from a live Codex CLI session and its running watchdog.
The permission request ran this harmless command:

```powershell
rtk proxy python -X utf8 -c "print('Approval received. The watchdog handled this prompt automatically.')"
```

The watchdog accepted the one-time permission prompt. A screenshot burst captured
the real menu, then the same command's approval/result and a current Working
status. The running monitor's console separately recorded background Enter
delivery to that terminal (HWND `8457658`) and waiting for menu readback. A queued
Enter log alone is not acceptance evidence; the executed command in `approved.png`
provides the readback. The printed sentence is demo output, not a monitor status.

| Asset | Captured content | Native crop size |
| --- | --- | --- |
| `screenshots/approval.png` | Actual permission menu, selected `Yes, proceed` | 1084 × 290 |
| `screenshots/approved.png` | Same command approved/executed, then Working | 1084 × 156 |
| `screenshots/monitor.png` | Actual watchdog console log | 902 × 121 |

Only rectangular crops and lossless PNG encoding were applied. Terminal text,
UI and logs were not drawn, replaced or generated. Unrelated transcript content,
window title bars and empty space were cropped out. Raw captures and their crop
coordinates/hashes remain in the maintainer's local diagnostics; do not publish
full desktop captures containing other sessions. These images demonstrate the
CLI approval path, not a staged error-recovery or Codex Desktop dialog.

For future updates, capture the live prompt and its authoritative outcome in the
same session, inspect every final image for private content, verify referenced
paths and image dimensions, and run `git diff --check`. Documentation/assets-only
updates do not require a new EXE release.
