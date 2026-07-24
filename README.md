# Telegram APEX v10 ULTRA

A local, self-hosted media browser & bulk downloader for **your own Telegram account**.
It runs a small web UI on your machine (via Flask + Telethon) so you can browse your chats,
preview media, and download photos/videos/audio/documents in parallel — fast.

> Runs against the **official Telegram API** using your own API credentials and your own
> logged-in session. This is a personal tool for backing up / bulk-downloading media from
> chats you're already a member of — not a scraper for other people's private data.

## ✨ Features

- Browse all your Telegram chats/channels and their media in a fast local web UI
- **Concurrent downloads** — several files at once (configurable), not one-at-a-time
- Adaptive chunked + parallel-segment downloading for large files, chunk size scales up to 8MB on sustained fast links
- **"5G Ultra" preset** — 8 connections / 8 concurrent files, tuned for high-bandwidth mobile or fiber connections (plus the original Turbo/Balanced/Safe presets)
- **Load more** pagination fixed to correctly fetch older media instead of re-fetching the same page
- Lazy-loaded thumbnails (only fetch thumbnails for cards actually scrolled into view) — noticeably faster on large chats
- Thumbnails no longer fall back to downloading entire videos/documents just to generate a preview
- Live per-file progress rows, aggregate speed graph, ETA
- Pause / Resume the whole queue, cancel individual files or cancel all
- Optional bandwidth cap (KB/s), fairly divided across concurrent downloads
- **Auto-download new incoming media** as it arrives (opt-in)
- Session download history → export to CSV
- Checks GitHub Releases for newer versions on startup
- Ships as a single portable `.exe` — no Python required on the machine you run it on

## 🚀 Quick start (from source)

1. Install [Python 3.10+](https://python.org) (3.12 recommended).
2. Get your API ID & Hash from <https://my.telegram.org/apps>.
3. Copy `config_v10.example.json` → `config_v10.json` and fill in your `api_id` / `api_hash`
   — **or** just leave it blank and enter them in the Settings dialog the first time you run it.
4. Double-click `LAUNCH.bat` (Windows). It installs missing packages automatically and starts
   the app, opening your browser to the local UI.

## 📦 Building the standalone EXE

**Locally:** double-click `BUILD_EXE.bat`. It installs PyInstaller if needed and produces
`TelegramAPEX_v10.exe` in this folder — no Python required to run that exe elsewhere.

**Via GitHub (recommended):** this repo includes a GitHub Actions workflow
(`.github/workflows/build.yml`) that builds the exe on a clean Windows runner and attaches it
to a GitHub Release automatically. To use it:

1. Push this repo to GitHub.
2. Go to **Releases → Draft a new release**, tag it (e.g. `v10.1.0`), and publish it.
3. Actions will build `TelegramAPEX_v10.exe` and attach it to the release within a few minutes.
4. (Optional) Update the `GITHUB_REPO` constant near the top of `TelegramAPEX_v9.py` to
   `"your-username/your-repo"` so the in-app update checker can find your releases.

You can also trigger a build manually any time from the **Actions** tab
("Build Windows EXE" → *Run workflow*), without publishing a release.

## 🔒 Security — read this before pushing to GitHub

This app stores two sensitive files **next to itself**, both already excluded via
`.gitignore` — do not remove them from `.gitignore` and do not commit these:

- `config_v10.json` — contains your Telegram **API ID and Hash**
- `apex_session.session` — your **live, logged-in Telegram session**. Anyone who gets this
  file can access your Telegram account without your password or 2FA. Treat it like a
  password, never upload it anywhere (including to an AI tool, a support forum, or a public
  repo).

If either file has ever been shared outside your machine, revoke it:
- Regenerate your API credentials at <https://my.telegram.org/apps>, or
- Log out the affected session from **Telegram → Settings → Devices**.

## ⚙️ Settings reference

| Setting | Description |
|---|---|
| Preset (5G Ultra/Turbo/Balanced/Safe) | Baseline connection count & concurrency. Use 5G Ultra on fast mobile/fiber connections. |
| Max Simultaneous Downloads | Overrides the preset's concurrency (0 = use preset) |
| Bandwidth Cap | KB/s, shared fairly across all concurrent downloads (0 = unlimited) |
| Auto-download new incoming media | Watches for new messages and queues matching media automatically |

## 🛠 Tech

Python · [Telethon](https://docs.telethon.dev) (Telegram MTProto client) · Flask (local web
server) · vanilla JS/CSS frontend · PyInstaller (packaging)

## License

MIT — see [LICENSE](LICENSE). For personal use with your own Telegram account and content
you have the right to download. You're responsible for complying with Telegram's
[Terms of Service](https://telegram.org/tos) and applicable law in how you use this tool.
