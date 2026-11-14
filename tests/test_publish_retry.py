"""Retrying publish_scheduled() after the database drops the connection.

A Neon restart killed the drain job's first query ("terminating connection due
to administrator command"), so nothing published until the next scheduled run.
A retry is only safe before the first send: after one, the dropped connection
may have lost the commit that marks the row published, and a retry would post
it twice. These tests pin that boundary.
"""
import asyncio
from types import SimpleNamespace

import pytest
from asyncpg import exceptions as asyncpg_exc
from sqlalchemy.exc import DBAPIError, IntegrityError

from scripts.drain_and_publish import publish_with_retry
from src.db.base import is_connection_lost
from src.publisher import scheduler
from src.publisher.scheduler import PublishNotStartedError


def _wrapped(orig: BaseException) -> DBAPIError:
    """Shaped like the CI failure: SQLAlchemy's DBAPIError whose cause chain
    ends at asyncpg's own exception."""
    err = DBAPIError("SELECT ...", {}, orig)
    err.__cause__ = orig
    return err


@pytest.mark.parametrize(
    "orig",
    [
        asyncpg_exc.ConnectionDoesNotExistError(
            "connection was closed in the middle of operation"
        ),
        asyncpg_exc.AdminShutdownError("terminating connection due to administrator command"),
        asyncpg_exc.CannotConnectNowError("the database system is starting up"),
        ConnectionResetError("reset by peer"),
    ],
)
def test_connection_loss_is_detected_through_the_wrapper(orig):
    assert is_connection_lost(_wrapped(orig))


def test_query_errors_are_not_connection_loss():
    assert not is_connection_lost(
        IntegrityError("INSERT ...", {}, asyncpg_exc.UniqueViolationError("dup"))
    )
    assert not is_connection_lost(ValueError("bad data"))


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _DroppingRepo:
    def __init__(self, session):
        pass

    async def get_due_for_publish(self, now):
        raise _wrapped(asyncpg_exc.AdminShutdownError("administrator command"))


def test_connection_drop_before_send_raises_retryable_and_sends_nothing(monkeypatch):
    sent = []

    class _Sender:
        def __init__(self, *a, **kw):
            pass

        async def publish(self, opp, bot):
            sent.append(opp)

    monkeypatch.setattr(scheduler, "OpportunityRepository", _DroppingRepo)
    monkeypatch.setattr(scheduler, "OpportunitySender", _Sender)
    settings = SimpleNamespace(DAILY_PUBLISH_CAP=5)

    with pytest.raises(PublishNotStartedError):
        asyncio.run(scheduler.publish_scheduled(settings, _FakeSession, bot=None))
    assert sent == []


def test_other_errors_before_send_are_not_made_retryable(monkeypatch):
    class _BrokenRepo(_DroppingRepo):
        async def get_due_for_publish(self, now):
            raise ValueError("bug")

    monkeypatch.setattr(scheduler, "OpportunityRepository", _BrokenRepo)
    with pytest.raises(ValueError):
        asyncio.run(
            scheduler.publish_scheduled(
                SimpleNamespace(DAILY_PUBLISH_CAP=5), _FakeSession, bot=None
            )
        )


def _counting(failures: list[BaseException]):
    calls = []

    async def publish():
        calls.append(1)
        if failures:
            raise failures.pop(0)

    return publish, calls


def test_retries_after_connection_drop_then_succeeds():
    publish, calls = _counting([PublishNotStartedError("dropped")])
    asyncio.run(publish_with_retry(publish, delays=(0, 0)))
    assert len(calls) == 2


def test_gives_up_after_the_last_retry():
    publish, calls = _counting([PublishNotStartedError("dropped")] * 5)
    with pytest.raises(PublishNotStartedError):
        asyncio.run(publish_with_retry(publish, delays=(0, 0)))
    assert len(calls) == 3


def test_does_not_retry_other_errors():
    # Anything else may have come after a send -- never retried.
    publish, calls = _counting([DBAPIError("UPDATE ...", {}, Exception("x"))])
    with pytest.raises(DBAPIError):
        asyncio.run(publish_with_retry(publish, delays=(0, 0)))
    assert len(calls) == 1
