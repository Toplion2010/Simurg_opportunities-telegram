"""Telegram and web sources share source_channels — they must not see each other.

Web rows carry telegram_id=NULL. If the Telegram collector's accessors picked
them up, fetch_new_messages would hand None to Telethon as a channel id and the
whole Telegram collection path would fail. No DB here (this suite is
DB-free by design); the accessors are checked at the query level.
"""
from src.db.models.source_channel import KIND_TELEGRAM, KIND_WEB, SourceChannel
from src.db.repositories.source_channel import SourceChannelRepository


class RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)

        class _Result:
            def scalars(self):
                class _Scalars:
                    def all(self_inner):
                        return []

                return _Scalars()

        return _Result()


class RecordingRepo(SourceChannelRepository):
    """Captures the filters handed to BaseRepository.list."""

    def __init__(self) -> None:
        super().__init__(RecordingSession())
        self.list_filters = None

    async def list(self, **filters):
        self.list_filters = filters
        return []


def test_kinds_are_distinct_constants():
    assert KIND_TELEGRAM == "telegram"
    assert KIND_WEB == "web"
    assert KIND_TELEGRAM != KIND_WEB


def test_model_defaults_to_telegram():
    # Existing rows take this from the server default in migration 0006, so the
    # ~42 seeded channels keep working untouched.
    assert SourceChannel.__table__.c.kind.default.arg == KIND_TELEGRAM
    assert SourceChannel.__table__.c.kind.server_default.arg == KIND_TELEGRAM


def test_telegram_id_is_nullable_for_web_rows():
    assert SourceChannel.__table__.c.telegram_id.nullable is True
    # Still unique: Postgres allows many NULLs, so web rows cannot collide.
    assert SourceChannel.__table__.c.telegram_id.unique is True


async def _run(coro):
    return await coro


def test_get_active_excludes_web_sources():
    import asyncio

    repo = RecordingRepo()
    asyncio.run(_run(repo.get_active()))
    assert repo.list_filters == {"active": True, "kind": KIND_TELEGRAM}


def test_get_active_channel_ids_filters_kind_and_null_ids():
    import asyncio

    repo = SourceChannelRepository(RecordingSession())
    asyncio.run(_run(repo.get_active_channel_ids()))
    sql = str(repo._session.statements[0]).lower()
    assert "kind" in sql
    assert "telegram_id is not null" in sql
