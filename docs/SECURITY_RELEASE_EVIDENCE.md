# Security release evidence and review gates

**Scope:** TelegramAPEX-repo merged security-remediation PR #5, assessed 26 October 2026. Security fixes are merged into main; this does not itself deploy the service or certify released binaries.

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

- For future security changes, require passing checks on the **exact PR head commit** before merging.
- Inspect future diffs and require human review; these merged PRs passed automated CI, but this report is not an independent security assessment.
- Never push API keys, account credentials, WhatsApp/Telegram session files or production customer data to a test log.
- Sign and publish only after owner approval, preserve reproducible artifacts and a rollback point.
- Label all claims precisely: **CI passed**, **packaged successfully**, **manual test performed**, or **not yet verified**. Never substitute one for another.
