"""
Always-on admin bot, webhook mode. Intended for Koyeb's free tier.

This runs *only the bot*: it answers /start, View Queue, and — the whole point —
applies Approve/Reject taps within seconds instead of the 30-60 minutes a
GitHub Actions cron takes to come around.

It deliberately does NOT:

  * start Telethon (collection stays on ``batch.yml``)
  * render or publish cards (Playwright + Chromium will not run on 0.1 vCPU /
    512MB, and this image doesn't even ship Chromium -- see Dockerfile.bot)
  * run APScheduler

Approve only flips the row's status (see src/bot/routers/queue.py); the next
``drain.yml`` run calls publish_scheduled and the post goes out. So taps feel
instant, posts still land within the usual Actions window.

While this is running it owns update delivery. ``_drain_admin_updates`` checks
getWebhookInfo and skips polling on its own, so the two never fight over
getUpdates -- no workflow edit is needed to switch modes in either direction.

Env (beyond the usual secrets):
    SIMURG_WEBHOOK_BASE_URL   required, e.g. https://simurg-bot-xxxx.koyeb.app
    SIMURG_WEBHOOK_SECRET     required, any long random string
    PORT                      injected by Koyeb, defaults to 8080

Run:
    python -m src.routines.bot_webhook
"""
import os

from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from src.bot.bootstrap import build_dispatcher
from src.core.config import Settings
from src.core.logging import get_logger, setup_logging
from src.db.base import create_engine
from src.db.session import create_session_factory

logger = get_logger(__name__)

# The path is secret as well as the header token. Telegram will happily deliver
# to any URL someone points it at, so an unguessable path keeps stray scanners
# out of the handler entirely.
_WEBHOOK_PATH_TEMPLATE = "/tg/{secret}"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(
            f"{name} is not set. Set it in the Koyeb service's environment "
            f"variables (see the module docstring)."
        )
    return value


def build_app() -> web.Application:
    settings = Settings()
    setup_logging(settings.ENVIRONMENT)

    base_url = _required("SIMURG_WEBHOOK_BASE_URL").rstrip("/")
    secret = _required("SIMURG_WEBHOOK_SECRET")
    path = _WEBHOOK_PATH_TEMPLATE.format(secret=secret)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    # No default parse_mode, matching src/main.py -- every handler passes
    # parse_mode="HTML" itself, so a default here would only add divergence.
    bot = Bot(token=settings.BOT_TOKEN)

    # build_dispatcher() may only be called once per process: aiogram routers are
    # module-level singletons and a second call raises "Router is already
    # attached". Fine here -- this process builds exactly one.
    dp = build_dispatcher(settings, session_factory, bot)
    allowed = dp.resolve_used_update_types()

    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        # Target for the keep-warm pinger (cron-job.org every ~45 min) so Koyeb's
        # 1-hour scale-to-zero never kicks in and taps never eat a ~30s cold start.
        return web.Response(text="ok")

    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    async def on_startup(_: web.Application) -> None:
        # drop_pending_updates=False on purpose: taps queued while this was down
        # are real approvals, and losing them silently is exactly the bug that
        # cost days of debugging. Let them replay through the handlers.
        await bot.set_webhook(
            url=f"{base_url}{path}",
            secret_token=secret,
            allowed_updates=allowed,
            drop_pending_updates=False,
        )
        info = await bot.get_webhook_info()
        logger.info(
            "webhook_set",
            pending=info.pending_update_count,
            allowed=allowed,
        )

    async def on_cleanup(_: web.Application) -> None:
        # Hand delivery back to getUpdates so drain.yml resumes applying taps the
        # moment this service stops. Without it a dead container would keep the
        # webhook registered and every tap would sit undelivered forever.
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            logger.info("webhook_deleted", hint="polling via drain.yml resumes")
        except Exception:
            logger.exception("webhook_delete_failed")
        await bot.session.close()
        await engine.dispose()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=path)
    setup_application(app, dp, bot=bot)

    logger.info("webhook_bot_ready", base_url=base_url)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    web.run_app(build_app(), host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
