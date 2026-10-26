# codex-auto-confirm

![Tests](https://github.com/NJCN-AXIO/codex-auto-confirm/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)

A Windows watchdog for **OpenAI Codex CLI** that automatically presses
<kbd>Enter</kbd> on permission prompts and self-heals transient runtime errors
— without ever stealing your focus.

### Quick summary / 快速了解

**English:** A Windows watchdog for OpenAI Codex CLI that safely auto-confirms
one-shot prompts and recovers transient errors without stealing focus. Ordinary
transient errors are continued once after successful delivery. A persistent model
capacity warning or HTTP 503 is retried every 3 seconds while fresh error
evidence remains. A fresh authoritative
`Working (duration)` or `Compacting context (duration)` status stops retries.
Draft text, recent typing, an explicit interruption, or an ambiguous pane blocks input.

**中文：** Windows 下的 OpenAI Codex CLI 守护工具，可在不抢占焦点的情况下
自动确认一次性授权并恢复瞬时错误。普通瞬时错误成功发送一次后等待状态确认；
持续的模型容量不足或 HTTP 503 每 3 秒重试，
直到检测到新的权威状态 `Working (duration)` 或 `Compacting context (duration)`。
草稿、近期键盘输入、主动中断及无法确定输入目标的多窗格都会阻止自动输入。

> **Tested on:** Windows Terminal + `codex-cli` 0.156.x. The code also ships a
> CDP path aimed at the Codex Desktop "Allow once" dialog, but the author has
> only run the CLI flow end-to-end; the desktop path is included as-is and is
> community-tested at best.

## v1.3.5 / 本次更新

- Recognizes the exact `(p)` shortcut after a complete command-scope option,
  so consecutive clipped approvals retain distinct request identities.
- 修复另一个窗口连续审批漏回车：命令范围末尾的 `(p)` 快捷键不再导致请求身份丢失。
  保留现有草稿保护、读回间隔和每请求三次投递上限。
- Real-terminal verification: the old owner timed out on the second menu;
  the repaired owner received 3/3 single CRs without an intervening Working clear.
  These are bounded tests; no guarantee of every future prompt is made.

### v1.3.4 / 先前更新

- Fixes a further missed YES/NO confirmation when a native approval heading
  is indented under `Running` after previously submitted input.
- Recognizes only a complete overlay with one outer-column selection and a
  confirmation footer; interleaved drafts and old selected rows block input.
- 修复历史输入和 Running 输出后的缩进审批菜单漏确认；补充两种跨草稿误触回归。
  本次修复通过三轮真实终端单回车收件；有限验收不代表整晚运行保证。

### v1.3.3 capabilities / 已有功能

- Recognizes the complete `Field 1/1` MCP permission form when **1. Allow**
  is explicitly selected. Session, permanent, cancel and incomplete choices block input.
- Repairs a verified historical YES/NO viewport, checks subsequent visible
  readback, and reports stalled approvals with bounded reader recovery.
- Delivers one Enter through the terminal InputSite, including fallback;
  English/custom recovery text, tray and EXE packaging are preserved.
- 新增 MCP 单次 Allow 表单识别；修复 YES/NO 停留历史视口、重复回车和回退投递；
  增加卡住状态及有上限的读取器恢复。不会自动选择会话或永久授权。

Existing installations must exit the old monitor with F10 or tray Exit before
launching the new EXE. The single-instance guard does not hot-reload an old worker.
更新后先用 F10 或托盘 Exit 退出旧进程，再启动新版；覆盖 EXE 不会热更新。

## Real usage / 实际运行

Captured from a live Codex CLI session in Windows Terminal on **2026-10-22**.
The approval demo command only prints a line of text. These are cropped screenshots of
the actual approval, command result and watchdog console.

以下为 Windows Terminal 中的真实运行截图，仅裁剪无关区域。授权演示命令只打印一行文字。

**1. A real permission prompt / 真实授权菜单**

![Live Codex permission prompt with Yes, proceed selected](docs/screenshots/approval.png)

**2. Automatically approved, command completed / 自动确认后执行完成**

The prompt disappears, the command runs, and Codex shows `Working` again.
授权菜单消失，命令执行完成，Codex 回到 `Working` 状态。

![Same command approved and executed, followed by Working status](docs/screenshots/approved.png)

**3. Background watchdog log / 后台守护日志**

The console records the background Enter delivery and waits for menu readback.
控制台记录后台发送 Enter，并等待授权菜单状态读回。

![Actual watchdog console showing Enter delivery and menu readback waiting](docs/screenshots/monitor.png)

### Error recovery / 报错后自动发送“继续！”

**Local fault injection, real CLI and watchdog.** A loopback test endpoint returns
HTTP 429 or 503 to an isolated Codex session. The running watchdog automatically
submits `继续！`; the endpoint receives that exact user message and returns a test
response. The success text comes from the local test service.

**本地故障注入实拍：** 测试接口实际返回 429/503，真实 Codex CLI 显示报错，
现有守护程序自动提交“继续！”。接口确认收到该消息后返回测试响应；成功文字由本地测试服务生成。

**HTTP 429 — Too Many Requests → 自动发送“继续！”**

![Real Codex CLI showing HTTP 429, automatically submitted 继续！ and local test response](docs/screenshots/recovery-429.png)

**HTTP 503 — Service Unavailable → 自动发送“继续！”**

![Real Codex CLI showing HTTP 503, automatically submitted 继续！ and local test response](docs/screenshots/recovery-503.png)

Capture details: [`docs/RUNBOOK.md`](docs/RUNBOOK.md#readme-screenshot-provenance).

---

## Why

Codex CLI (≥ 0.15.x) periodically interrupts a long session to:

1. Ask for permission before running a command or applying edits
   (`Would you like to run the following command?` → `Yes, proceed`).
2. Surface transient errors that a single "continue" clears —
   `429 Too Many Requests`, `model at capacity`, `502/503/504 Bad Gateway`,
   `stream disconnected before completion`.

Leaving Codex unattended means it stalls until you come back. This tool watches
every Windows Terminal / ConPTY window that hosts Codex and presses the right
key at the right moment, using **background `PostMessage` delivery** — it never
calls `SetForegroundWindow`, `SetFocus`, or global `SendInput`, so it will not
yank focus away from whatever you are doing.

## Features

- **One-shot approval auto-confirm** for the inline TUI menus
  (`Yes, proceed` / `Yes, just this once`) — the primary, author-tested path.
- **Error self-recovery**: on a visible `429` / `5xx` / capacity / stream-error
  line it posts `继续！` or `continue` + <kbd>Enter</kbd>, then waits for an authoritative
  `Working (… • esc to interrupt)` or `Compacting context (…)` status before
  re-arming. Successful sends are not repeated just because UIA readback is
  delayed. Persistent capacity warnings and HTTP 503 errors retry every
  3 seconds until an authoritative working status appears. Stale
  transcript lines and historical errors are ignored.
- **Multi-window aware**: each terminal HWND is tracked independently.
- **Focus-safe**: keyboard input is delivered with `PostMessageW` /
  `WM_CHAR` directly to the terminal's `InputSite`; the foreground window stays
  yours.
- **Request tracking**: consecutive different command requests can be confirmed
  even if the intervening clear is missed. Partial menu reads preserve the
  delivered request's latch and failed-post budget.
- **Approval readback**: a queued Enter still waits for acceptance. If the same
  complete command menu persists in two fresh safe reads after at least 2 s,
  retry within a total three-post budget. Drafts, Working and pane ambiguity
  block these retries; anonymous menus retain their one-shot successful latch.
- **Single-instance**: a named Windows mutex prevents duplicate monitors.
- **Supervised restart**: the `.bat` launcher restarts the Python monitor after
  a crash, with a real delay even when hidden. Console and tray modes detect
  dead worker/listener threads and respect a clean <kbd>F10</kbd> exit.
- **Typing protection**: unfinished drafts and recent typing defer input. Multiple
  TermControls in one window defer input until its target is unambiguous.
- **No screenshots, no OCR**: it reads the terminal through the native Windows
  UIA TextPattern API, so it works on any DPI / font size.
- **Multi-language recovery**: detects Chinese vs English Codex UI and sends
  `继续！` or `continue` accordingly (override with
  `CODEX_AUTO_CONFIRM_RECOVERY_TEXT`).
- **System tray**: green/grey icon shows ON/OFF; right-click to toggle, enable
  Windows startup, or quit.
- **(Untested) Codex Desktop "Allow once" via CDP** — code included, not
  verified by the author. See the Safety notes before relying on it.

## Requirements

- Windows 10 / 11 (64-bit)
- Windows Terminal (for the TUI approval path); the ConPTY fallback also works

## Install — easiest (EXE)

Download `codex-auto-confirm.exe` from the
[latest release](https://github.com/NJCN-AXIO/codex-auto-confirm/releases/latest)
and double-click it. A small green icon appears in the system tray; that's it.
No Python install required.

Right-click the tray icon to toggle auto-confirm, enable/disable Windows
startup, or quit.

## Install — from source

```powershell
git clone https://github.com/NJCN-AXIO/codex-auto-confirm.git
cd codex-auto-confirm
pip install -r requirements.txt
```

The UIA reader ships as a small PowerShell script
(`scripts/codex_terminal_uia_reader.ps1`) — no extra install needed, it is
launched on demand by the Python monitor.

## Run

Console mode (with visible log window):

```powershell
python scripts\codex_auto_confirm.py
```

Tray mode (no console window):

```powershell
python scripts\codex_auto_confirm.py --tray
```

You should see:

```
=======================================================
  Codex CLI Auto Confirm
  Codex: found
  Trigger title: action required
  Auto Confirm: ON
  F9=toggle  F10=exit
=======================================================
```

Start Codex in a Windows Terminal window as usual. Leave this monitor running in
the background.

## Hotkeys

| Key | Action |
|-----|--------|
| <kbd>F9</kbd> | Toggle auto-confirm on / off (also resets the recovery latch) |
| <kbd>F10</kbd> | Exit cleanly (the `.bat` supervisor will **not** restart a clean exit) |

In tray mode, the same toggle is also available from the right-click menu.

## Configuration

All tuning is via environment variables — no config file to edit.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CODEX_AUTO_CONFIRM_TITLE` | `codex` | Window-title fragment used by the legacy title-based finder. |
| `CODEX_AUTO_CONFIRM_ACTION_TITLE` | `Action Required` | Legacy title that signals a pending approval. |
| `CODEX_AUTO_CONFIRM_PROCESS_NAMES` | `WindowsTerminal.exe,conhost.exe,codex.exe` | Process names eligible for Codex-terminal detection. |
| `CODEX_AUTO_CONFIRM_CDP_PORT` | `27374` | Local CDP port used for the Codex Desktop "Allow once" dialog. |
| `CODEX_AUTO_CONFIRM_RECOVERY_TEXT` | _(auto)_ | Pin the exact "continue" command sent after a recoverable error. Default: auto-detect Chinese vs English. |
| `CODEX_AUTO_CONFIRM_RECOVERY_POLL_SECONDS` | `0.25` | How often the UIA scanner wakes up. |
| `CODEX_AUTO_CONFIRM_SCAN_TIMEOUT_SECONDS` | `1.5` | Timeout for one in-flight UIA scan. |
| `CODEX_AUTO_CONFIRM_SNAPSHOT_MAX_AGE_SECONDS` | `0.5` | Discard nonempty UIA responses older than this from scan start (minimum 0.1 s). |
| `CODEX_AUTO_CONFIRM_CONFIRMATION_TIMEOUT_SECONDS` | `5.0` | Compatibility setting; a successful delivery is not resent while the same error remains visible. |
| `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS` | `3.0` | Retry interval for persistent capacity warnings and HTTP 503 (minimum 1.2 seconds). |
| `CODEX_AUTO_CONFIRM_POWERSHELL` | `powershell.exe` | Path to the PowerShell executable used for the UIA helper. |

See [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the full list and the exact
error signatures that trigger recovery.

## Safety notes

- This tool sends <kbd>Enter</kbd> (and, for the Chinese locale, the message
  `继续！`) **only** after the current UIA/CDP read proves a real
  one-shot approval or a known transient error is on screen. It does **not**
  infer completion from a window title or a generic substring.
- Deny / reject menus, "always allow" options, quoted examples inside the
  transcript, and historical error lines all fail closed — no keypress is sent.
- It intentionally does **not** read passwords or type into any field that is
  not a Codex approval / error prompt.
- Still, run it only on machines and sessions you control.

### Local diagnostic data / 本地诊断数据

The health JSON contains state, counters and request digests. The rotating
`codex-recovery-decisions.jsonl` also retains up to 16,000 characters from each
initial/fresh terminal snapshot and may contain private terminal text. Source
mode stores these under `scripts/run_logs`; the EXE stores them beside
`watchdog.log` under `%APPDATA%\codex-auto-confirm`. Each journal rotates at
2 MiB with one previous file. Inspect and redact diagnostics before sharing.

健康 JSON 保存状态摘要；决策日志还会保存部分终端原文，可能含隐私。源码版位于
`scripts/run_logs`，EXE 版位于 `%APPDATA%\codex-auto-confirm`。分享前请检查并脱敏。

## Troubleshooting

| Symptom | Fix |
|---|---|
| Console says `Codex: not found` | Start Codex in a **Windows Terminal** window first. The watchdog only detects ConPTY / Windows Terminal hosting `codex`. |
| Prompt appears but no auto-confirm | Press <kbd>F9</kbd> to make sure auto-confirm is `ON`; check the tray icon colour. |
| Tray icon doesn't appear on first run | The EXE starts minimized to tray. Look in the overflow chevron (the `^` on the taskbar) and drag the icon out if you want it pinned. |
| Nothing happens on a `429` / `503` | Your Codex UI may be in a language other than English/Chinese. Set `CODEX_AUTO_CONFIRM_RECOVERY_TEXT` to the exact "continue" command your Codex expects. |
| I want to see what it is doing | Open `%APPDATA%\codex-auto-confirm\watchdog.log`, or right-click the tray icon → **Open log folder**. |
| It keeps relaunching after I close it | You ran `codex_auto_confirm.bat`, which is a supervised launcher. Press <kbd>F10</kbd> inside the console for a clean exit, or close the window and wait 2 s — the bat will restart it; press Ctrl+C in the console instead to stop the loop. |
| `Another monitor is already running` | A previous instance (or tray) is still alive. Right-click its tray icon → Exit, or kill `codex-auto-confirm.exe` in Task Manager. |

## Uninstall

Run `scripts\uninstall.bat` (or, for the EXE, right-click and Run as
administrator is **not** needed — everything is per-user). It will:

1. Remove the `CodexAutoConfirm` Windows autostart entry.
2. Terminate any running `codex-auto-confirm.exe`.

Then delete the EXE / source folder you downloaded. Logs stay at
`%APPDATA%\codex-auto-confirm\`; delete that folder manually for a full clean.

## Development

Run the regression suite (no real Codex window needed — everything is mocked):

```powershell
python -m pytest scripts\ -q
```

A read-only live probe (prints the currently visible Codex snapshots, sends
nothing):

```powershell
python -c "import importlib.util,time; \
p=r'scripts\codex_auto_confirm.py'; \
s=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); \
r=m.CodexTerminalReader(); r.request_scan(); time.sleep(1); \
v=r.poll(); print([(x.get('title'), x.get('hwnd')) for x in (v or []) if m.eligible_codex_snapshot(x)]); r.close()"
```

## Project layout

```
codex-auto-confirm/
├── scripts/
│   ├── codex_auto_confirm.py          # The watchdog (main entry point)
│   ├── codex_terminal_uia_reader.ps1  # UIA TextPattern reader (child process)
│   ├── tray.py                       # System-tray UI (pystray)
│   ├── autostart.py                  # Windows Run-key startup toggle
│   ├── codex_auto_confirm.bat        # Supervised launcher / restart loop
│   ├── uninstall.bat                 # Remove autostart + kill running EXE
│   ├── test_codex_auto_confirm.py
│   ├── test_codex_auto_confirm_guards.py
│   ├── test_codex_auto_confirm_recovery.py
│   ├── test_codex_auto_confirm_desktop.py
│   └── test_recovery_text.py         # i18n / language detection tests
├── docs/
│   ├── RUNBOOK.md                    # Detailed behavior & tuning reference
│   └── screenshots/                  # Real Windows Terminal captures
│       ├── approval.png
│       ├── approved.png
│       ├── monitor.png
│       ├── recovery-429.png
│       └── recovery-503.png
├── pyproject.toml
├── requirements.txt
├── CHANGELOG.md
├── LICENSE                           # MIT
└── README.md
```

## License

[MIT](LICENSE)
