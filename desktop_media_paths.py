"""Path confinement for Telegram-provided filenames and media previews.

Telegram filenames and query-string media names are untrusted. Stored file paths
must remain below the configured download root even across symlinks.
"""
import os
import re

MEDIA_SUBFOLDERS = frozenset({"videos", "photos", "audios", "docs", "thumbs"})
_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def safe_media_filename(raw: str, fallback: str = "telegram_media.bin") -> str:
    """Create a cross-platform flat filename, preserving a safe extension."""
    if not isinstance(raw, str):
        return fallback
    basename = raw.replace("\\", "/").split("/")[-1]
    basename = _UNSAFE.sub("_", basename).strip(" .")
    if not basename or basename in {".", ".."}:
        return fallback
    if _RESERVED.match(basename):
        basename = "_" + basename
    # Avoid platform filename/path limits and large attacker-controlled values.
    if len(basename) > 180:
        stem, ext = os.path.splitext(basename)
        basename = stem[:max(1, 180 - len(ext))] + ext[:16]
    return basename


def is_in_download_tree(download_root: str, candidate: str) -> bool:
    """Reject symlink escapes and paths outside the configured download directory."""
    try:
        root = os.path.realpath(download_root)
        target = os.path.realpath(candidate)
        return os.path.commonpath((root, target)) == root
    except (OSError, ValueError, TypeError):
        return False


def contained_media_path(download_root: str, subfolder: str, raw_name: str) -> str:
    if subfolder not in MEDIA_SUBFOLDERS:
        raise ValueError("Unsupported Telegram media folder")
    safe_name = safe_media_filename(raw_name)
    candidate = os.path.join(download_root, subfolder, safe_name)
    if not is_in_download_tree(download_root, candidate):
        raise ValueError("Media file escapes configured download directory")
    return candidate
