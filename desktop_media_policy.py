"""Parse bounded Telegram media pagination without importing the desktop backend.

The backend uses page size 50. Reject huge/non-numeric values before scheduling
Telegram requests and allocating results in the local desktop service.
"""

MAX_MEDIA_PAGE = 100
MAX_TELEGRAM_MESSAGE_ID = (1 << 63) - 1


def parse_media_page(limit_raw: str = "50", before_raw: str = "0") -> tuple[int, int]:
    try:
        # Only canonical ASCII decimal digits. No signs, floats or unbounded integers.
        if not (isinstance(limit_raw, str) and limit_raw.isascii()
                and limit_raw.isdecimal() and len(limit_raw) <= 3):
            raise ValueError("invalid media page limit")
        if not (isinstance(before_raw, str) and before_raw.isascii()
                and before_raw.isdecimal() and len(before_raw) <= 19):
            raise ValueError("invalid media page cursor")
        limit, before_id = int(limit_raw), int(before_raw)
        if not (1 <= limit <= MAX_MEDIA_PAGE and 0 <= before_id <= MAX_TELEGRAM_MESSAGE_ID):
            raise ValueError("media page outside accepted range")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Invalid media pagination parameters") from error
    return limit, before_id
