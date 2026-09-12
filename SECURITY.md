# Security Policy

## Reporting security issues

Do not publish Telegram API credentials, session files, phone numbers, private chat data, media, or exploit details in a public issue.

Report sensitive findings privately to the repository owner with:

- affected version or commit
- reproduction steps
- security impact
- relevant logs with secrets removed
- suggested mitigation, if known

## Sensitive files

The following must remain private and must never be committed:

- `config_v10.json`
- `apex_session.session`
- Telegram API ID / API hash
- exported authentication/session material

Treat a leaked Telegram session as a compromised credential. Revoke affected sessions from Telegram's device settings and regenerate API credentials if needed.

## Local application boundary

Telegram APEX is intended to operate against the user's own authorized Telegram account and content. It must not be used to bypass authentication, access private data without authorization, or collect data from accounts/chats the user is not permitted to access.

## Dependency and release hygiene

Keep Telethon, Flask, Electron/PyInstaller tooling and other dependencies current, verify downloaded third-party binaries/models before use, and avoid distributing builds that contain local configuration or session state.
