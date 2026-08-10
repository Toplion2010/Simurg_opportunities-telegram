# Simurg — handoff notes

Working state as of **2026-08-09**. Written so a fresh session can pick this up
without re-deriving anything. Read this **before** touching the admin-approval
or publishing code.

---

## 1. What this project is

A Telegram bot that finds "opportunities" (scholarships, hackathons, internships)
and posts them to two channels. Three distinct jobs:

| Job | What it does | Runs where |
|---|---|---|
| **Collect** | Telethon userbot reads ~40 source channels → Groq/Gemini extract structured rows into Postgres | GitHub Actions `batch.yml`, 5×/day |
| **Review** | aiogram bot DMs the admin inline Approve/Reject buttons | GitHub Actions `drain.yml`, `*/10` cron |
| **Publish** | Playwright+Chromium renders an HTML/CSS card → posts to channels | Both `batch.yml` and `drain.yml` |

There is **no always-on process**. Everything is short-lived GitHub Actions jobs.
Secrets live in GitHub Actions secrets (`DATABASE_URL`, `BOT_TOKEN`, `ADMIN_IDS`,
`TELETHON_*`, `DEST_CHANNEL_ID_*`, `GROQ_API_KEY`, `GEMINI_API_KEY`). There is no
local `.env` and no local Postgres — **you cannot run this app locally**; all
verification happens by dispatching workflows and reading logs.

The repo is **public**, so Actions minutes are unlimited/free.

---

## 2. Workflows

| File | Trigger | Purpose |
|---|---|---|
| `batch.yml` | cron `7 1,5,9,13,17 * * *` + manual | Collect → process → publish. Sets `SIMURG_SKIP_DRAIN=true`. |
| `drain.yml` | cron `*/10` + manual | Apply admin taps → publish. **Sole `getUpdates` consumer.** |
| `diagnose.yml` | manual only | Read-only health check (webhook state, pending count, DB status, Gemini models). |
| `preview.yml` | manual only | Renders real cards, uploads JPEGs as artifacts, publishes nothing. |

`batch.yml` and `drain.yml` share `concurrency: group: simurg-runtime` so they can
never run at once — two `getUpdates` callers would 409, and two publishers could
double-post.

Useful commands:
```bash
gh workflow run drain.yml --ref main -f window_seconds=120
gh workflow run diagnose.yml --ref main
gh workflow run preview.yml --ref main -f count=4
gh run list --workflow=drain.yml --limit 10 --json createdAt,event,conclusion
gh run view <id> --log | grep -E "approval_recorded|admin_updates_drained|opportunity_published"
```

---

## 3. Bugs found and fixed (all on `main`, all verified)

Read the commit messages — they explain the reasoning in detail.

1. **`574bf94` — Gemini 503 killed every publish.** `gemini-2.5-flash-image`
   returns `503 UNAVAILABLE` under load; the renderer treated that as fatal, so
   *every* approved post died. `image_gen.py` already had a complete procedural
   background for `bg_entry=None` that was unreachable. Now it falls back.
2. **`96abd90` — retries were hopeless.** 3 tries over 15s against an outage
   lasting hours. Now rotates through sibling models
   (`gemini-3.1-flash-image`, `-lite-`, `gemini-3-pro-image`) over ~85s.
   Congestion is per-model, so a sibling usually answers instantly.
3. **`58381e2` — everything was silent.** Approve/Reject logged *nothing*, and
   `publish_scheduled` returned silently on an empty queue, so "nobody approved"
   and "everything crashed" looked identical. Added `approval_recorded` /
   `rejection_recorded`, always-log the due count, and admin alerts on failure.
   Also swallow `TelegramBadRequest` on stale `answerCallbackQuery`.
4. **`f72f8b0` — one failure skipped all the rest.** `session.rollback()` expires
   ORM objects; reading `opp.title` afterwards triggered a lazy load →
   `MissingGreenlet` → escaped the per-item `try` → aborted the whole loop.
5. **`ba6b4aa` — THE BIG ONE: taps were destroyed.** See §4.
6. **`5669ddf` — the diagnostic destroyed taps.** See §5.

---

## 4. Why taps used to vanish (do not reintroduce this)

`dp.start_polling()` advances the Telegram `offset` as soon as updates are
**fetched**, and runs each handler as a *detached* `asyncio` task. The old
`_drain_admin_updates` polled for a fixed 90s then cancelled. Any handler still
running was killed — but Telegram already considered those updates delivered.
The tap was **gone permanently and logged nothing**, because handlers only log
after their commit.

`_drain_admin_updates` in `src/routines/batch_processor.py` now drives
`getUpdates` manually:

- offset advances **only after** `await dp.feed_update(...)` returns
- the advanced offset reaches Telegram on the *next* call, so an interrupted run
  leaves taps queued for the next run rather than destroying them
- a raising handler is logged and skipped so one poison update can't wedge the queue
- returns as soon as the queue is empty (usually 1 API call, ~1s)

**Never replace this with `start_polling()`.**

---

