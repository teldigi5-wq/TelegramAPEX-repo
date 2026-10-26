<div align="center">

# Telegram APEX

**Local-first Telegram media manager · Python / Telethon / Flask · Electron desktop shell**

[![CI](https://github.com/teldigi5-wq/TelegramAPEX-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/teldigi5-wq/TelegramAPEX-repo/actions/workflows/ci.yml)
[Source](https://github.com/teldigi5-wq/TelegramAPEX-repo) · [Security policy](SECURITY.md) · [Windows packaging](.github/workflows/electron-pr-packaging.yml) · [Release evidence](docs/SECURITY_RELEASE_EVIDENCE.md)

**Maintained by [Poojana Kaveesh Sellahewa](https://github.com/teldigi5-wq).**

</div>

## What is it?

Telegram APEX is a **local** media-browsing and download application for content accessible through **your own authorized Telegram account**. Python's Telethon client talks to Telegram, Flask serves a loopback-only browser UI, and an optional Electron application launches the backend inside a Windows desktop shell.

The design focuses on efficient media workflows while keeping Telegram credentials, sessions and downloaded content out of a hosted third-party backend.

| Area | Code / technology |
| --- | --- |
| Telegram integration | Python 3.12 CI baseline, Telethon |
| Local application API | Flask, strict loopback-host/origin checks |
| Desktop shell | Electron 44 with sandboxed, context-isolated renderer |
| Downloads | Local filesystem, queue/concurrency and media preview code |
| Packaging | PyInstaller Python executable + electron-builder/NSIS Windows x64 installer |
| Verification | Python unittest, Node security tests, dependency audits, Windows packaging CI |

### Architecture

~~~mermaid
flowchart LR
    User[Authorized account holder] --> App[Local browser / Electron UI]
    App --> Web[Flask HTTP on loopback]
    Web --> Auth[Telethon authenticated session]
    Auth --> TG[Telegram API]
    Web --> Queue[Media queue / previews]
    Queue --> Files[Local download directory]
    Electron[Electron main process] --> Backend[Packaged Python backend]
    Backend --> Web
~~~

The Python service is intended to be accessed from the same machine, not exposed as a public website. Electron launches the backend and opens only its private loopback UI.

## Product workflow

1. Supply personal Telegram API ID and hash from the official Telegram developer console and authorize **your own session**.
2. Browse chats you can access; search, filter and paginate media using the local UI.
3. Download authorized photos, videos and files; inspect progress, queued items and completed output.
4. Optionally use FFmpeg for local thumbnails or rescaling, subject to installed binaries and hardware.
5. Keep private session material and media on your own machine.

**Feature qualification:** The code contains queue, preview, concurrency, search and optional processing paths. CI does **not** demonstrate Telegram login, download success on a real account, peak speeds, structural integrity on arbitrary media, or universal format compatibility. Titles such as “5G Ultra” are UI presets, not benchmark results.

### Video processing is not always AI

Ordinary FFmpeg/Lanczos “4K upscale” **resizes** a video; it does not invent high-frequency detail. A separate optional Real-ESRGAN integration depends on user-provided third-party binaries/models and GPU compatibility. Neither approach promises restoration quality or performance on every file.

## Security and engineering decisions

| Decision | Implementation | How to discuss it |
| --- | --- | --- |
| Allow only local desktop origins | [desktop_origin_policy.py](desktop_origin_policy.py), [tests](tests/test_desktop_origin_policy.py) | Localhost/port matching reduces cross-origin access to the backend |
| Contain output within download folders | [desktop_media_paths.py](desktop_media_paths.py), [path tests](tests/test_media_path_policy.py) | Reject traversal and links escaping the chosen storage tree |
| Separate privileged desktop operations | [electron/main.js](electron/main.js), [navigation policy](electron/navigation-policy.js) | Sandbox and context isolation; Electron page limited to loopback backend |
| Avoid silent dependency drift | [requirements-electron-build.txt](requirements-electron-build.txt), [electron/package-lock.json](electron/package-lock.json) | Pin Python packaging dependencies and npm installation |
| Verify packaging on a clean Windows runner | [PR Windows packaging](.github/workflows/electron-pr-packaging.yml) | Stage PyInstaller backend inside Electron and record installer SHA-256 |

**Traceable security work:** [PR #5](https://github.com/teldigi5-wq/TelegramAPEX-repo/pull/5) upgraded Electron, added pinned dependency audits and successfully exercised an integrated Windows build. Passing these checks is **not** the same as independent penetration testing or a signed production installer.

## Quick start from source

**Requirements:** Windows for the included launch scripts, Python 3.12 recommended, a Telegram account you own and API credentials from [my.telegram.org/apps](https://my.telegram.org/apps). Additional packages are installed by the launch script.

1. Copy **config_v10.example.json** to a local **config_v10.json**.
2. Enter your own API credentials only in that local file or the application's settings flow.
3. Run **LAUNCH.bat** from an authorized local Windows machine.

~~~bat
copy config_v10.example.json config_v10.json
LAUNCH.bat
~~~

Do not place session data or real API credentials in a public bug report, screen recording or committed file. Do not expose the Flask HTTP port to the internet.

### Virtual tests you can reproduce without Telegram login

~~~bash
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile TelegramAPEX_v9.py desktop_origin_policy.py desktop_media_policy.py desktop_media_paths.py
cd electron
npm ci
npm run security:test
npm audit --audit-level=high
~~~

The latest verified October 26, 2026 **main-branch CI** ran **12 Python tests** and its Electron/Node policy suite on a clean runner; the Windows job verified the Electron executable. [Inspect actual CI history](https://github.com/teldigi5-wq/TelegramAPEX-repo/actions/workflows/ci.yml).

The tests use synthetic paths and requests: they do not log into Telegram, read private chat data or download user media.

## Windows build and distribution

| Method | Entry point / output | Verification scope |
| --- | --- | --- |
| Python EXE | **BUILD_EXE.bat** or [Build Windows EXE](.github/workflows/build.yml) | Produces a standalone backend executable |
| Full desktop installer | **BUILD_ELECTRON.bat** or [Build Electron Installer](.github/workflows/build-electron.yml) | PyInstaller backend bundled with Electron / NSIS |
| Pull request packaging | [PR Windows Installer Integration](.github/workflows/electron-pr-packaging.yml) | Creates installer/checksum artifact for review without publishing a release |

Use the **Actions** tab to inspect generated artifacts. GitHub Release workflows are separate publishing actions; a passing pull-request build **does not mean** the installer has been signed, published or installed successfully on a clean user's Windows PC.

For normal Electron development, install Python requirements for the backend first, then:

~~~bash
cd electron
npm ci
npm start
~~~

### Private session handling

- **config_v10.json** and **apex_session.session** are sensitive; never commit or upload either.
- Telegram session files can act as account access credentials; log out/revoke a leaked session under Telegram device settings.
- Avoid uploading private media or accounts to public CI or issue attachments.
- Report suspected vulnerabilities privately following [SECURITY.md](SECURITY.md).

## Portfolio ownership and technical walkthrough

**Maintainer:** [Poojana Kaveesh Sellahewa](https://github.com/teldigi5-wq). Demonstrable repository work includes local service boundaries, filesystem path tests, Python/Electron packaging and security regression workflows. The [commit history](https://github.com/teldigi5-wq/TelegramAPEX-repo/commits/main) and [PR history](https://github.com/teldigi5-wq/TelegramAPEX-repo/pulls?q=is%3Apr) provide reviewable evidence. In an interview, say which decisions and implementation tasks you carried out yourself, and disclose collaborators or AI/tool assistance where applicable. No claim of sole manual authorship is implied.

**A concise demo:**
1. Show the local Flask → Telethon → local-files architecture, without revealing a personal session.
2. Run the Python path-traversal and loopback-origin tests.
3. Explain the Python backend / Electron wrapper separation and safe shutdown.
4. Show the audited dependency lockfiles and successful PR installer workflow.
5. Describe unverified account-level and Windows-installed-app scenarios transparently.

## Current limitations / next work

- [ ] Record a privacy-safe actual-app screenshot and short demo.
- [ ] Test full login, reconnection, pagination, download cancellation and media integrity on a dedicated account.
- [ ] Exercise native installer/uninstall and PyInstaller backend startup on a clean Windows machine.
- [ ] Add end-to-end tests for local HTTP request paths and error recovery.
- [ ] Sign published Windows builds and document update/rollback behavior.
- [ ] Independently verify model/binary provenance before redistribution.

**Responsible use:** Access only chats and media for which you have permission. Respect Telegram terms, media rights and account privacy. [MIT license](LICENSE).
