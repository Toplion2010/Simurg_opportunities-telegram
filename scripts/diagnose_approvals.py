"""Read-only diagnostic for the "approvals never publish" problem.

Answers three questions the batch logs cannot:

    1. Is a webhook set on the bot? (a webhook makes getUpdates return 409 and
       silently starves the drain)
    2. How many admin button presses are queued at Telegram, waiting to be
       collected?
    3. What does the database think the status of every opportunity is?
    4. Do stored `location` values actually carry a Kazakhstan signal the geo
       matcher can see? (see check_geo — this is what gates whether routing KZ
       hackathons on `location` can work at all)

**Never calls getUpdates.** An earlier version listed the queued updates with an
offset-less getUpdates, believing that to be a non-destructive read. It is not:
the next getUpdates confirms the previously delivered batch, so merely running
this diagnostic destroyed six real admin taps (three approvals) before the drain
could collect them. ``pending_update_count`` from getWebhookInfo answers the same
question and touches nothing.
"""
import asyncio
import json
import os
import re
from collections import Counter

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import Settings
from src.core.enums import Category
from src.core.geo import match_kazakhstan, normalize
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
        pending = result.get("pending_update_count")
        print(f"\npending_update_count = {pending}")
        if pending:
            print(
                f"  -> {pending} admin tap(s) queued and waiting. The next drain "
                "will apply them."
            )
        else:
            print("  -> nothing waiting; taps made from now on will queue here.")


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


# --- KZ geo signal -------------------------------------------------------
# Does the extractor's `location` field actually carry a recognisable
# Kazakhstan signal? Routing KZ hackathons to the dedicated channel rests
# entirely on that, and it is otherwise unverified. Runs the REAL matcher
# rather than a SQL twin of the regex, which would drift within one PR.

# Whole-string formats that mean "no host country stated". Only used to split
# the unmatched pile into "nothing to match" vs "a location the matcher missed"
# — a string like "Online, Kazakhstan" matches and never reaches here.
# Normalized on the way in for the same reason the geo tokens are: "онлайн"
# normalizes to "онлаин", so a literal set member would never be hit.
_ONLINE_WORDS = {
    normalize(w)
    for w in (
        "online",
        "remote",
        "worldwide",
        "virtual",
        "hybrid",
        "anywhere",
        "global",
        "онлайн",
        "удаленно",
        "дистанционно",
        "везде",
    )
}


def _looks_online(location: str) -> bool:
    words = re.findall(r"\w+", normalize(location))
    return bool(words) and all(w in _ONLINE_WORDS for w in words)