## 5. Traps that already bit us

- **Never call `getUpdates` in a "read-only" tool.** An offset-less `getUpdates`
  is *not* a safe read: the next `getUpdates` confirms the previously delivered
  batch. `diagnose_approvals.py` did this and destroyed 6 real taps (3 approvals).
  Use `getWebhookInfo`'s `pending_update_count` instead — that touches nothing.
- **`build_dispatcher()` can only be called once per process.** aiogram routers
  are module-level singletons; a second call raises
  `RuntimeError: Router is already attached`.
- **`session.rollback()` expires ORM objects.** Capture `id`/`title` *before* the
  operation that might fail.
- **GitHub cron is wildly unpunctual.** The 4-hourly `batch.yml` starts **1–3
  hours late, every time**. The `*/10` drain actually fires every **26–133 min**
  (avg ~45). Do not promise "every 10 minutes" — measure with `gh run list`.
- **Gemini 503 is normal, not a billing problem.** Vision calls succeed and some
  image calls succeed in the same minute. It's capacity, not the account.

---

## 6. Verified current state

Confirmed by workflow logs and the diagnostic, not assumed:

- Collection: working unattended, ~120 messages/run.
- Publishing: working. 7/7 published in one run with real Gemini artwork;
  another published unattended end-to-end at 2026-08-07 14:26 UTC.
- Taps: **no longer lost** — proven by the diagnostic showing 6 queued
  callbacks (`oa:87:approve` etc.) surviving until collected.
- `batch.yml` correctly logs `drain_skipped`, so only `drain.yml` polls.
- DB last seen: `pending 97 / rejected 164 / published 21 / approved 0`.

**VERIFIED END-TO-END 2026-08-10** on the Vercel webhook (run 31360621839):
tap → `✅ Approved` edit in Telegram within ~1s → `drain_skipped_webhook_active`
(the drain saw the live webhook and published without polling, no 409) →
`publishing_due_opportunities count: 2` → both `opportunity_published` with real
Gemini artwork on attempt 1. The webhook URL is the stable
`simurg-opportunities-telegram-ten.vercel.app`, **not** a deployment-specific
`-<hash>` host — the latter is pinned to one immutable deployment and would
break on the next push.

---

## 7. The remaining problem

The bot is only alive while a job runs, so:

- Buttons take **~30–60 min** to take effect (they are never lost, just queued).
- The bot does not answer `/start` or `View Queue` between runs.

The user has repeatedly said this is the main pain. They **refuse to pay** and
found Oracle Cloud signup too hard.

---

## 8. Always-on bot — VERCEL is the live path; Koyeb is abandoned

**Current plan: Vercel serverless webhook.** Koyeb was built and CI-verified
first, but its console would not render for the user (empty sidebar, no
navigation, possibly a deactivated org) and they gave up on it. The Koyeb files
stay on `main`, dormant and harmless — nothing runs until a webhook is set.

Vercel suits this better regardless: Telegram invokes the function per tap, so
there is no sleeping instance, no keep-warm ping and no container.

| | Vercel (live path) | Koyeb (abandoned) |
|---|---|---|
| Entrypoint | `api/telegram.py` | `src/routines/bot_webhook.py` |
| Deps | `requirements.txt` | `Dockerfile.bot` |
| CI proof | `vercelcheck.yml` ✅ | `botcheck.yml` ✅ |
| Sleeps? | no | after 1 h |

Both share the same mode switch: `_drain_admin_updates` checks `getWebhookInfo`
and skips polling whenever a webhook is live, so Actions and the webhook can
never fight over `getUpdates`, in either direction, with no workflow edit.

### Vercel specifics worth knowing

- **10 s max execution** on the free plan. A tap is ~2 DB round trips + 2
  Telegram calls, normally under 2 s. A cold start plus a suspended Neon compute
  could brush the limit; the handler returns 500 so Telegram redelivers, and the
  retry hits a warm instance.
- **Everything is built once at module scope**, and one event loop is kept for
  the process. `build_dispatcher()` must never run twice per process, and the
  Bot's aiohttp session and the SQLAlchemy engine bind to the loop that created
  them — `asyncio.run()` per request would strand both.
- **Use Neon's DIRECT URL**, not `-pooler`. Through PgBouncer transaction mode
  asyncpg's prepared statements break and would need `statement_cache_size=0`.
- **Import errors are captured, not raised.** A raise at import time shows on
  Vercel as an opaque 500 with no body; `_init_error` is returned instead.
- `setup_logging`'s file handler is best-effort — Vercel mounts the deployment
  read-only apart from `/tmp`.

### Deploying Vercel

1. vercel.com → sign up with GitHub → **Add New Project** → import the repo.
2. Framework preset **Other**. No build command. Do not set a root directory.
3. Add env vars: `DATABASE_URL` (Neon direct), `BOT_TOKEN`, `ADMIN_IDS`,
   `DEST_CHANNEL_ID_SCHOOL`, `DEST_CHANNEL_ID_UNIVERSITY`, `TELETHON_API_ID`,
   `TELETHON_API_HASH`, `SIMURG_WEBHOOK_SECRET`, `ENVIRONMENT=production`.
