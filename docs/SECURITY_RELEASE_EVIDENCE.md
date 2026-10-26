# Security release evidence and review gates

**Scope:** TelegramAPEX-repo draft PR #5, assessed 26 October 2026. These are candidate code changes, not an authorized merge or deployment.

## Automated checks and defended boundaries

- Electron 44.9.1 and Electron Builder 26.18.0; committed deterministic npm lockfile.
- `requirements-electron-build.txt` pins the complete Python Windows backend dependency set from a successful packaging run; `pip check` and an additional `pip-audit` job guard the build.
- New read-only-permission PR workflow produces a complete PyInstaller backend EXE bundled in the Electron Windows installer; tested separately from release publishing.
- Electron renderer has sandbox/context isolation and no Node integration; loopback origin/navigation, Python media path and authorization checks remain in CI.
- CI artifact is available for review but is not a signed, production-released installer.

**CI evidence:** https://github.com/teldigi5-wq/TelegramAPEX-repo/actions/runs/40272477664

To verify that the scan remains valid, use the latest PR-head workflow result; older CI links are historical evidence only. Zero findings from a dependency scan do **not** establish absence of application or infrastructure vulnerabilities.

## Mandatory manual and release checks

- [ ] Run installer on clean Windows 11 with no developer environment; verify Python backend startup and graceful exit.
- [ ] Test authorized Telegram login on a dedicated test account, logout, local HTTP protection, download pagination, media file paths and session deletion.
- [ ] Review native file/SQLite permissions, secrets not entering logs, CSRF/origin defense and malicious path handling.
- [ ] Sign final Windows installer and verify it on a second machine; check rollback.
- [ ] Perform GitHub security-alert and peer architecture review before merge.

## Release decision standard

- Keep the PR draft until required checks on its **exact latest commit** pass.
- Inspect the changed-file diff, ensure `main` is not overwritten, and require an approving reviewer.
- Never push API keys, account credentials, WhatsApp/Telegram session files or production customer data to a test log.
- Sign and publish only after owner approval, preserve reproducible artifacts and a rollback point.
- Label all claims precisely: **CI passed**, **packaged successfully**, **manual test performed**, or **not yet verified**. Never substitute one for another.