def _report(label: str, rows: list) -> None:
    total = len(rows)
    print(f"\n=== KZ geo signal — {label} (n={total}) ===")
    if not total:
        print("  (no rows)")
        return

    blank = online = 0
    matched: Counter = Counter()  # (location, token) -> n
    unmatched: Counter = Counter()  # location -> n
    org_only: Counter = Counter()  # (organizer, token) -> n, location missed it
    org_matched = 0

    for row in rows:
        location = (row.location or "").strip()
        token = match_kazakhstan(location)
        if token:
            matched[(location, token)] += 1
        elif not location:
            blank += 1
        elif _looks_online(location):
            online += 1
        else:
            unmatched[location] += 1

        org_token = match_kazakhstan(row.organizer)
        if org_token:
            org_matched += 1
            if not token:
                org_only[((row.organizer or "").strip(), org_token)] += 1

    matched_rows = sum(matched.values())
    unmatched_rows = sum(unmatched.values())
    no_signal = blank + online

    def pct(n: int) -> str:
        return f"{n:>5}  ({n / total:>5.1%})"

    print(f"  total                 {total:>5}")
    print(f"  location blank        {pct(blank)}")
    print(f"  location online-only  {pct(online)}")
    print(f"  location MATCHED KZ   {pct(matched_rows)}")
    print(f"  location unmatched    {pct(unmatched_rows)}   <- the shopping list")
    print(f"  organizer matched KZ  {pct(org_matched)}")
    print(f"  ...of which location missed: {sum(org_only.values())}")

    if matched:
        print("\n  -- matched: location -> token --")
        for (location, token) in sorted(matched, key=lambda k: -matched[k]):
            print(f"    {matched[(location, token)]:>4}x  {location!r} -> {token}")

    if unmatched:
        # Verbatim and complete: this is what tells you which tokens are missing.
        print("\n  -- UNMATCHED non-empty locations (verbatim) --")
        for location in sorted(unmatched, key=lambda k: -unmatched[k]):
            print(f"    {unmatched[location]:>4}x  {location!r}")

    if org_only:
        print("\n  -- organizer matches KZ but location did not (sizes a widening) --")
        for (organizer, token) in sorted(org_only, key=lambda k: -org_only[k])[:30]:
            print(f"    {org_only[(organizer, token)]:>4}x  {organizer!r} -> {token}")

    # The decision rule, written down before the run so the numbers are a
    # verdict rather than something to rationalise afterwards.
    print("\n  -- verdict --")
    if total < 20:
        print(f"    TOO SMALL (n={total} < 20) to conclude. Ship anyway — the routing")
        print("    is additive and cannot break existing publishing — and re-check")
        print("    in two weeks.")
    elif no_signal / total >= 0.5:
        print(f"    LOCATION IS THE BOTTLENECK: {no_signal / total:.0%} of rows are blank or")
        print("    online-only, so the matcher is not what is limiting the hit rate.")
        print("    Do the extractor prompt nudge (plan C2) first. A `country` column")
        print("    would be NULL just as often.")
    else:
        print(f"    Locations are populated ({1 - no_signal / total:.0%} non-blank, non-online).")
        # NOT recall. This number cannot tell "the matcher missed a KZ location"
        # apart from "the location simply is not KZ", and most of a global feed
        # is the latter. Recall is only readable off the unmatched list below.
        print(f"    KZ SHARE of populated locations: {matched_rows / (total - no_signal):.0%}")
        print("    (this is a property of the sources, NOT the matcher's hit rate)")
        print()
        print("    Now read the UNMATCHED list above and count how many YOU read as")
        print("    Kazakhstan. That count is the only measure of what the matcher is")
        print("    missing:")
        print("      ~none missed        -> recall is fine, ship as-is")
        print("      some missed         -> add those tokens to src/core/geo.py, re-run")
        print("      systematically bad  -> the one result that justifies a schema change")


async def check_geo(settings: Settings) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        Opportunity.id,
                        Opportunity.title,
                        Opportunity.location,
                        Opportunity.organizer,
                        Opportunity.status,
                        Opportunity.category,
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    hackathons = [
        r for r in rows if getattr(r.category, "value", r.category) == Category.Hackathon.value
    ]
    _report("category = 'Hackathon'", hackathons)
    # The KZ-signal rate is a property of the ~39 sources, not of one category,
    # and this sample is 10-100x larger — so a thin hackathon sample can still
    # be read against it.
    _report("ALL categories", rows)


# The public @username, so this check works BEFORE the numeric id is known --
# resolving it is half the point of the check.
HACKATHON_CHANNEL = "@simurg_hackathons"


