# Runbook — Codex Auto Confirm

## v1.3.4: native approval after Running

A production capture showed a complete selected `Yes, proceed` menu after
submitted input and a native Running row. The old owner discarded its indented
heading as tool output, then interpreted the outer-column selection as a
draft. Exact-record replay and an isolated real terminal both produced zero
sends with the old owner.

`_recovery_output_lines` now ends that tool block only at an exact approval
heading when the rest of the range contains exactly one top-level prompt,
that prompt is a numbered selection and the final nonblank row is the complete
confirmation footer. Existing live-composer ownership still takes precedence.
An old selected row cannot bridge a draft to another selected row. Permanent
or denial selections, pane/input guards, request identity, fresh readback and
the hard three-post limit remain on the existing approval path.

Independent read-only review found two composer-crossing cases; each was
reproduced RED and retained as a regression before final review passed.
Eight focused regressions and all 296 installed Windows tests passed. With
the final owner, the real UIA/original sender fixture received 3/3 single CRs
and no extras, maximum 0.406 s. The receiver executed no commands or MCP calls.
Foreground was unchanged during delivery. No overnight soak is claimed.

On recurrence, correlate HWND/time with the local pre-delivery journal; a
successful post is not proof of acceptance. Do not restart the worker to retry
an approval because in-memory budgets would be lost. A deployment requires
fresh authoritative clear states first. Action Required titles can be stale
even during current Working; semantic status is the readback authority.
Exit an old installation before launching the new EXE; workers do not hot-reload.
Raw journals/captures stay private and are excluded from releases.

## v1.3.3 operation and evidence

### MCP single-field form

Only the full `Field 1/1` server/tool heading, four exact options, submission
footer and explicitly selected `1. Allow` authorize input. `Allow for this
session`, `Always allow`, `Cancel`, missing selection and incomplete forms
block approval and continuation. This uses the existing approval owner and
three-post request budget. Request keys preserve server/tool/argument case and
internal string spacing. Native tool output and pasted/numbered drafts cannot
authorize a form. This support requires visible text; buffer-tail navigation
currently recognizes the standard YES/NO footer only.

### Historical viewport and Enter delivery

For Action Required, a single pane, no selected text and a verified current
one-time buffer-tail menu permit view repair. The bounded tail starts at 16,000
characters and expands once to 65,536 only when the footer exists but the
selected row is missing. Three attempts are paced immediately, after at least
one second, then at least three more seconds. Only a later independent visible
scan can authorize Enter. Navigation cannot replenish the Python post budget.

Enter posts key-down/key-up only. Posting WM_CHAR for Enter as well produced
two CR characters in a translating terminal message pump. Text continues to use
WM_CHAR. Windows Terminal fallback resolves the same parent's InputSite;
partial delivery never falls back or replays Enter. A failed key-up gets only
key-up cleanup. Focus/global input APIs are not introduced.

### Freshness, health and recovery

Nonempty snapshots older than 0.5 seconds from scan start are unknown. Error
continuation takes an independent fresh preflight; current Working, queued
messages, ambiguity, drafts and recent input block it. Persistent capacity/503
recovery retains its existing handling for cropped/incomplete composer ranges:
two incomplete fresh preflights can permit a retry based on the original error
snapshot, while all negative guards still apply. Partial output cannot clear a
Working barrier. A matching submitted continuation checkpoint distinguishes a
new failure after Working from an old error redraw. Public language selection
is bound to the actual successful send for that HWND; another language's draft
does not become the monitor's own continuation.

The former account-pool five-second environment setting is superseded by the
common `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS` (default three seconds).
Other errors retain their one-shot successful-delivery policy.

Health writes atomically every two seconds, reports pending as stalled after
ten seconds and missing fresh UIA after five seconds. Eligible stalled readers
can refresh after eight seconds, at most twice per episode and once per global
30 seconds. Python trackers and the hard three-post approval limit remain
intact. A heartbeat proves monitor activity, not approval acceptance.

Source diagnostics live in `scripts/run_logs`; frozen EXE diagnostics live in
`%APPDATA%\codex-auto-confirm`, outside `_MEIPASS`. Health contains state,
counters and request digests. The decision journal includes up to 16,000
characters from each initial/fresh snapshot and can contain private content;
it rotates at 2 MiB with one previous file. Inspect/redact before sharing.
Raw captures, logs, backup files and diagnostic bundles are excluded from releases.

### Bounded acceptance and publication

The prior installed source passed 288 Windows regressions. Isolated real UIA,
original owner and actual sender tests observed 12/12 main Enter receipts
(maximum 0.938 s), 3/3 forced fallback (0.750 s), 3/3 marked Chinese continuation
(0.687 s), and 3/3 MCP-form receipts (0.391 s), each with one CR and no extras.
Send/scroll operations preserved foreground. The fixture executes no commands
or actual MCP calls. Classic conhost fallback and a real overnight soak were
not tested live; this is not a guarantee that every future prompt will match.

