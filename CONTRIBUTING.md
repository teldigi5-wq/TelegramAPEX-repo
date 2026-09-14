# Contributing to Telegram APEX

Thanks for your interest in improving Telegram APEX.

This project combines a Python backend, a local Flask web UI, Telegram API integration, media-processing tooling, and Windows packaging. Contributions should preserve reliability, privacy, and clear feature boundaries.

## Before changing code

1. Keep credentials, session files, downloaded media, and local config out of commits.
2. Do not add features that bypass Telegram access controls, DRM, or user permissions.
3. Prefer small, focused changes that are easy to review and test.
4. Document behavior that affects downloads, session handling, packaging, or media processing.

## Development workflow

1. Create a branch for the change.
2. Run the application locally and verify the affected flow.
3. If Python code changes, run a syntax check before committing.
4. If Electron code changes, verify the desktop wrapper starts and closes the backend cleanly.
5. If packaging changes, validate the related GitHub Actions workflow or local build path.

## Pull requests

A good pull request should explain:

- what problem is being solved;
- what changed;
- how the change was tested;
- whether it affects credentials, sessions, downloads, media integrity, or packaging;
- any rollback or compatibility concerns.

## Commit style

Use concise conventional-style messages when practical:

- `feat:` new capability
- `fix:` bug fix
- `docs:` documentation
- `refactor:` internal code improvement
- `test:` test or validation work
- `ci:` GitHub Actions / build pipeline
- `chore:` maintenance

## Security

Never commit Telegram API credentials, live session files, secrets, tokens, downloaded private media, or machine-specific sensitive data. Follow `SECURITY.md` for reporting security issues.
