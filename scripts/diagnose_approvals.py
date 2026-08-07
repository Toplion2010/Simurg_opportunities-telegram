"""Read-only diagnostic for the "approvals never publish" problem.

Answers three questions the batch logs cannot:

    1. Is a webhook set on the bot? (a webhook makes getUpdates return 409 and
       silently starves the admin-drain window)
    2. Are the admin's button presses actually sitting in Telegram's update
       queue, waiting to be collected?
    3. What does the database think the status of every opportunity is?

Deliberately does NOT pass an ``offset`` to getUpdates: per the Bot API,
updates are confirmed (and therefore dropped) only when an offset is sent, so
this inspects the pending queue without consuming the admin's real taps.
"""
import asyncio
import json
import os

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import Settings
from src.db.models.opportunity import Opportunity

API = "https://api.telegram.org/bot{token}/{method}"


async def check_telegram(token: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        info = (await client.get(API.format(token=token, method="getWebhookInfo"))).json()
        print("=== getWebhookInfo ===")
        print(json.dumps(info, indent=2, ensure_ascii=False))

        result = info.get("result") or {}
        if result.get("url"):
            print("\n!! A WEBHOOK IS SET -> getUpdates cannot work. This is the bug.")
        print(f"\npending_update_count = {result.get('pending_update_count')}")

        print("\n=== pending updates (not confirmed/consumed) ===")
        upd = (
            await client.get(
                API.format(token=token, method="getUpdates"),
                params={"timeout": 0, "limit": 100},
            )
        ).json()
        if not upd.get("ok"):
            print("getUpdates FAILED:", json.dumps(upd, indent=2, ensure_ascii=False))
            return
        updates = upd.get("result", [])
        print(f"count = {len(updates)}")
        for u in updates:
            kind = next((k for k in u if k != "update_id"), "?")
            payload = u.get("callback_query", {})
            print(
                f"  update_id={u['update_id']} type={kind}"
                + (f" data={payload.get('data')!r}" if payload else "")
            )


async def check_db(settings: Settings) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            print("\n=== opportunities by status ===")
            rows = (
                await conn.execute(
                    select(Opportunity.status, func.count()).group_by(Opportunity.status)
                )
            ).all()
            if not rows:
                print("  (table empty)")
            for status, count in rows:
                print(f"  {getattr(status, 'value', status):<12} {count}")

            print("\n=== rows publish_scheduled() would pick up ===")
            due = (
                await conn.execute(
                    select(Opportunity.id, Opportunity.title, Opportunity.scheduled_at)
                    .where(Opportunity.status == "approved")
                    .limit(20)
                )
            ).all()
            print(f"  approved count = {len(due)}")
            for opp_id, title, scheduled_at in due:
                print(f"  id={opp_id} scheduled_at={scheduled_at} title={title!r}")
    finally:
        await engine.dispose()


async def check_gemini_models(api_key: str) -> None:
    """List image-capable models, so a 503 fallback chain uses real model names."""
    print("\n=== Gemini models supporting image output ===")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key, "pageSize": 200},
        )
        if resp.status_code != 200:
            print(f"  ListModels failed {resp.status_code}: {resp.text[:200]}")
            return
        for m in resp.json().get("models", []):
            name = m.get("name", "").removeprefix("models/")
            if "image" in name.lower() or "imagen" in name.lower():
                methods = ",".join(m.get("supportedGenerationMethods", []))
                print(f"  {name:<55} [{methods}]")


async def main() -> None:
    settings = Settings()
    await check_telegram(os.environ["BOT_TOKEN"])
    await check_db(settings)
    if settings.GEMINI_API_KEY:
        await check_gemini_models(settings.GEMINI_API_KEY)


if __name__ == "__main__":
    asyncio.run(main())