Public integration adds language/override preflight-to-Working-to-new-error
coverage and actual frozen health/journal file readback. The public regression
suite and Ruff must pass, followed by Windows CI for the exact main commit,
before tagging. Read back the tag, Release workflow and nonempty EXE asset.
Installed workers do not hot-reload: exit the old monitor before starting an
updated source/EXE. A publication operation must not restart the local monitor.

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
| Any current contextual HTTP 503 | Retry every 3 s while fresh error evidence persists. |
| Other error | One successful continuation per visible episode. |

Failed posts retry every 0.35 s. Non-continuous errors stop after three
consecutive failures; capacity/503 errors keep paced retries pending. Successful
paced retries do not consume the failure budget. Every retry needs fresh evidence and
passes draft/typing guards. Changed wording does not create a second send within
the same episode. Each HWND is independent.

### Authoritative status and stop barriers

- Current `Working (duration)` or `Compacting context (duration)` stops retries.
  Seconds/minutes/hours and localized units are accepted; `esc to interrupt`
  is optional. Known spinners may split label and duration, including blank UIA
  ranges between them. Both scans join at most five nonempty rows and retain
  the existing decoration/prose guards. Quoted/indented
  examples and arbitrary prose never qualify.
- Working/Compacting binds a still-visible old error to a barrier. If redraw
  drops that row, the stale signature stays quiet. A clean processing readback
  re-arms a later real error.
- `Reconnecting... n/5` pauses recovery. When it disappears the existing
  tracker can recognize a new final-error edge; it does not send while reconnecting.
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
| `CODEX_AUTO_CONFIRM_SNAPSHOT_MAX_AGE_SECONDS` | `0.5` | Nonempty response age from scan start; minimum 0.1 s. |
| `CODEX_AUTO_CONFIRM_INCOMPLETE_RETRY_SCANS` | `2` | Incomplete fresh-read threshold for continuous recovery; minimum 2. |
| `CODEX_AUTO_CONFIRM_HELPER_RESTART_BACKOFF_SECONDS` | `1.0` | Pace helper replacement. |
| `CODEX_AUTO_CONFIRM_DELIVERY_RETRY_SECONDS` | `0.35` | Failed-post retry interval. |
| `CODEX_AUTO_CONFIRM_MAX_ATTEMPTS` | `3` | Failure budget; clamped to 1–5. |
| `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS` | `3.0` | Capacity/503 interval; minimum 1.2 s. |
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
full desktop captures containing other sessions. The three images above
demonstrate the CLI approval path.

### HTTP 429/503 fault-injection captures

Also on 2026-10-22, two separate **Codex CLI 0.155.1** sessions received real HTTP
errors from a loopback-only test endpoint. Each session used a new, empty demo
workspace and its own `CODEX_HOME`; no existing configuration or authentication
was copied. The provider's `base_url` pointed to `127.0.0.1`, with
`request_max_retries = 0`, `stream_max_retries = 0` and `supports_websockets = false`.
These settings were checked against the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
and then verified with a bounded CLI protocol probe (error exit 1, test-response
exit 0). No remote model service was called for the demo.

The existing running watchdog handled the visible error through its normal UIA
reader and background PostMessage delivery. The capture helper did not type a
continuation. The test endpoint recorded the latest actual `user` message as
exactly `继续！`, then returned a local Responses SSE test response. Continuous
raw screenshot bursts and the CLI's own rollout records retain the initial
error, submitted continuation, Working status and completed test response.

| Asset | Observed conversation request sequence | Native crop size |
| --- | --- | --- |
| `screenshots/recovery-429.png` | HTTP 429 → latest user message `继续！` → HTTP 200 test response | 1084 × 190 |
| `screenshots/recovery-503.png` | HTTP 503 → latest user message `继续！` → HTTP 200 test response | 1084 × 210 |

The screenshots are lossless rectangular crops of the real terminal pixels.
Both the README captions and the test response identify the local fault
injection. They demonstrate automatic continuation delivery and CLI acceptance
of the test response; the response is generated by the test service.

Use separate sessions for separate ordinary-error cases. A changed error string
in one episode does not re-arm its successful-send latch. When verifying the
HTTP timeline, compare the latest actual conversation user message exactly;
background task-title requests and quoted prompt text are not continuation
evidence. The 503 capture is an ordinary service-unavailable error, not the
special account-pool `auth_unavailable` five-second retry case.

Only the demo's registered Windows Terminal windows were closed after capture.
The production watchdog and existing sessions were left running. The private
capture bundle includes the exact-source crop manifest, request timelines,
protocol probe and an independent read-only review of the isolation and claims.

For future updates, capture the live prompt and its authoritative outcome in the
same session, inspect every final image for private content, verify referenced
paths and image dimensions, and run `git diff --check`. Documentation/assets-only
updates do not require a new EXE release.
