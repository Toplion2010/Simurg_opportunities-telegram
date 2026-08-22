"""Shared HTTP helper: real User-Agent, timeout, retry with backoff."""

from __future__ import annotations

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)


def get(url: str, **kwargs) -> requests.Response:
    """GET with a real User-Agent, a fixed timeout, and retries on 5xx /
    timeout. Raises requests.RequestException if every attempt fails —
    callers (each Source.fetch) are responsible for catching that."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", config.USER_AGENT)
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT_SECONDS)

    attempts = config.REQUEST_RETRIES + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=headers, **kwargs)
            if response.status_code >= 500:
                raise requests.HTTPError(
                    f"{response.status_code} from {url}", response=response
                )
            return response
        except (requests.Timeout, requests.HTTPError, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < attempts - 1:
                sleep_for = config.REQUEST_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "GET %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    url,
                    attempt + 1,
                    attempts,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for)

    assert last_exc is not None
    raise last_exc
