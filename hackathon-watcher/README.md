# Hackathon Watcher

A free, serverless hackathon watcher. It runs entirely on GitHub Actions
cron — no persistent server, no paid services, no API keys other than a
Telegram bot token, no LLM. It fetches listings from Devpost, dev.events,
MLH, Devfolio, and reskilll, deduplicates them, filters for relevance, and
posts new ones to a Telegram channel.

This bot and its channel are fully independent of anything else in this
repo — it does not share state, secrets, or a channel with Simurg's own
hackathon-related plans.

## Setup

### 1. Create the bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   follow the prompts. You'll get a token like `123456:ABC-DEF...` — this
   is `TELEGRAM_BOT_TOKEN`.
2. Create the Telegram channel you want posts to go to (public or private).
3. Add the bot to the channel as an **administrator** with permission to
   post messages.

### 2. Get the channel's numeric chat id

- If the channel is public, forward any message from it to
  [@userinfobot](https://t.me/userinfobot) — it replies with the chat id
  (looks like `-100XXXXXXXXXX`).
- If private, post a message in the channel, then call
  `https://api.telegram.org/bot<TOKEN>/getUpdates` and read the `chat.id`
  field of the update.

This is `TELEGRAM_CHAT_ID`.

### 3. Add GitHub Secrets

In this repo's Settings → Secrets and variables → Actions, add:

- `HACKATHON_WATCHER_BOT_TOKEN` — the bot token from step 1
- `HACKATHON_WATCHER_CHAT_ID` — the chat id from step 2

(Named with a `HACKATHON_WATCHER_` prefix deliberately, so they can't be
confused with any other bot's secrets in this repo.)

### 4. Seed the state before enabling the cron

Run once, locally, **before** the workflow's first scheduled run — this
prevents the first real run from dumping every hackathon currently live
into the channel at once:

```bash
cd hackathon-watcher
pip install -r requirements.txt
python main.py --seed
git add state/seen.json
git commit -m "hackathon-watcher: seed initial state"
git push
```

### 5. Enable the workflow

The workflow (`.github/workflows/hackathon-check.yml`) runs every 3 hours
and on manual dispatch. Nothing else to enable — it starts running once
merged to the default branch, and only *new* hackathons (not seeded ones)
get posted.

## CLI

```
python main.py [options]

-r, --resources NAME [NAME...]  run only these sources
-n, --dry-run                   fetch/dedup/filter, print, persist nothing
-l, --limit N                   cap items processed per source
-f, --force                     ignore seen.json, re-process everything
    --seed                      populate seen.json without posting
```

Examples:

```bash
python main.py --dry-run                     # see what would post, right now
python main.py -r devpost mlh -n -l 5         # debug two sources, capped
python main.py --seed                         # one-time backlog seed
```

## Adding a source

Write `sources/<name>.py` with a class implementing `Source.fetch() ->
list[Hackathon]` (see `sources/base.py`), then add one entry to
`config.SOURCES`:

```python
"myname": {"module": "sources.myname", "priority": 6, "enabled": True},
```

`priority` breaks dedup ties (lower wins). No other file needs to change —
`main.py` resolves sources dynamically.

## Configuration

All tunables live in `config.py`: filter thresholds (`ONLINE_ONLY`,
`STILL_OPEN`, `MIN_PRIZE`, `EXCLUDE_THEMES`, `INCLUDE_THEMES`),
`MAX_POSTS_PER_RUN`, per-source settings, and HTTP timeout/retry knobs.

## Tests

```bash
cd hackathon-watcher
pytest tests/
```

Parser tests run against saved HTML/JSON fixtures in `tests/fixtures/`, so
selector rot on the live sites shows up in CI without a network call.
