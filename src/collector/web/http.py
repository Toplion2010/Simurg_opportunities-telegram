"""Shared HTTP for scraped catalogs.

Two transports, chosen at import time:

  curl_cffi  (preferred, from the `scrape` extra) — presents a browser TLS
             fingerprint. REQUIRED for sirel.org, whose WAF fingerprints the
             handshake rather than the headers: curl gets 200 while httpx and
             urllib both get 403 from the same IP, with the same User-Agent, at
             the same moment. No header combination fixes it; the TLS profile
             is the discriminator.
  httpx      (fallback) — already a base dependency. Fine for
             ExtracurricularHub, which has no such protection.

The fallback is not a nicety: it keeps `pip install -e .` alone enough to
import and unit-test this package, so the test suite never needs a compiled
libcurl. Only webscan.yml installs the extra.

Pacing and retry are a port of hackathon-watcher/sources/http.py, which has
been running against 11 sites in production.
"""
import time

import httpx

from src.core.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - exercised by which extra is installed
    from curl_cffi import requests as curl_requests

    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    curl_requests = None
    HAS_CURL_CFFI = False

# The profile curl_cffi impersonates. chrome/chrome124/safari were all verified
# to get 200 from sirel.org; "chrome" tracks their current stable default.
IMPERSONATE = "chrome"

_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)

# 5xx and 429 are the usual suspects. 403 is here because sirel.org answers 403
# intermittently even to an accepted client, and treating that as a permanent
# verdict would silently zero out the source on a bad day.
_RETRY_STATUSES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})


class Fetcher:
    """A small session wrapper. One per run, per source.

    Politeness is not optional: these are small, volunteer-run sites and one of
    them (ExtracurricularHub) has ~1,760 detail pages. `sleep_seconds` is
    enforced BETWEEN requests, and the collector separately caps how many
    requests a run may make at all.
    """

    def __init__(
        self,
        user_agent: str,
        timeout: float = 20.0,
        retries: int = 2,
        sleep_seconds: float = 1.0,
        backoff_seconds: float = 1.0,
        prefer_curl_cffi: bool = True,
    ) -> None:
        self._sleep_seconds = sleep_seconds
        self._backoff_seconds = backoff_seconds
        self._retries = retries
        self._timeout = timeout
        self._last_request_at: float | None = None
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        }

        self._uses_curl = bool(prefer_curl_cffi and HAS_CURL_CFFI)
        if self._uses_curl:
            self._client = curl_requests.Session(
                headers=self._headers, impersonate=IMPERSONATE
            )
        else:
            self._client = httpx.Client(
                headers=self._headers, timeout=timeout, follow_redirects=True
            )
            if prefer_curl_cffi:
                # Worth one line in the run log: if a source starts returning
                # 403s, this is the first thing to check.
                logger.warning("web_fetcher_no_curl_cffi", transport="httpx")

    def get(self, url: str, **kwargs) -> "httpx.Response":
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> "httpx.Response":
        return self._request("POST", url, **kwargs)

    def _send(self, method: str, url: str, **kwargs):
        if self._uses_curl:
            kwargs.setdefault("timeout", self._timeout)
            kwargs.setdefault("allow_redirects", True)
            return self._client.request(method, url, **kwargs)
        return self._client.request(method, url, **kwargs)

    def _request(self, method: str, url: str, **kwargs):
        """Request with pacing and retry. Raises on total failure — every caller
        is inside a source's own try/except, which is where the failure is
        swallowed and logged."""
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            self._pace()
            try:
                response = self._send(method, url, **kwargs)
                status = response.status_code
                if status in _RETRY_STATUSES:
                    raise _StatusError(f"retryable status {status}", status)
                if status >= 400:
                    # Other 4xx are verdicts, not congestion.
                    raise _StatusError(f"http {status}", status)
                return response
            except _StatusError as exc:
                last_error = exc
                if exc.status not in _RETRY_STATUSES:
                    raise
            except _TRANSIENT as exc:
                last_error = exc
            except Exception as exc:  # curl_cffi raises its own error types
                if type(exc).__module__.startswith("curl_cffi"):
                    last_error = exc
                else:
                    raise

            if attempt < self._retries:
                delay = self._backoff_seconds * (2**attempt)
                logger.warning(
                    "web_fetch_retry", url=url, attempt=attempt + 1, delay=delay
                )
                time.sleep(delay)

        assert last_error is not None
        raise last_error

    def _pace(self) -> None:
        if self._last_request_at is not None:
            remaining = self._sleep_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class _StatusError(Exception):
    """One status-failure type across both transports, so the retry policy is
    written once instead of per-library."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status
