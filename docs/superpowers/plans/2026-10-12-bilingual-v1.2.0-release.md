# Bilingual GitHub Page and v1.2.0 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the public project entry point in English and Chinese, synchronize v1.2.0 metadata, and publish the GitHub Release with its generated Windows EXE.

**Architecture:** Reuse the existing README, changelog, version constants, GitHub repository metadata, and tag-triggered `.github/workflows/release.yml`. No runtime behavior or release workflow changes are needed; the implementation documents and publishes behavior already present on `main`.

**Tech Stack:** Markdown, TOML, Python, Git, GitHub CLI, GitHub Actions, pytest, Ruff.

## Global Constraints

- Keep the README's existing English manual; add a concise Chinese summary and bilingual wording only for the project overview and recovery policy.
- State that only an explicit account-pool `auth_unavailable` 503 is retried every 5 seconds after successful delivery; ordinary transient errors are not resent merely because UIA readback is delayed.
- Stop account-pool retries only after a fresh authoritative `Working (duration • esc to interrupt)` or `Compacting context (duration • esc to interrupt)` status (or existing clear/off-state handling).
- Keep Codex Desktop CDP behavior marked experimental and author-untested.
- Set `pyproject.toml` and `scripts/codex_auto_confirm.py` to version `1.2.0` and document the same release in `CHANGELOG.md`.
- Publish only after the full test suite and Ruff pass; verify the remote release asset after Actions completes.

---

### Task 1: Add bilingual project copy and align v1.2.0 metadata

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml:7`
- Modify: `scripts/codex_auto_confirm.py:12`
- Test: `scripts/test_codex_auto_confirm_recovery.py` (existing recovery regression suite; no runtime code changes expected)

**Interfaces:**
- Consumes: Existing retry semantics documented in `docs/RUNBOOK.md` and tested in `scripts/test_codex_auto_confirm_recovery.py`.
- Produces: Matching bilingual overview copy and a consistent 1.2.0 version across package metadata, `--version`, and changelog.

- [ ] **Step 1: Add matching English/Chinese overview and recovery copy to README**

Keep the existing English intro, but add this concise bilingual block near the top, before the Features section:

```markdown
### Quick summary / 快速了解

**English:** A Windows watchdog for OpenAI Codex CLI that safely auto-confirms one-shot prompts and recovers transient errors without stealing focus. Ordinary transient errors are continued once after successful delivery; an explicit account-pool `auth_unavailable` 503 is retried every 5 seconds until a fresh authoritative `Working (duration • esc to interrupt)` or `Compacting context (duration • esc to interrupt)` status appears.

**中文：** Windows 下的 OpenAI Codex CLI 守护工具，可在不抢占焦点的情况下自动确认一次性授权并恢复瞬时错误。普通瞬时错误成功发送一次“继续执行”后会等待状态确认；明确的账号池 `auth_unavailable` 503 则每 5 秒重试，直到检测到新的权威状态 `Working (duration • esc to interrupt)` 或 `Compacting context (duration • esc to interrupt)`。
```

Do not claim that every HTTP 503 is retried. Leave the existing Desktop CDP experimental warning intact.

- [ ] **Step 2: Add the v1.2.0 changelog entry and synchronize version sources**

Set `version = "1.2.0"` in `pyproject.toml` and `__version__ = "1.2.0"` in `scripts/codex_auto_confirm.py`. Add a newest-first entry to `CHANGELOG.md` dated `2026-10-12` with these bilingual changes:

```markdown
## [1.2.0] - 2026-10-12

### Fixed / 修复
- Prevented repeated continuation messages when a successful input delivery is followed by delayed UIA status readback.
- 修复成功发送后 UIA 状态读取延迟导致“继续执行”连续排队发送的问题。

### Added / 新增
- Retry explicit account-pool `auth_unavailable` 503 errors every five seconds until an authoritative working or compacting status appears.
- 对明确的账号池 `auth_unavailable` 503 错误每五秒重试，直至出现权威的工作中或上下文压缩状态。
- Added a bilingual project overview and recovery-policy explanation.
- 增加中英双语项目简介与恢复策略说明。

