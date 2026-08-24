from __future__ import annotations

from sources.http import get


class _FakeResponse:
    def __init__(self, content: bytes, content_type: str = "text/html", status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.encoding = "ISO-8859-1"  # requests' default guess without a charset
        self.apparent_encoding = "utf-8"


def test_get_corrects_encoding_when_content_type_lacks_charset(monkeypatch):
    response = _FakeResponse("₹54,00,000+ prize".encode("utf-8"), content_type="text/html")
    monkeypatch.setattr("sources.http.requests.get", lambda *a, **k: response)

    result = get("https://example.com")
    assert result.encoding == "utf-8"


def test_get_leaves_encoding_alone_when_charset_declared(monkeypatch):
    response = _FakeResponse(b"plain ascii", content_type="text/html; charset=utf-8")
    monkeypatch.setattr("sources.http.requests.get", lambda *a, **k: response)

    result = get("https://example.com")
    assert result.encoding == "ISO-8859-1"  # untouched — server was explicit


def test_get_handles_empty_body_without_crashing(monkeypatch):
    response = _FakeResponse(b"", content_type="text/html")
    monkeypatch.setattr("sources.http.requests.get", lambda *a, **k: response)

    result = get("https://example.com")
    assert result is response
