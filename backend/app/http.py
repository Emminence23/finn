"""Polite HTTP fetching (NFR-11): per-host rate limit, retries, disk cache, NSE cookies."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class RateLimiter:
    """Minimum interval between requests to the same host."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last.get(host, 0.0) + self.min_interval - now
            self._last[host] = max(now, now + delay)
        if delay > 0:
            time.sleep(delay)


class RetryableHTTPError(Exception):
    pass


class Fetcher:
    def __init__(self, cache_dir: Path | None = None, min_interval: float | None = None) -> None:
        s = get_settings()
        self.cache_dir = (cache_dir or s.cache_dir) / "http"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = RateLimiter(
            s.min_seconds_between_requests if min_interval is None else min_interval
        )
        self.client = httpx.Client(headers=DEFAULT_HEADERS, timeout=30, follow_redirects=True)
        self._nse_primed = False

    # -- cache -------------------------------------------------------------
    def _cache_path(self, url: str, params: dict | None) -> Path:
        key = hashlib.sha256(f"{url}|{sorted((params or {}).items())}".encode()).hexdigest()
        return self.cache_dir / key[:2] / key

    # -- core --------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((RetryableHTTPError, httpx.TransportError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get(self, url: str, params: dict | None, headers: dict | None) -> httpx.Response:
        self.limiter.wait(urlparse(url).netloc)
        r = self.client.get(url, params=params, headers=headers)
        if r.status_code in (429, 500, 502, 503, 504):
            raise RetryableHTTPError(f"{r.status_code} for {url}")
        r.raise_for_status()
        return r

    def get_bytes(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        use_cache: bool = True,
    ) -> bytes:
        path = self._cache_path(url, params)
        if use_cache and path.exists():
            return path.read_bytes()
        if "nseindia.com/api" in url:
            self._prime_nse()
        content = self._get(url, params, headers).content
        if use_cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return content

    def get_text(self, url: str, **kw) -> str:
        return self.get_bytes(url, **kw).decode("utf-8", errors="replace")

    def get_json(self, url: str, **kw):
        import json

        return json.loads(self.get_bytes(url, **kw))

    def download(self, url: str, dest: Path) -> Path:
        """Download a file (e.g. a PDF) once; return its local path."""
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.get_bytes(url, use_cache=False))
        return dest

    # -- NSE ---------------------------------------------------------------
    def _prime_nse(self) -> None:
        """NSE's JSON API requires cookies set by a prior homepage visit."""
        if self._nse_primed:
            return
        self.limiter.wait("www.nseindia.com")
        self.client.get("https://www.nseindia.com/")
        self._nse_primed = True


_fetcher: Fetcher | None = None


def get_fetcher() -> Fetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher()
    return _fetcher
