# Changelog

## [1.3.3] - 2026-10-25

### Fixed / 修复

- Recognize complete single-field MCP permission forms only when the explicit
  selected option is one-time Allow; keep the original request identity,
  readback, draft guards and total three-post approval budget.
- Restore verified historical approval viewports with three paced navigation
  attempts. Buffer-tail text authorizes navigation only; input still needs a
  subsequent fresh visible scan.
- Remove the duplicate Enter character source and route Windows Terminal
  fallback to the same InputSite. Partial delivery never replays Enter.
- Discard stale UIA scans, retain Working barriers through partial redraws,
  and avoid absent-desktop CDP timeouts delaying terminal scans.
- Preserve public language overrides through fresh preflight and recovery
  checkpoints; keep packaged health/journals outside the temporary EXE bundle.
- 修复 YES/NO 漏确认、历史视口卡住、重复回车及回退投递；支持新的 MCP 单次 Allow
  表单，保留英文/自定义续接、托盘和 EXE 功能。

### Changed / 调整

- Merge the installed capacity/HTTP 503 recovery policy: fresh persistent errors
  retry at the common three-second semantic interval until processing readback.
  Other errors retain their successful one-shot latch. The former account-pool
  five-second setting is superseded by `CODEX_AUTO_CONFIRM_SEMANTIC_RETRY_SECONDS`.
- Add an atomic two-second health heartbeat, ten-second stall reporting and
  reader-only recovery capped at two refreshes per episode with a global
  30-second cooldown. Input budgets and Python trackers are never reset by it.
- 明确区分投递与接受；记录健康摘要和本地轮转诊断原文。容量不足及 HTTP 503 统一使用
  默认三秒重试间隔，Working、队列、草稿、近期输入和主动中断继续阻止自动输入。

### Verification / 验收

- Windows unit/integration regressions cover the public packaging and language
  seams. Prior isolated real-terminal receiver tests observed 12/12 main Enter,
  3/3 fallback, 3/3 continuation and 3/3 MCP-form receipts, with one CR each.
  These are bounded fixture results; no real overnight soak is claimed.

[1.3.3]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.3.3

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.2] - 2026-10-21

### Fixed / 修复

- Keep successful command-approval posts pending until authoritative UIA
  readback. A still-visible complete command menu can retry after at least two
  seconds and two fresh safe observations, with a total three-post budget.
- Missing/partial reads, drafting, typing and ambiguous panes interrupt retry
  evidence. Historical request redraws cannot falsely acknowledge a newer menu.
- Label input posts as awaiting menu readback in the monitor log.
- 修复“按键入队成功但审批未通过”后永久停住的问题：同一完整命令菜单经两次读回仍存在才有限补发，
  至少间隔两秒、每请求总投递最多三次；不改变错误续接的“继续”策略。

[1.3.2]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.3.2

## [1.3.1] - 2026-10-21

### Fixed / 修复

- Recognize Working labels, spinners and durations split across UIA ranges
  with intervening blank lines; stop capacity continuation retries while busy.
- Confirm consecutive distinct command requests even when UIA misses the
  intervening clear. Preserve each request's delivery latch and failure budget.
- Treat empty/partial menu reads as unknown. Missing command bodies or changing
  metadata cannot reauthorize an already delivered approval.
- 修复 Working 拆行夹空行时误续接、连续不同命令漏确认，以及残缺菜单读回引发重复确认。

[1.3.1]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.3.1

## [1.3.0] - 2026-10-21

### Fixed / 修复

- Protect unfinished and multiline drafts, quoted errors, recent physical input,
  and windows exposing an ambiguous pane target.
- Latch a successful approval delivery until authoritative clear; keep Working /
  Compacting barriers through redraws and incomplete UIA reads.
- Initialize hidden PowerShell UIA pipes as UTF-8, isolate reader generations,
  bound desktop CDP reads, and deliver text plus Enter to one resolved InputSite.
- Detect dead worker/listener threads in console and tray modes, honor hidden
  supervisor restart delays, and fix source-mode Windows startup to launch the monitor.
- 修复草稿误提交、审批重复发送、Working 状态重绘误触发、隐藏进程编码和重启延迟；
  多窗格目标不明确时暂停输入，并修复托盘健康检查及源码开机启动入口。

