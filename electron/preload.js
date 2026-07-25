// Intentionally minimal. The renderer (TelegramAPEX's own HTML/JS) talks to
// its local Python/Flask backend purely over HTTP (fetch + SSE), so no
// contextBridge/IPC surface is required. Kept as a hook for future native
// integrations (e.g. system tray, native notifications).
