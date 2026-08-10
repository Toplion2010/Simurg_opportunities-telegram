"""Single Vercel entrypoint: Telegram webhook + one-time webhook registration.

Why the bot is here at all: it used to exist only while a GitHub Actions job
ran, so an Approve tap took 30-60 minutes to apply. Telegram calls this the
instant a button is pressed, so taps apply in seconds. Collection and
publishing stay on Actions -- this never renders a card (Playwright would never
fit in a serverless function) and never runs Telethon. Approve just flips the
row's status; the next drain.yml run publishes it.

Why ONE file rather than api/telegram.py + api/setup.py: Vercel's Python
runtime resolves a single top-level `app`/`application`/`handler` per
deployment. With two, the build fails with "Found src/main.py but it does not
export a top-level app". So routing happens inside:

    POST any path            -> Telegram update
    GET  .../setup?secret=   -> register / inspect / delete the webhook
    GET  anything else       -> health check

Two implementation details are load-bearing:

  * Everything expensive is built ONCE at module scope and reused across warm
    invocations. build_dispatcher() must only ever run once per process --
    aiogram routers are module-level singletons and a second call raises
    "Router is already attached" (HANDOFF.md section 5).
  * A single event loop is kept for the process lifetime rather than
    asyncio.run() per request. The Bot's aiohttp session and SQLAlchemy's async
    engine bind to the loop that created them; a fresh loop per request would
    strand both and every warm request after the first would fail.

Env vars (Vercel project settings):
    DATABASE_URL            Neon connection string -- the DIRECT one, not -pooler
    BOT_TOKEN, ADMIN_IDS
    TELETHON_API_ID, TELETHON_API_HASH                   unused, Settings requires them
    DEST_CHANNEL_ID_SCHOOL, DEST_CHANNEL_ID_UNIVERSITY   likewise
    SIMURG_WEBHOOK_SECRET   guards both the setup URL and the webhook itself
"""
import asyncio
import json
import os
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
# Telegram posts here. Any path reaches this handler, but keep it explicit so
# getWebhookInfo is readable when something goes wrong.
_WEBHOOK_PATH = "/api/webhook"

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

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    _engine = create_serverless_engine(_settings)
    _session_factory = create_session_factory(_engine)
    _bot = Bot(token=_settings.BOT_TOKEN)
    _dp = build_dispatcher(_settings, _session_factory, _bot)

    _logger.info("webhook_function_cold_start")
except Exception:  # noqa: BLE001
    # Raising at import surfaces on Vercel as an opaque 500 with no body.
    # Capture it so the handler can return the real reason instead.
    _init_error = traceback.format_exc()


def _telegram(method: str, params: dict | None = None) -> dict:
    """Plain urllib so setup works even if the aiogram import above failed."""
    url = _TELEGRAM_API.format(token=os.environ["BOT_TOKEN"], method=method)
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.loads(r.read().decode())


class handler(BaseHTTPRequestHandler):
    """Vercel's Python runtime instantiates this per request."""

    def _reply(self, code: int, body: str = "") -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # ---------------------------------------------------------------- GET

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if not parsed.path.rstrip("/").endswith("setup"):
            if _init_error:
                self._reply(500, f"init failed:\n{_init_error}")
            else:
                self._reply(200, "simurg webhook alive")
            return

        # --- webhook registration -------------------------------------
        # A function has no startup hook, so this is triggered manually once
        # after deploying. Guarded by the same secret as the webhook itself.
        secret = os.environ.get("SIMURG_WEBHOOK_SECRET")
        if not secret:
            self._reply(500, "SIMURG_WEBHOOK_SECRET is not set")
            return
        if query.get("secret", [""])[0] != secret:
            self._reply(403, "forbidden: pass ?secret=<SIMURG_WEBHOOK_SECRET>")
            return

        action = query.get("action", ["set"])[0]
        try:
            if action == "info":
                self._reply(200, json.dumps(_telegram("getWebhookInfo"), indent=2))
                return

            if action == "delete":
                # Rollback. A webhook and getUpdates are mutually exclusive, so
                # while one is set drain.yml detects it and skips polling.
                # Deleting hands delivery straight back to GitHub Actions.
                # drop_pending_updates stays false so queued taps survive.
                res = _telegram("deleteWebhook", {"drop_pending_updates": "false"})
                info = _telegram("getWebhookInfo")
                self._reply(
                    200,
                    "WEBHOOK DELETED -- GitHub Actions polling resumes on the next "
                    f"drain run.\n\n{json.dumps(res)}\n\n{json.dumps(info, indent=2)}",
                )
                return

            # Derive the URL from the request so it cannot be mistyped and stays
            # correct across preview and production deployments.
            host = self.headers.get("Host", "")
            if not host:
                self._reply(500, "no Host header; cannot derive the webhook URL")
                return

            res = _telegram(
                "setWebhook",
                {
                    "url": f"https://{host}{_WEBHOOK_PATH}",
                    "secret_token": secret,
                    "allowed_updates": json.dumps(["message", "callback_query"]),
                    # Taps queued while the webhook was down are real approvals.
                    "drop_pending_updates": "false",
                },
            )
            info = _telegram("getWebhookInfo")
            self._reply(
                200,
                f"WEBHOOK SET -> https://{host}{_WEBHOOK_PATH}\n\n"
                f"{json.dumps(res)}\n\n{json.dumps(info, indent=2)}\n\n"
                "Tap Approve in Telegram; it should apply within seconds.\n"
                "Rollback: add &action=delete to this URL.",
            )
        except Exception:
            self._reply(500, traceback.format_exc())

    # --------------------------------------------------------------- POST

    def do_POST(self) -> None:
        if _init_error:
            # 500 rather than 200: Telegram retries, so a tap delivered during a
            # bad deploy is applied once fixed instead of silently dropped.
            self._reply(500, f"init failed:\n{_init_error}")
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
            # A malformed body will never parse; 200 stops Telegram retrying it
            # forever behind everything else in the queue.
            _logger.exception("webhook_bad_payload")
            self._reply(200, "ignored")
            return

        try:
            _loop.run_until_complete(_dp.feed_update(_bot, update))
        except Exception:
            # 500 so Telegram redelivers -- a dropped update here is a lost
            # approval, the exact failure this project has been fighting.
            _logger.exception("webhook_handler_failed", update_id=update.update_id)
            self._reply(500, "handler error")
            return

        self._reply(200, "ok")