4. Deploy, then visit `https://<project>.vercel.app/api/setup?secret=<SECRET>`
   once to register the webhook. `&action=info` inspects, `&action=delete` rolls
   back to Actions polling.

Expected outcome: buttons respond in **seconds**; posts still appear within
~30–60 min via Actions, since publishing needs Chromium and stays there.

### Historical: the Koyeb plan (do not pursue unless Vercel fails)

### What is already built and on `main`

| Item | Where | State |
|---|---|---|
| Webhook entrypoint | `src/routines/bot_webhook.py` | done |
| Slim image (no Chromium) | `Dockerfile.bot` | done |
| Mode switch | `_drain_admin_updates` in `src/routines/batch_processor.py` | done |
| CI proof it builds/imports | `.github/workflows/botcheck.yml` | done |

Verified on Actions (not assumed), run `31296034168`:
`Dockerfile.bot` builds at **190 MB** (cap is 2GB), `build_app()` constructs
inside the image, `/health` and `/tg/<secret>` both register, and
playwright/telethon/numpy/Pillow/openai/apscheduler are all absent.
Run `31296036298` confirms the new `getWebhookInfo` check did **not** disturb
polling: with no webhook set it drained normally (`admin_updates_drained
handled=1`) and never logged `webhook_info_failed`.

Still unverified, because it needs the account: the webhook path itself
(`set_webhook`, a real tap arriving over HTTPS, `delete_webhook` on shutdown).

**Change from the original plan (step 3).** `drain.yml` was *not* rewired to
publish-only. Instead `_drain_admin_updates` calls `getWebhookInfo` first and
returns early (`drain_skipped_webhook_active`) when a webhook is set. Reasons:

- it switches automatically in **both** directions, so the rollback in step 6 is
  just `bot.delete_webhook()` — no workflow edit, no revert commit
- it removes the §5-class trap where a stale webhook silently breaks all polling:
  now the drain *says* why it isn't polling
- `getWebhookInfo` is a genuine read (unlike `getUpdates`, it confirms nothing),
  so this is safe under the §5 rule

`batch.yml` keeps `SIMURG_SKIP_DRAIN=true`; `drain.yml` keeps its cron and the
shared concurrency group, unchanged.

### Still blocked on
The user must sign up at koyeb.com (GitHub login) and report **whether it demands
a credit card** in Kazakhstan. Koyeb docs say no card for most regions but they
have been tightening anti-abuse. Fallbacks if a card is demanded: Render (no card,
sleeps at 15 min instead of 1 h) or just stay on Actions — the code above works
unchanged on any host that gives an HTTPS URL and a `PORT`.

### Deploy checklist once unblocked

1. Koyeb → Create Service → GitHub → this repo → **Dockerfile path
   `Dockerfile.bot`**, instance `free`, port `8080` (HTTP).
2. Env vars: `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, `TELETHON_API_ID`,
   `TELETHON_API_HASH`, `DEST_CHANNEL_ID_SCHOOL`, `DEST_CHANNEL_ID_UNIVERSITY`
   (the last four are unused by the bot but `Settings` requires them — any valid
   value works), plus `SIMURG_WEBHOOK_SECRET` (long random string) and
   `SIMURG_WEBHOOK_BASE_URL` (the `https://…koyeb.app` URL Koyeb assigns —
   set it after the first deploy and redeploy once).
3. Optional keep-warm: cron-job.org hitting `<url>/health` every ~45 min, to dodge
   Koyeb's 1-hour scale-to-zero and its ~30s cold start.

### Rollback
Stop/delete the Koyeb service. Its `on_cleanup` calls `delete_webhook`, and the
next `drain.yml` run sees no webhook and resumes polling by itself. If the
container died without cleanup, call `deleteWebhook` once by hand:
`curl "https://api.telegram.org/bot$BOT_TOKEN/deleteWebhook"`.

### Verification
Tap Approve → the bot should edit the message within seconds (not minutes) →
`approval_recorded` in Koyeb logs → next `drain.yml` run logs
`drain_skipped_webhook_active` then `publishing_due_opportunities count>0` →
`opportunity_published` → post appears.

---

## 9. Housekeeping

- Branch `diagnose-approvals` is merged into `main` but still exists locally and
  on the remote; safe to delete.
- Local repo has git identity set (`Toplion2010` / user's email) — repo-local only.
- `HANDOFF.md` (this file) is now **committed** to `main`, so it survives a fresh
  clone. Keep it updated in the same commit as the change it describes.

---

## 10. How the user works

- Communicates in short, blunt messages; often mixes Russian and English.
- Wants results, not options — but **do** flag honest limits, they respond well
  to being told what is not possible.
- Cannot be relied on to tap buttons at a specific moment for a test; design
  verification so it works whenever they get to it.
- Has been burned by "it's fixed" claims that weren't. Verify with logs before
  saying anything works, and say plainly when something is still unproven.
