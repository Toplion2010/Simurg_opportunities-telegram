from types import SimpleNamespace

from src.processor.manual import parse_external_id
from src.publisher.scheduler import split_manual


def test_parse_external_id_text_only():
    assert parse_external_id("manual:123:45") == (123, 45, None)


def test_parse_external_id_with_photo_and_negative_chat():
    # file ids never contain ':' but be safe: everything after the 2nd colon is the id
    assert parse_external_id("manual:-100:7:AgAC_x-y") == (-100, 7, "AgAC_x-y")


def _opp(external_id):
    raw = SimpleNamespace(external_id=external_id) if external_id is not None else None
    return SimpleNamespace(raw_message=raw)


def test_split_manual_keeps_order_and_ignores_drafts():
    a, b, c, d, e = (
        _opp("manual:1:2"),
        _opp(None),
        _opp("manual-draft:1:3"),
        _opp("slug-x"),
        _opp("manual:1:4"),
    )
    manual, rest = split_manual([a, b, c, d, e])
    assert manual == [a, e]
    assert rest == [b, c, d]


def test_split_manual_tolerates_rows_without_raw_message_attr():
    plain = SimpleNamespace()
    assert split_manual([plain]) == ([], [plain])
