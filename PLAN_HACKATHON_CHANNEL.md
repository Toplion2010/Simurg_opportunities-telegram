# Simurg Hackathons — a dedicated channel

## Context

Simurg publishes to two channels today, split by audience: `DEST_CHANNEL_ID_SCHOOL` and
`DEST_CHANNEL_ID_UNIVERSITY`. Hackathons are the operator's highest-interest category and
currently sit mixed in with scholarships and internships in both.

This plan adds a **third channel that is category-routed, not audience-routed**, and moves
hackathons into it exclusively.

**Decision already taken:** hackathons publish to the hackathon channel **only** — they
leave school and university entirely.

> **Prerequisite, not a dependency.** The triage plan (`PLAN_TRIAGE.md`) is independent.
> This one can ship before, after, or without it. If the triage plan ships first, the
> hackathon *caption* format will already exist and these posts will look right on day one.

> **Supply gate.** `PLAN_SOURCE_AUDIT.md` Phase 1 must run before the channel copy is
> published. It measures how many hackathons the ~40 Telegram sources actually yield per
> week and what fraction are online. The routing code below can ship regardless — but the
> promise *"new ones daily"* cannot be pinned until a query proves it. Its query 1d is the
> same one Step 0 needs, so run it once.

## Manual setup — do this BEFORE any code ships

