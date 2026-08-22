from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def fixture_response():
    def _load(filename: str) -> FakeResponse:
        return FakeResponse((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return _load