### Changed / 调整

- Merge the October 21 watchdog and its regression suites. Persistent model
  capacity warnings retry every 3 seconds until Working/Compacting readback;
  explicit account-pool `auth_unavailable` 503 retries remain at 5 seconds,
  including across reconnecting states. Other errors remain one-shot per episode.
- Preserve tray, logging, autostart, EXE resources, language selection and the
  recovery text override. The default Chinese recovery message is now `继续！`
  so automatic activations can be recognized; English remains `continue`.
- 合入 10 月 21 日稳定性修复：容量不足每 3 秒重试，账号池 503 保持每 5 秒重试；
  主动中断阻止重试，新的 Working/Compacting 状态确认恢复。中文自动续接改为 `继续！`。

[1.3.0]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.3.0

## [1.2.0] - 2026-10-12

### Fixed / 修复
- Prevented repeated continuation messages when successful input delivery is
  followed by delayed UIA status readback.
- 修复成功发送后 UIA 状态读取延迟导致“继续执行”连续排队发送的问题。

### Added / 新增
- Retry explicit account-pool `auth_unavailable` 503 errors every five seconds
  until an authoritative working or compacting status appears.
- 对明确的账号池 `auth_unavailable` 503 错误每五秒重试，直至出现权威的工作中
  或上下文压缩状态。
- Added a bilingual project overview and recovery-policy explanation.
- 增加中英双语项目简介与恢复策略说明。

[1.2.0]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.2.0

## [1.1.0] - 2026-10-07

### Added
- **File logging**: stdout/stderr are now teed to
  `%APPDATA%\codex-auto-confirm\watchdog.log`; the tray menu has a new
  "Open log folder" item.
- **`--version` flag** on the command line.
- **`scripts/uninstall.bat`**: removes the autostart registry entry and
  kills any running EXE.
- **GitHub issue templates** for bug reports and feature requests.
- **`ruff` lint** now runs in CI; rules are configured in `pyproject.toml`.
- **Automatic release workflow**: pushing a `v*` tag builds the EXE on
  `windows-latest` and attaches it to the GitHub release.

### Docs
- README: new Troubleshooting and Uninstall sections.

[1.1.0]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.1.0

## [1.0.0] - 2026-10-07

### Added
- **Background, focus-safe watchdog for OpenAI Codex CLI on Windows.**
  Watches every Windows Terminal / ConPTY window that hosts Codex and presses
  <kbd>Enter</kbd> without ever calling `SetForegroundWindow`, `SetFocus`, or
  global `SendInput`.
- **One-shot approval auto-confirm** for inline TUI menus
  (`Yes, proceed` / `Yes, just this once`) — the author-tested primary path.
- **Error self-recovery**: on a visible `429` / `5xx` / model-capacity /
  stream-disconnect error, posts a "continue" command + <kbd>Enter</kbd>, then
  waits for an authoritative `Working (… • esc to interrupt)` or
  `Compacting context (…)` status before re-arming.
- **Multi-language recovery text**: the monitor detects whether the terminal UI
  is Chinese (sends `继续执行`) or English (sends `continue`). Override with
  `CODEX_AUTO_CONFIRM_RECOVERY_TEXT`.
- **System-tray app** (`--tray`, default for the packaged EXE): green/grey icon
  shows ON/OFF; right-click toggles auto-confirm, toggles Windows startup,
  exits cleanly.
- **Windows startup toggle** in the tray menu (writes `HKCU\...\Run`).
- **Single-instance guard** via a named Windows mutex.
- **Supervised `.bat` launcher** that restarts the Python monitor after a crash
  but respects a clean <kbd>F10</kbd> exit.
- **PyInstaller-packaged `codex-auto-confirm.exe`** — double-click, no Python
  install needed.
- 104 unit tests covering detection, guards, recovery state machine, and the
  new language picker.

### Notes
- Verified end-to-end on Windows Terminal + `codex-cli` 0.156.x.
- The CDP path aimed at the Codex Desktop "Allow once" dialog is included but
  **not author-tested**; treat it as experimental.

[1.0.0]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.0.0
