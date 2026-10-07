# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
