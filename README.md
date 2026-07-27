# Telegram APEX v10 ULTRA

A local, self-hosted media browser & bulk downloader for **your own Telegram account**.
It runs a small web UI on your machine (via Flask + Telethon) so you can browse your chats,
preview media, and download photos/videos/audio/documents in parallel — fast.

> Runs against the **official Telegram API** using your own API credentials and your own
> logged-in session. This is a personal tool for backing up / bulk-downloading media from
> chats you're already a member of — not a scraper for other people's private data.

## ✨ Features

- Browse all your Telegram chats/channels and their media in a fast local web UI
- **Downloads tab** — a dedicated view showing active downloads (live progress), how many are queued, and a session history of completed downloads, separate from the media browser
- **Proper tab navigation** — Media / Downloads / Stats / Settings, replacing the old icon-toggle buttons
- **★ Favorites** — star any media item to save it, with a dedicated Favorites filter; persists across restarts
- **Stats tab** — session totals, a live speed graph, and a media-type breakdown, in a full dashboard view
- Media search box now actually works (was silently broken - called a function that didn't exist)
- **Concurrent downloads** — several files at once (configurable), not one-at-a-time
- Adaptive chunked + parallel-segment downloading for large files, chunk size scales up to 8MB on sustained fast links
- **"5G Ultra" preset** — 8 connections / 8 concurrent files, tuned for high-bandwidth mobile or fiber connections (plus the original Turbo/Balanced/Safe presets)
- Downloads are verified for completeness (size-checked) **and structural integrity** (ffprobe-checked, catches a same-size-but-corrupt file from a segment-boundary mismatch in parallel downloads) before being marked done, with automatic retry on failure
- Thumbnails now generate locally via ffmpeg for already-downloaded videos whose Telegram-side thumbnail is missing, instead of showing nothing
- **"Upscale to 4K"** on any completed video (Downloads tab) — resizes to 3840×2160 via FFmpeg/Lanczos, GPU-accelerated (NVENC/QuickSync/AMF) when available. This sharpens/smooths but does **not** add AI-generated detail; requires [ffmpeg](https://ffmpeg.org/download.html) installed and on your PATH
- **"AI Upscale"** — a slower, heavier alternative that adds real detail via [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) (GPU-accelerated, frame-by-frame). Optional manual setup — see below
- Working video/audio preview — plays the actual file (streamed live from Telegram if not downloaded yet, with seek support) instead of failing silently
- **🔄 Refresh button** on the media view to force a clean reload if a chat's media doesn't show up
- **Load more** pagination fixed to correctly fetch older media instead of re-fetching the same page, with a loading state and running item count
- Lazy-loaded thumbnails (only fetch thumbnails for cards actually scrolled into view) — noticeably faster on large chats
- Thumbnails no longer fall back to downloading entire videos/documents just to generate a preview
- Live per-file progress rows, aggregate speed graph, ETA
- Pause / Resume the whole queue, cancel individual files or cancel all
- Optional bandwidth cap (KB/s), fairly divided across concurrent downloads
- **Auto-download new incoming media** as it arrives (opt-in)
- Session download history → export to CSV
- Checks GitHub Releases for newer versions on startup
- Ships as a single portable `.exe`, **or** as a proper Windows desktop installer via Electron (see below) — no Python required on the machine you run it on either way

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

## 🖥️ Building the Electron desktop app (no console window, proper installer)

The plain `.exe` above is a console app — a black terminal window sits behind the UI. The
`electron/` folder wraps the same Python backend in a real desktop shell: no console window,
a taskbar/Start Menu entry, a proper `Setup.exe` installer, and desktop/Start Menu shortcuts.

**How it works:** Electron spawns the Python backend as a hidden background process
(`windowsHide: true`, unbuffered stdout so it starts fast and reliably), waits for it to
report ready, then opens a native window pointed at its local web UI. Closing the window
stops the backend automatically.

**Build it locally — one command:**
```
BUILD_ELECTRON.bat
```
This builds the Python backend with PyInstaller, stages it into `electron/backend/`, then
runs Electron Builder to produce `electron/release/Telegram APEX Setup <version>.exe` — a
double-click installer for end users, with no Python and no visible console window.

**Build it via GitHub Actions:** the included `.github/workflows/build-electron.yml` does the
same thing on a clean Windows runner and attaches the installer to your GitHub Release,
alongside the plain exe. Trigger it the same way — publish a release, or run it manually from
the Actions tab.

**Developing/testing without building an installer:**
```bash
cd electron
npm install
npm start
```
This runs the backend via `python TelegramAPEX_v9.py` directly (no PyInstaller step) inside
an Electron window — fast to iterate on.

## 🧠 AI Upscale setup (optional)

The fast "Upscale to 4K" button works out of the box (just needs ffmpeg). The **AI Upscale**
button needs one extra one-time download, since it's a ~70MB third-party binary + model that
isn't bundled with this repo:

1. Download the Windows build from the official releases page:
   **https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases**
   (grab the asset with "windows" in its name, e.g. `realesrgan-ncnn-vulkan-*-windows.zip`)
2. Extract the zip.
3. Create this folder next to `TelegramAPEX_v9.py` (or next to the built `.exe`):
   `tools\realesrgan\`
4. Copy everything from the extracted zip into that folder, so you end up with:
   ```
   tools\realesrgan\realesrgan-ncnn-vulkan.exe
   tools\realesrgan\models\  (folder with the .bin/.param model files)
   ```
5. Restart the app. The Downloads tab will detect it automatically — no config needed.

That's it — no separate install, no PATH changes. If you'd rather install it system-wide
instead, putting `realesrgan-ncnn-vulkan.exe` anywhere on your PATH also works.

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