Hackathon-only routing removes the fallback: if the channel is wrong or the bot cannot post,
`publish()` raises `PublishError` ([sender.py:75-76](src/publisher/sender.py#L75-L76)), the
item never publishes, **and every drain retries it every 10 minutes forever** while
`notify_admins` messages the admin each cycle. So the channel must be real and working
first.

1. Create the Telegram channel (public, so it gets a `@handle`).
2. Add the bot as an **administrator** with *Post Messages* permission.
3. Get the numeric chat id — forward any channel post to `@userinfobot`, or read it from the
   bot's logs. It looks like `-100…`.
4. Add it as a **GitHub Secret**: `DEST_CHANNEL_ID_HACKATHON`.
5. Set the same variable in **Vercel** project settings — `Settings()` is constructed at
   cold start in [api/index.py:64](api/index.py#L64), and while the webhook never publishes,
   keeping the two environments identical avoids a boot-time surprise later.

> The order is: channel → bot admin → secret → **then** code. `/setup hackathon` is the
> *last* step, not the first — it configures nothing, it only posts welcome messages into an
> already-configured channel ([setup.py:92-104](src/bot/routers/setup.py#L92-L104)).

## Step 0 — Check the classifier against real data FIRST

The pinned copy promises CTFs and datathons, and the whole design assumes the LLM labels
them `Category.Hackathon`. That is probable, not verified — and if a datathon is classified
`Competition` it silently goes to the wrong channel.

Do **not** verify this by running 30–50 fresh examples through the classifier: at ~2.5k
tokens per extraction that is ~125k tokens against a 100k/day Groq ceiling, which would
consume a full day's budget and stall collection.

Ask the database instead — it already holds thousands of classified rows, at zero token cost:

```sql
SELECT category, count(*), min(title)
FROM opportunities
WHERE title ILIKE '%ctf%' OR title ILIKE '%datathon%'
   OR title ILIKE '%capture the flag%' OR title ILIKE '%case competition%'
   OR title ILIKE '%coding %' OR title ILIKE '%robotic%'
GROUP BY category ORDER BY 2 DESC;
```

Run it through `diagnose.yml`. The result decides the routing set **before** any code is
written: if datathons land in `Competition`, either the routing includes `Competition` or
the pinned post drops the promise. Do not ship with this unresolved.

## Step 1 — Config

**`src/core/config.py`** — `DEST_CHANNEL_ID_HACKATHON: int = 0`.

Optional with a sentinel default on purpose: `vercelcheck.yml` and `botcheck.yml` boot
`Settings()` with fake env and no such variable, and a bare `int` (like the two existing
`DEST_CHANNEL_ID_*` fields) would make both CI checks fail immediately. That is also why
the misconfiguration check below lives in the publishing entrypoints and **not** in
`Settings` — both CI checks run with `ENVIRONMENT: production`, so a production-gated
validator inside `Settings` would fail them.

## Step 2 — Routing, declarative

**`src/publisher/sender.py`** — replace `_resolve_targets(audience)` with
`_resolve_targets(opp)`, driven by a table rather than a chain of `if`s. Simurg is heading
toward more dedicated channels (Competition, Olympiad, Research are all plausible), and a
growing `if` chain is how routing bugs get born:

```python
def _category_channels(self) -> dict[Category, int]:
    """Categories with a dedicated channel. A category listed here NEVER
    falls through to audience routing."""
    return {
        k: v for k, v in {
            Category.Hackathon: self._settings.DEST_CHANNEL_ID_HACKATHON,
        }.items() if v            # unset (0) entries drop out
    }

def _resolve_targets(self, opp: Opportunity) -> list[int]:
    dedicated = self._category_channels().get(opp.category)
    if dedicated:
        return [dedicated]

    if opp.category in _CATEGORY_CHANNEL_VARS:      # configured-but-missing
        logger.error(
            "category_channel_misconfigured",
            category=opp.category.value, opp_id=opp.id,
            detail="falling back to audience routing — this violates the "
                   "category-only routing decision",
        )
    ...existing audience branch unchanged...
```

Adding a channel later is one dict entry plus one secret.

### Why the fallback stays (and why it is not silent)

The obvious alternative — `raise ConfigurationError` when the channel is unset — is worse in
operation, not better. `_resolve_targets` runs **inside** `publish()`, so the exception is
caught by `publish_scheduled` ([scheduler.py:44-48](src/publisher/scheduler.py#L44-L48)):
the row stays `approved`, the next drain retries it 10 minutes later, forever, and
`notify_admins` fires every cycle. A misconfiguration would turn into "hackathons never
publish at all, plus an alert every 10 minutes".

The real defect in the original plan was the word *silent*, not the word *fallback*. Fixed in
two places:

1. **`logger.error` on every fallback**, quoted above — greppable, and visible in the same
   Actions logs already read after each run.
2. **Startup validation** (Step 3) — fails loudly *before* anything publishes, which is
   where a config error belongs.

## Step 3 — Startup validation in the publishing entrypoints

`src/routines/batch_processor.py` and `scripts/drain_and_publish.py` — before any publishing,
check every category that is *meant* to have a dedicated channel actually has one. On a miss:
`logger.error` + a single `notify_admins` message naming the missing variable.

**It must not abort the run.** An unconfigured hackathon channel would otherwise stop
scholarships and internships from publishing too — a config typo in one category taking the
whole pipeline down is a strictly worse failure than the one being prevented.

These two entrypoints are never executed by CI, so this check is free of the `Settings`
problem described in Step 1.

## Step 4 — Channel health check in `diagnose.yml`

The new channel is a hard dependency with no second target, so the failure modes worth
catching before 2 AM are mechanical. Extend `scripts/diagnose_approvals.py` (already
read-only, already dispatch-only) with, per configured destination channel:

- `getChat` — does the id resolve, and is the title what you expect?
- `getChatMember(chat_id, bot_id)` — is the bot an administrator?
- is `can_post_messages` actually true?

Print a table of channel → title → admin? → can post?. This is the check that catches the
stupid failures: a `-100` prefix dropped, the bot added as a member instead of an admin, or
the id of the wrong channel pasted.

## Step 5 — Workflows

`DEST_CHANNEL_ID_HACKATHON` must reach the jobs that publish and the one that diagnoses:

- `.github/workflows/batch.yml` — the batch step's `env:` block
- `.github/workflows/drain.yml` — the drain step's `env:` block
- `.github/workflows/diagnose.yml` — needed by the Step 4 health check

`preview.yml` doesn't publish and needs nothing; the sentinel default keeps it booting.

## Step 6 — `/setup hackathon`

**`src/bot/routers/setup.py`** — add `"hackathon"` to the channels dict at
[setup.py:92-95](src/bot/routers/setup.py#L92-L95).

Note the existing `/setup` sends one generic welcome text to every channel. Worth splitting
per target while here, using the copy below.

## Step 7 — Routing tests

`_resolve_targets` is a pure function of `(Settings, Opportunity)` — no DB, no network — so
this is cheap and belongs in CI. The routing invariant is exactly the kind of rule that a
well-meaning cleanup resurrects six months later:

- `Hackathon` + channel configured → `[HACKATHON]`, and **nothing else**
- `Hackathon` + channel unset (`0`) → audience routing **and** a `category_channel_misconfigured` log
- `Scholarship` / `Internship` → school / university, unchanged, for all three audiences
- `category is None` → audience routing, no crash
- adding an entry to `_category_channels` does not disturb any other category

If the triage plan's `tests/` scaffold already exists, add `tests/test_routing.py` beside it;
otherwise it brings the same minimal pytest setup.

## Step 8 — Existing rows: pending vs already published

Two distinct populations, and the plan must state the intent for both:

- **Pending hackathons approved after the deploy** → the new channel only. This is the
  desired behaviour and needs no migration: `_resolve_targets` is evaluated at publish time,
  not at approval time. Worth an explicit end-to-end check (Verification #6) because it is
  the most likely first real post.
- **Already-published hackathons** → stay where they are. `publish_scheduled` only queries
  `status == approved` ([opportunity.py:74-86](src/db/repositories/opportunity.py#L74-L86)),
  so nothing re-sends them, and they are **not** deleted or migrated. Historical posts stay
  in school/university; only new ones move. Deleting them would break existing links and
  gain nothing.

---

## Channel copy (ready to paste)

### Description — RU (152 chars)

> Хакатоны со всего мира: онлайн и офлайн, с призовыми и travel grants. Каждый день новые, в каждом посте дедлайн и ссылка. Связь: @TOPLION_7

### Description — EN (158 chars)

> Hackathons from around the world: online and onsite, with prize pools and travel grants. New ones daily, deadline and link in every post. Contact: @TOPLION_7

Telegram caps the description field at **255 characters**. Both fit.

### Pinned post — RU

> **🏆 Simurg Hackathons**
>
> Только хакатоны. Онлайн, офлайн, студенческие, корпоративные, CTF и дататоны — со всего мира.
>
> В каждом посте: **кто может участвовать · призовой фонд · дедлайн · ссылка.**
> Отбор делает ИИ, дубли и мёртвые ссылки не проходят.
>
> ➖➖➖➖➖
>
> **🏷 Навигация по хукам**
> Нажми на тег, чтобы отфильтровать.
>
> 🔥 #PremiumOpportunity — крупнейшие хакатоны
> ⚡ #ClosingSoon — регистрация закрывается
> 🚀 #EarlyAccess — регистрация только открылась
> 💰 #PaidOpportunity — призовые, гранты, оплата поездки
> ⭐ #LimitedSpots — ограниченное число команд
> 🌍 #Worldwide — участие из любой страны
> 🏆 #HighlyRecommended — стоит потраченных выходных
>
> ➖➖➖➖➖
>
> ⭐ Стипендии, стажировки, гранты → @simurg_opportunities
> 🎓 Университеты и поступление → @Simurg_Opportunities_University
> ✉️ Связь, реклама, сотрудничество → @TOPLION_7

### Pinned post — EN

> **🏆 Simurg Hackathons**
>
> Hackathons only. Online, onsite, student, corporate, CTFs and datathons — worldwide.
>
> Every post: **who can enter · prize pool · deadline · link.**
> AI-filtered. No duplicates, no dead links.
>
> ➖➖➖➖➖
>
> **🏷 Navigate by hook**
> Tap a tag to filter.
>
> 🔥 #PremiumOpportunity — the biggest ones
> ⚡ #ClosingSoon — registration closing
> 🚀 #EarlyAccess — registration just opened
> 💰 #PaidOpportunity — prize money, grants, travel covered
> ⭐ #LimitedSpots — limited team slots
> 🌍 #Worldwide — enter from any country
> 🏆 #HighlyRecommended — worth the weekend
>
> ➖➖➖➖➖
>
> ⭐ Scholarships, internships, grants → @simurg_opportunities
> 🎓 Universities and admissions → @Simurg_Opportunities_University
> ✉️ Contact, ads, partnerships → @TOPLION_7

Navigation is by **hook**, not by category, because only `Category.Hackathon` routes here —
a category-tag list would contain exactly one working tag.

> ⚠️ **The pinned post promises a navigation system that does not generate itself.** Hooks
> are set **manually** by an admin in [hooks.py](src/bot/routers/hooks.py); the pipeline
> always inserts `hooks=[]` ([pipeline.py:107](src/processor/pipeline.py#L107)). If posts
> are not tagged by hand, every tag in the pinned post returns nothing and the channel looks
> broken to a new subscriber.
>
> Three honest options, pick one before pinning:
> 1. Commit to tapping `🏷 Hooks` on every hackathon before approving (realistic — it is one
>    extra tap on a category you already care about most).
> 2. Cut the hook section from the pinned post and keep only the four-line value
>    proposition: *only hackathons, filtered, worldwide, deadline + prize + eligibility +
>    link.* That is the actual product and it needs no manual work.
> 3. Have the LLM emit hooks — new extraction fields, new token cost, and out of scope for
>    both current plans.
>
> Option 2 is the safe default; option 1 is better if you will genuinely do it.

### Announcement for the two existing channels — REQUIRED

Hackathons will disappear from school and university. Without notice that reads as the
channel getting worse. Post in both:

> **📢 Хакатоны переехали**
>
> Теперь все хакатоны выходят в отдельном канале — так их проще не пропустить, а этот канал остаётся про стипендии, стажировки и гранты.
>
> 👉 @simurg_hackathons

### Promo copy — for posting in student chats and university groups

**RU**

> **Узнаёшь о хакатонах, когда регистрация уже закрыта?**
>
> Отдельный канал только под хакатоны — онлайн и офлайн, студенческие и корпоративные, со всего мира.
>
> В каждом посте: **призовой фонд · дедлайн регистрации · ссылка.**
> Ничего лишнего, только хакатоны.
>
> 👉 @simurg_hackathons
>
> Бесплатно, без спама 🌍

**EN**

> **Finding out about hackathons after registration closes?**
>
> A channel for hackathons only — online and onsite, student and corporate, worldwide.
>
> Every post: **prize pool · registration deadline · link.**
> Nothing else. Just hackathons.
>
> 👉 @simurg_hackathons
>
> Free, no spam 🌍

**KZ**

> **Хакатондар туралы тіркеу жабылғаннан кейін білесің бе?**
>
> Тек хакатондарға арналған арна — онлайн және офлайн, студенттік және корпоративтік, бүкіл әлемнен.
>
> Әр постта: **жүлде қоры · тіркеу дедлайны · сілтеме.**
> Артығы жоқ, тек хакатондар.
>
> 👉 @simurg_hackathons
>
> Тегін, спамсыз 🌍

**One-liner** (stories, bio, chat signatures)

> Хакатоны со всего мира, каждый день, с призовыми и дедлайнами → @simurg_hackathons

### Avatar prompt

Electric green `#00E676`. Cyan `#00D4FF` is taken by Opportunities and gold `#FFD700` by
Universities; terminal green reads as "hackathon" without a word of text.

```
Minimalist logo mark of a stylized Simurgh — a mythical Persian
firebird — rendered as a single continuous luminous line, wings
sweeping upward, the wingtips breaking into small square pixels
as if dissolving into code. Electric terminal green (#00E676)
light trail against a near-black background (#0A0E14), soft outer
glow, faint pixel particles trailing behind. Geometric,
symmetrical, centered composition with generous padding. Flat
vector aesthetic, sharp edges, high contrast, no gradient
background. Modern hacker-tech identity, readable at 64px.
Square 1:1, centered, no text.
```

Negative prompt: `text, letters, watermark, realistic feathers, photorealistic, 3d render, busy background, drop shadow, mockup, frame, border`

Generate at 1024×1024, upload at 512×512, keep the bird inside the middle 80% — Telegram
crops avatars to a circle.

---

## Verification

1. **Manual setup done** — bot is admin, secret set in GitHub and Vercel.
2. **CI** — `vercelcheck.yml` and `botcheck.yml` stay green, proving the sentinel default
   works when the variable is absent.
3. **Positive** — approve a `Hackathon` item; it appears in the new channel and **nowhere
   else**.
4. **Negative** — approve a `Scholarship` item; school/university still receive it.
5. **Guard** — confirm in `batch.yml`/`drain.yml` logs that `DEST_CHANNEL_ID_HACKATHON` is
   actually populated. If it isn't, hackathons silently keep going to school/university —
   working, but not what was intended.
6. **Copy live** — description set, pinned post pinned, avatar uploaded, announcement posted
   in both existing channels.

## Open questions

1. **The channel handle.** All copy above uses `@simurg_hackathons` as a placeholder.
   Replace throughout once the real handle exists.
2. **CTFs and datathons.** The pinned post promises them, but they only land here if the LLM
   assigns `Category.Hackathon`. Probable, not verified. Check the first few posts — if a
   datathon is classified `Competition` it goes to the wrong channel, and the fix is either
   a prompt tweak or dropping the word from the pinned post.
3. **Should `Competition` / `Olympiad` join?** Currently no. Easy to add later — it is one
   more condition in `_resolve_targets`.
