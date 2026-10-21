"""Browser-origin boundary for a loopback-only desktop API (no third-party deps)."""
from urllib.parse import urlsplit

_ALLOWED_HOSTS = frozenset(("127.0.0.1", "localhost", "::1"))

def permitted_desktop_request(host: str, origin: str | None, fetch_site: str | None) -> bool:
    """Reject cross-origin browser traffic and DNS-rebinding Host headers.

    Requests from local CLI tools without browser headers are permitted for
    diagnostics; this is an origin/CSRF protection, NOT a machine-level login.
    """
    try:
        authority = urlsplit("http://" + (host or ""))
        if authority.hostname not in _ALLOWED_HOSTS or authority.username or authority.password:
            return False
        if authority.path not in ("", "/") or authority.query or authority.fragment:
            return False
        if authority.port is not None and not (1 <= authority.port <= 65535):
            return False
        # Exact origin matching, including the port, to prevent localhost/127 alias
        # origins from being used as an untrusted cross-origin bridge.
        if origin is not None:
            ref = urlsplit(origin)
            if ref.scheme != "http" or ref.netloc != host or ref.path or ref.query or ref.fragment:
                return False
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            return False
        return True
    except (ValueError, TypeError):
        return False
