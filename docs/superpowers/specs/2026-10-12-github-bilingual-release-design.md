# GitHub Bilingual Project Page and v1.2.0 Release Design

## Context

The repository's `main` branch contains the account-pool `auth_unavailable`
503 recovery change, but the latest GitHub Release is still v1.1.0. The current
release workflow builds and attaches the Windows EXE only when a `v*` tag is
pushed. The GitHub About description does not explain the new retry behavior,
and the script/package versions and changelog have not yet been advanced from
their earlier values.

## Goals

- Make the GitHub repository entry point understandable in both English and
  Chinese without translating the full existing manual.
- Clearly distinguish the repeated retry policy for account-pool
  `auth_unavailable` 503 errors from the one-shot recovery policy for other
  transient errors.
- Publish the already-implemented changes as v1.2.0 and let the existing
  tagged-release workflow build the EXE.

## Decisions

Use a focused bilingual update rather than a full README translation or an
About-only change:

1. Update the GitHub About description with concise English and Chinese copy.
2. Add a Chinese summary near the top of `README.md`; pair the key feature and
   recovery-policy explanation in English and Chinese. Keep the remainder of
   the existing English manual intact.
3. Keep Codex Desktop's CDP path explicitly marked experimental and
   author-untested; do not imply it has the same verification level as the
   Windows Terminal CLI path.
4. Synchronize the package version in `pyproject.toml`, runtime `--version`
   in `scripts/codex_auto_confirm.py`, and `CHANGELOG.md` at 1.2.0. Release
   notes will describe the duplicate-send guard and the special account-pool
   503 retry policy in both languages.
5. Push the reviewed `main` commit and a `v1.2.0` tag. Verify the resulting
   GitHub Release and EXE asset rather than treating the tag push as proof of
   successful publication.

## Recovery wording and safety boundaries

For ordinary recognized transient errors, the monitor sends one continuation
per error occurrence after successful input delivery, then waits for a fresh,
authoritative `Working` or `Compacting context` status. It must not queue
repeated messages solely because UI Automation readback is delayed.

For an explicit account-pool `auth_unavailable` 503, the monitor retries the
continuation at the configured interval (default five seconds) until a fresh,
authoritative `Working` or `Compacting context` status appears. The
documentation must not suggest that all HTTP 503 responses receive this
repeated-retry treatment.

No focus-stealing or broader automation behavior is introduced by this
documentation/release update. Approval remains limited to one-shot prompts;
the Desktop CDP route remains experimental.

## Validation and acceptance criteria

- The About description and README summary present matching bilingual claims.
- The special 503 policy is described with its five-second default and
  authoritative stopping condition; other transient failures remain described
  as one successful send per occurrence.
- Both version sources and the latest changelog entry say 1.2.0.
- The test suite and Ruff pass before publishing.
- GitHub Actions completes for `v1.2.0`, and the Release page contains the
  generated `codex-auto-confirm.exe` asset.