[1.2.0]: https://github.com/NJCN-AXIO/codex-auto-confirm/releases/tag/v1.2.0
```

Retain the existing 1.1.0 entry and link beneath it.

- [ ] **Step 3: Run the project's established tests and lint checks**

Run from the repository root:

```powershell
python -m pytest scripts/ -q
ruff check scripts/
python scripts/codex_auto_confirm.py --version
```

Expected: pytest passes, Ruff exits 0, and the version command prints `codex-auto-confirm 1.2.0`.

- [ ] **Step 4: Review and commit the release content**

Run `git diff --check`, inspect `git diff`, then stage only the four files listed in this task and commit:

```powershell
git add README.md CHANGELOG.md pyproject.toml scripts/codex_auto_confirm.py
git commit -m "release: prepare v1.2.0 bilingual update"
```

Expected: a clean diff check and one commit containing only README, changelog, and the two synchronized version files.

---

### Task 2: Update GitHub About and publish the tagged release

**Files:**
- External metadata: GitHub repository `NJCN-AXIO/codex-auto-confirm` description
- Remote refs: `origin/main`, tag `v1.2.0`
- Produced artifact: GitHub Release asset `codex-auto-confirm.exe`

**Interfaces:**
- Consumes: The tested v1.2.0 release commit from Task 1 and the existing `.github/workflows/release.yml` tag trigger.
- Produces: A bilingual GitHub About description, pushed `main`, v1.2.0 Release, and verified EXE asset.

- [ ] **Step 1: Update GitHub About with a concise bilingual description**

Use this exact description (keep it below GitHub's description limit):

```text
Windows Codex CLI watchdog: safely auto-confirms one-shot prompts and recovers transient errors without stealing focus. Retries account-pool auth_unavailable 503 every 5 seconds until authoritative Working/Compacting. | Windows 下的 Codex CLI 守护工具：安全自动确认一次性授权、恢复瞬时错误且不抢占焦点；账号池 auth_unavailable 503 每 5 秒重试，直到权威的 Working/上下文压缩状态。
```

Run:

```powershell
gh repo edit NJCN-AXIO/codex-auto-confirm --description 'Windows Codex CLI watchdog: safely auto-confirms one-shot prompts and recovers transient errors without stealing focus. Retries account-pool auth_unavailable 503 every 5 seconds until authoritative Working/Compacting. | Windows 下的 Codex CLI 守护工具：安全自动确认一次性授权、恢复瞬时错误且不抢占焦点；账号池 auth_unavailable 503 每 5 秒重试，直到权威的 Working/上下文压缩状态。'
gh repo view NJCN-AXIO/codex-auto-confirm --json description
```

Expected: the readback exactly matches the bilingual copy above.

- [ ] **Step 2: Check remote state and push the reviewed main branch**

Run `git status --short --branch`, `git log -3 --oneline --decorate`, and `git ls-remote --heads origin main`. Confirm the working tree is clean and no unrelated remote commit would be overwritten. Then run:

```powershell
git push origin main
```

Expected: `origin/main` points to the release commit.

- [ ] **Step 3: Verify the tag is absent, then push v1.2.0**

Run `git ls-remote --tags origin v1.2.0`. If it returns an existing tag, stop and inspect it rather than moving it. If absent, run:

```powershell
git tag v1.2.0
git push origin v1.2.0
```

Expected: the remote tag resolves to the same commit as the reviewed `main` release commit; the existing Release workflow starts from this tag.

- [ ] **Step 4: Verify the Actions run and Release asset**

Use:

```powershell
gh run list --repo NJCN-AXIO/codex-auto-confirm --workflow Release --limit 5
gh release view v1.2.0 --repo NJCN-AXIO/codex-auto-confirm --json tagName,url,assets
```

Wait for the run to finish if it is still in progress, then re-read the release. Expected: the v1.2.0 release exists, its tag points to the intended commit, the workflow succeeded, and its assets include `codex-auto-confirm.exe`.
