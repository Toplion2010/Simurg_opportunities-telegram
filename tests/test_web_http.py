"""The Fetcher's transport choice and retry policy.

sirel.org's WAF fingerprints the TLS handshake: curl gets 200 while httpx and
urllib get 403 from the same IP, same User-Agent, same moment. curl_cffi
presents a browser fingerprint and gets 200. These tests pin the selection
logic and the retry policy; neither touches the network.
"""
import pytest

from src.collector.web import http as web_http


def test_falls_back_to_httpx_when_curl_cffi_is_absent():
    # The fallback is what keeps `pip install -e .` enough to import and unit
    # test this package — no compiled libcurl needed for the test suite.
    fetcher = web_http.Fetcher(user_agent="ua", prefer_curl_cffi=False)
    try:
        assert fetcher._uses_curl is False
    finally:
        fetcher.close()


@pytest.mark.skipif(not web_http.HAS_CURL_CFFI, reason="scrape extra not installed")
def test_prefers_curl_cffi_when_available():
    fetcher = web_http.Fetcher(user_agent="ua")
    try:
        assert fetcher._uses_curl is True
    finally:
        fetcher.close()


def test_403_is_retryable():
    """Not a permanent verdict: sirel.org answers 403 intermittently even to an
    accepted client, and giving up on the first one zeroes out the source."""
    assert 403 in web_http._RETRY_STATUSES
    assert 429 in web_http._RETRY_STATUSES
    assert 503 in web_http._RETRY_STATUSES


def test_404_is_not_retryable():
    # Retrying a genuine 4xx just annoys the host and slows the run.
    assert 404 not in web_http._RETRY_STATUSES
    assert 401 not in web_http._RETRY_STATUSES


def test_pacing_is_enforced_between_requests():
    import time

    fetcher = web_http.Fetcher(user_agent="ua", sleep_seconds=0.05, prefer_curl_cffi=False)
    try:
        started = time.monotonic()
        fetcher._pace()
        fetcher._pace()
        assert time.monotonic() - started >= 0.05
    finally:
        fetcher.close()


def test_user_agent_names_the_project_contact():
    """A descriptive UA is what makes this legible to small volunteer-run sites
    as an aggregator rather than as an attack."""
    from src.core.config import Settings

    ua = Settings.model_fields["WEB_USER_AGENT"].default
    assert "simurg" in ua.lower()
    assert "Mozilla/5.0" in ua
