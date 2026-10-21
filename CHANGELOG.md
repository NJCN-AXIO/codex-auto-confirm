# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
