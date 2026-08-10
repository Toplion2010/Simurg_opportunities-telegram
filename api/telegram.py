"""Telegram webhook endpoint, Vercel serverless function.

Why this exists: the bot only existed while a GitHub Actions job ran, so an
Approve tap took 30-60 minutes to apply. Telegram calls this function the
instant a button is pressed, so taps apply in seconds. Collection and
publishing stay on Actions -- this never renders a card (Playwright would
never fit in a serverless function) and never runs Telethon.

Approve only flips the row's status; the next drain.yml run publishes it.

Two things about this file are load-bearing:

  * Everything expensive is built ONCE at module scope and reused across warm
    invocations. build_dispatcher() *must* only ever be called once per process
    -- aiogram routers are module-level singletons and a second call raises
    "Router is already attached" (HANDOFF.md section 5).
  * A single event loop is kept for the process lifetime rather than
    asyncio.run() per request. The Bot's aiohttp session and SQLAlchemy's async
    engine bind to the loop that created them; a fresh loop per request would
    strand both and every second request would fail.

Env vars (Vercel project settings):
    DATABASE_URL            Neon connection string -- the DIRECT one, not -pooler
    BOT_TOKEN, ADMIN_IDS
    TELETHON_API_ID, TELETHON_API_HASH          unused, Settings requires them
    DEST_CHANNEL_ID_SCHOOL, DEST_CHANNEL_ID_UNIVERSITY   likewise
    SIMURG_WEBHOOK_SECRET   must match the secret_token given to setWebhook
"""
import asyncio
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler

_init_error: str | None = None

try:
    from aiogram import Bot
    from aiogram.types import Update

    from src.bot.bootstrap import build_dispatcher
    from src.core.config import Settings
    from src.core.logging import get_logger, setup_logging
    from src.db.base import create_serverless_engine
    from src.db.session import create_session_factory

    _SECRET = os.environ["SIMURG_WEBHOOK_SECRET"]

    _settings = Settings()
    setup_logging(_settings.ENVIRONMENT)
    _logger = get_logger(__name__)

    # One loop for the whole process; see the module docstring.
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    _engine = create_serverless_engine(_settings)
    _session_factory = create_session_factory(_engine)
    _bot = Bot(token=_settings.BOT_TOKEN)
    _dp = build_dispatcher(_settings, _session_factory, _bot)

    _logger.info("webhook_function_cold_start")
except Exception:  # noqa: BLE001
    # A raise at import time surfaces on Vercel as an opaque 500 with no body.
    # Capture it so the handler below can return the real reason instead.
    _init_error = traceback.format_exc()


class handler(BaseHTTPRequestHandler):
    """Vercel's Python runtime instantiates this per request."""

    def _reply(self, code: int, body: str = "") -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        # Lets you confirm the deployment is alive from a browser.
        if _init_error:
            self._reply(500, f"init failed:\n{_init_error}")
            return
        self._reply(200, "simurg webhook alive")

    def do_POST(self) -> None:
        if _init_error:
            # 500 (not 200) on purpose: Telegram retries, so a tap delivered
            # during a bad deploy is applied once the deploy is fixed rather
            # than silently dropped.
            self._reply(500, "handler failed to initialise")
            return

        # Telegram echoes the secret_token from setWebhook. Without this check
        # the public URL would accept forged approvals from anyone.
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != _SECRET:
            _logger.warning("webhook_bad_secret")
            self._reply(403, "forbidden")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            update = Update.model_validate(json.loads(raw), context={"bot": _bot})
        except Exception:
            # Malformed body will never parse; 200 stops Telegram retrying forever.
            _logger.exception("webhook_bad_payload")
            self._reply(200, "ignored")
            return

        try:
            _loop.run_until_complete(_dp.feed_update(_bot, update))
        except Exception:
            # 500 so Telegram redelivers -- a dropped update here is a lost
            # approval, which is the exact failure this whole project fought.
            _logger.exception("webhook_handler_failed", update_id=update.update_id)
            self._reply(500, "handler error")
            return

        self._reply(200, "ok")