async def check_hackathon_channel(token: str, settings: Settings) -> None:
    """Can the bot actually post to the hackathons channel, and what is its id?

    Read-only. Answers the two things that gate the KZ-hackathon routing and
    that nothing else can tell you: the numeric chat id to put in the
    DEST_CHANNEL_ID_HACKATHON secret, and whether BOT_TOKEN's bot has been made
    an administrator there with Post Messages (a manual Telegram step -- the
    Bot API has no way to grant it to itself).
    """
    target = settings.DEST_CHANNEL_ID_HACKATHON or HACKATHON_CHANNEL
    print()
    print(f"=== hackathons channel ({target}) ===")
    async with httpx.AsyncClient(timeout=30) as client:

        async def call(method: str, **params):
            resp = await client.get(API.format(token=token, method=method), params=params)
            return resp.json()

        chat = await call("getChat", chat_id=target)
        if not chat.get("ok"):
            print(f"  getChat FAILED: {chat.get('description')!r}")
            print("  -> the channel does not exist, is private, or the username is wrong.")
            return
        info = chat["result"]
        chat_id = info.get("id")
        print(f"  title      {info.get('title')!r}")
        print(f"  chat_id    {chat_id}   <- the value for DEST_CHANNEL_ID_HACKATHON")
        if settings.DEST_CHANNEL_ID_HACKATHON:
            same = settings.DEST_CHANNEL_ID_HACKATHON == chat_id
            print(f"  secret     {'matches' if same else 'DOES NOT MATCH the resolved id'}")
        else:
            print("  secret     not set (routing is off; this is a silent no-op, not an error)")

        me = await call("getMe")
        if not me.get("ok"):
            print(f"  getMe FAILED: {me.get('description')!r}")
            return
        bot_id = me["result"]["id"]
        bot_username = me["result"].get("username")
        # Printed BEFORE the membership call, which fails outright when the bot
        # is not in the channel — and "which bot do I add?" is precisely what
        # you need answered in that case.
        print(f"  bot        @{bot_username} (id={bot_id}) — this is the one to add")

        member = await call("getChatMember", chat_id=chat_id, user_id=bot_id)
        if not member.get("ok"):
            print(f"  getChatMember FAILED: {member.get('description')!r}")
            print("  -> the bot is probably not a member at all.")
            return
        result = member["result"]
        status = result.get("status")
        can_post = result.get("can_post_messages")
        print(f"  status     {status} can_post_messages={can_post}")
        if status == "administrator" and can_post:
            print("  -> OK: the bot can publish here.")
        else:
            print("  -> NOT READY. Add the bot as an ADMINISTRATOR with 'Post Messages'.")
            print("     Only a human can do this, in the Telegram app: channel ->")
            print("     Manage -> Administrators -> Add Admin -> the bot -> Post Messages.")


async def check_routing_preview(settings: Settings) -> None:
    """Where would publish() actually send each hackathon, right now?

    Runs the REAL _resolve_targets over real rows with the real Settings, and
    sends nothing. This is the one link the other checks cannot cover on their
    own: the matcher can be right AND the secret can be right while the two are
    still not wired to each other.

    Chat ids print as *** once they are registered secrets, so the target COUNT
    and the hackathon_channel flag are what carry the information here.
    """
    # Imported here, not at module scope, so the checks above still run in
    # environments without aiogram installed.
    from src.publisher.sender import OpportunitySender

    sender = OpportunitySender(settings)
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        Opportunity.id,
                        Opportunity.location,
                        Opportunity.audience,
                        Opportunity.category,
                    ).where(Opportunity.category == Category.Hackathon)
                )
            ).all()
    finally:
        await engine.dispose()

    print()
    print(f"=== routing preview — Hackathon rows (n={len(rows)}) ===")
    if not settings.DEST_CHANNEL_ID_HACKATHON:
        print("  DEST_CHANNEL_ID_HACKATHON is 0 -> nothing can route. Feature is off.")

    routed = 0
    for row in rows:
        # Transient, never added to a session: _resolve_targets reads only these.
        opp = Opportunity(
            id=row.id,
            location=row.location,
            audience=row.audience,
            category=row.category,
        )
        targets = sender._resolve_targets(opp)
        hit = bool(settings.DEST_CHANNEL_ID_HACKATHON) and (
            settings.DEST_CHANNEL_ID_HACKATHON in targets
        )
        routed += hit
        print(
            f"  id={row.id:<5} targets={len(targets)}  "
            f"hackathon_channel={'YES' if hit else 'no '}  {row.location!r}"
        )

    print()
    print(f"  -> {routed} of {len(rows)} hackathon rows would ALSO reach the hackathons channel.")


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
    await check_geo(settings)
    await check_hackathon_channel(os.environ["BOT_TOKEN"], settings)
    await check_routing_preview(settings)
    if settings.GEMINI_API_KEY:
        await check_gemini_models(settings.GEMINI_API_KEY)


if __name__ == "__main__":
    asyncio.run(main())
