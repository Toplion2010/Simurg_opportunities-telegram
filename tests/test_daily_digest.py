"""The daily digest's DB-facing repository methods (src/db/repositories/
opportunity.py: get_digest_candidates, count_published_since).

DB-free by design, like tests/test_web_source_isolation.py: inspects the
compiled SQL a statement WOULD run, rather than standing up a database — this
suite (tests/test_*.py under CI's test.yml) is scoped to pure functions and
query construction, no DB/network/secrets. src/routines/daily_digest.py's
run() itself (DB writes + live Telegram sends) is verified the same way
publisher/scheduler.py and routines/batch_processor.py are: a real dispatched
workflow run, not a unit test.
"""
import asyncio
from datetime import datetime

from src.db.repositories.opportunity import OpportunityRepository


class RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)

        class _Result:
            def scalars(self_inner):
                class _Scalars:
                    def all(self_inner2):
                        return []

                return _Scalars()

            def scalar_one(self_inner):
                return 0

        return _Result()


def _run(coro):
    return asyncio.run(coro)


def _sql(statement) -> str:
    # literal_binds so a bound value (min_score, limit, the `since` cutoff)
    # shows up in the text instead of a `:param_N` placeholder.
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


def test_get_digest_candidates_filters_pending_undigested_above_the_score():
    repo = OpportunityRepository(RecordingSession())
    _run(repo.get_digest_candidates(min_score=90, limit=5))
    sql = _sql(repo._session.statements[0])
    assert "status = 'pending'" in sql
    assert "digested_at is null" in sql
    assert "relevance >= 90" in sql
    assert "limit 5" in sql


def test_get_digest_candidates_orders_best_score_first_then_soonest_deadline():
    repo = OpportunityRepository(RecordingSession())
    _run(repo.get_digest_candidates(min_score=90, limit=5))
    sql = _sql(repo._session.statements[0])
    order_by = sql.split("order by", 1)[1]
    # relevance desc must come before the deadline tiebreak, which must come
    # before the final oldest-first fallback.
    assert order_by.index("relevance") < order_by.index("deadline")
    assert order_by.index("deadline") < order_by.index("created_at")
    assert "opportunities.relevance desc" in order_by


def test_count_published_since_filters_status_and_cutoff():
    repo = OpportunityRepository(RecordingSession())
    since = datetime(2026, 9, 3, 0, 0, 0)
    _run(repo.count_published_since(since))
    sql = _sql(repo._session.statements[0])
    assert "status = 'published'" in sql
    assert "published_at >=" in sql
    assert "2026-09-03" in sql
