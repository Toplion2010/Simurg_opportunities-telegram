from __future__ import annotations

from datetime import date

from sources.base import Hackathon
from sources.devpost import DevpostSource, _absolute_url


def test_devpost_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("devpost.json")
    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: response)

    hackathons = DevpostSource().fetch()

    assert len(hackathons) == 2
    first = hackathons[0]
    assert first.source == "devpost"
    assert first.source_id == "12345"
    assert first.title == "Test Hackathon"
    assert first.starts_at == date(2026, 9, 1)
    assert first.ends_at == date(2026, 9, 15)
    assert first.is_online is True
    assert first.prize_text == "$1,000"
    assert first.themes == ["Machine Learning/AI", "Web"]
    assert first.image_url == "https://d2dmyh35ffsxbl.cloudfront.net/test-thumb.png"
    assert first.organizer == "Test Org"

    second = hackathons[1]
    assert second.starts_at == date(2026, 10, 10)
    assert second.ends_at == date(2026, 10, 10)
    assert second.is_online is False
    assert second.location == "Austin, TX"


def test_absolute_url_treats_generic_placeholder_as_no_image():
    placeholder = (
        "https://d2dmyh35ffsxbl.cloudfront.net/assets/defaults/"
        "thumbnail-placeholder-8c916ef4da99a222ce6ece077c71c7e282f071f830747b2abb5718018cbfa699.gif"
    )
    assert _absolute_url(placeholder) is None


def test_absolute_url_fixes_protocol_relative():
    assert _absolute_url("//example.com/real-thumb.png") == "https://example.com/real-thumb.png"


def test_absolute_url_keeps_real_absolute_url():
    assert _absolute_url("https://example.com/real-thumb.png") == "https://example.com/real-thumb.png"


def test_devpost_returns_empty_on_malformed_json(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: FakeResponse("not json"))
    assert DevpostSource().fetch() == []


def _bare_hackathon() -> Hackathon:
    return Hackathon(
        source="devpost", source_id="1", title="Test Hackathon",
        url="https://test-hack.devpost.com/", starts_at=date(2026, 8, 22),
        ends_at=date(2026, 9, 27), is_online=True, prize_text="$750",
        location="Online", themes=[], raw={},
    )


def test_devpost_enrich_parses_fixture(fixture_response, monkeypatch):
    response = fixture_response("devpost_detail.html")
    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: response)

    enriched = DevpostSource().enrich(_bare_hackathon())

    assert enriched.description == (
        "A problem-solving hackathon focused on identifying and building innovative "
        "solutions to real-world unsolved challenges in Blockchain and Web3. Bring "
        "your boldest ideas, challenge existing limitations, and build decentralized "
        "solutions that can create meaningful impact across finance, identity, "
        "security, governance, gaming, and beyond."
    )
    assert enriched.prize_breakdown == [
        "1st Prize: $500 of USDT",
        "2nd Prize: $200 of USDT",
        "3rd Prize: $50 of USDT",
    ]
    assert enriched.eligibility == (
        "Students only; Companies/professional organizations excluded from participation"
    )
    assert enriched.required_tech == []
    assert enriched.deadline == date(2026, 9, 27)
    assert enriched.sponsors == ["Art of Problem Solving", "CodeCrafters", "NordVPN"]
    # listing-level fields must be untouched
    assert enriched.title == "Test Hackathon"
    assert enriched.prize_text == "$750"


def test_devpost_enrich_boilerplate_only_gives_none_eligibility(fixture_response, monkeypatch):
    html = """
    <script type="application/ld+json" id="challenge-json-ld">
    {"description": "Open hackathon.", "endDate": "2026-09-27T03:00:00.000-04:00"}
    </script>
    <ul id="eligibility-list">
      <li>Above legal age of majority in country of residence</li>
      <li>All countries/territories, excluding standard exceptions</li>
    </ul>
    """
    from conftest import FakeResponse
    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: FakeResponse(html))

    enriched = DevpostSource().enrich(_bare_hackathon())
    assert enriched.eligibility is None


def test_devpost_enrich_returns_unchanged_when_no_json_ld(monkeypatch):
    from conftest import FakeResponse

    monkeypatch.setattr("sources.devpost.get", lambda *a, **k: FakeResponse("<html><body>gone</body></html>"))
    original = _bare_hackathon()

    enriched = DevpostSource().enrich(original)
    assert enriched == original


def test_devpost_enrich_returns_unchanged_on_fetch_failure(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr("sources.devpost.get", _raise)
    original = _bare_hackathon()

    enriched = DevpostSource().enrich(original)
    assert enriched == original
