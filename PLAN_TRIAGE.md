# Smarter triage: age-gating, relevance rating, source links, post variety

## Context

The approval pipeline works end-to-end (webhook → instant tap → cron drain → publish).
The problem has shifted from *delivery* to *triage quality*: the admin queue shows a bare
4-line summary with no signal about whether an item is worth reading, and the school
channel can receive age-restricted opportunities.

Four changes:

1. **Age safety.** Nothing 18+ may reach the school channel. No age concept exists today —
   age wording lands in free-text `eligibility` and is never inspected.
2. **Relevance rating.** The operator's profile is CS / AI / hackathons / logic & math /
   entrepreneurship. Art, generic volunteering (a Caspian beach cleanup), and low-substance
   items waste review time — unless they carry real coding or business content. A 1–5
   rating surfaces fit at a glance.
3. **Source link.** No way to open the original post before approving.
4. **Post variety.** Card artwork can repeat by construction, and hackathon captions use a
   layout built for scholarships.

**Decision:** low ratings **sort, never auto-reject**.

> **Scope split.** The separate hackathon *channel* — creating it, routing, secrets, channel
> copy — lives in `PLAN_HACKATHON_CHANNEL.md`. Whether supply needs expanding at all lives in
> `PLAN_SOURCE_AUDIT.md`. Nothing in this plan depends on either, and neither may block it.
> This plan only changes how hackathon posts *look*, not where they go.

> **Status: implemented in commits `e29d7d6` and `7495df0`.** The schema, migrate-first
> workflow, age gate, relevance rating, source links and card variety are in the tree. What
> is **not** recorded anywhere is whether the Verification section below was actually run —
> treat every item in it as unconfirmed until a dispatched Actions run says otherwise.

## Verified facts (checked, not assumed)

- **`Category.Hackathon` already exists** — [enums.py:11](src/core/enums.py#L11), flows
  through `_CATEGORIES` (built from the enum), `#Hackathon` in
  [formatter.py:12](src/publisher/formatter.py#L12), accent in
  [tokens.py:29](src/publisher/design/tokens.py#L29). **No enum or schema change needed.**
- **Permalink data is already in Postgres.** `opportunities.raw_message_id` →
  `raw_messages.telegram_msg_id` + `source_channel_id` → `source_channels.username` /
  `.telegram_id`. Nothing new to collect. `username` is NULL for the 2 private invite-link
  channels ([seed_channels.py:90-91](scripts/seed_channels.py#L90-L91)); `source_channel_id`
  is NULL when `_resolve_channel_id`
  ([worker.py:162-165](src/processor/worker.py#L162-L165)) finds no match. Formatter must
  be NULL-safe.
- **No test suite exists** — zero `test_*.py` files in the repo.
- Migration chain head is **`0004_add_last_seen_msg_id`**.

## Reuse, don't rebuild

- `OpportunityDTO` + `_SYSTEM_PROMPT`
  ([extractor.py:18-158](src/processor/extractor.py#L18-L158)) — Pydantic validation and
  `response_format={"type":"json_object"}` already in place.
- `_bold`, `_split_paragraphs`, the hook line and the tag footer in
  [formatter.py](src/publisher/formatter.py) — the hackathon layout reuses all of them.

---

## Step 0 — Migration must land BEFORE the code (deploy-order hazard)

Vercel auto-deploys on every push to `main`. `alembic upgrade head` currently runs **only**
inside `batch.yml` (cron 5×/day). So a plain push gives ~60 seconds of new ORM code against
an un-migrated Neon: every `repo.get(opp_id)` from the webhook raises
`UndefinedColumnError` → 500 → Telegram retries → taps stop applying. That is the exact
failure class this project already spent days fixing.

All four columns are **nullable additions**, so migrate-first is backward compatible — the
currently deployed code simply ignores them.

- New `.github/workflows/migrate.yml`, `workflow_dispatch` only, same concurrency group
  `simurg-runtime`, running `alembic upgrade head` with the existing secret set.
- Execution order is part of this plan, not a footnote: **commit the migration alone →
  dispatch `migrate.yml` → confirm success → only then push the application code.**

## Step 1 — Schema: four columns (migration `0005`)

`src/db/models/opportunity.py`, all nullable:

| Column | Type | Meaning |
|---|---|---|
| `relevance` | `Integer \| None` | 1–5 profile fit |
| `relevance_reason` | `String(120) \| None` | short phrase shown in queue |
| `min_age` | `Integer \| None` | minimum age stated in the source |
| `source_url` | `Text \| None` | denormalized `t.me/…` permalink |

`String(120)` deliberately matches the prompt's 120-char cap so schema and business rule
cannot silently drift.

New `src/migrations/versions/0005_add_triage_fields.py`, `down_revision = "0004"`, plain
`op.add_column` — no ENUM work, so no dialect branching.

`source_url` is denormalized on purpose: a join would require eager-loading
`raw_message → source_channel` on every queue query, and a missed `selectinload` surfaces
as `MissingGreenlet` at runtime (already hit once in
[scheduler.py](src/publisher/scheduler.py)). Compute once at insert.

## Step 2 — Extraction: age + relevance

**`src/core/config.py`** — tunable without a code edit:

```python
RELEVANCE_PROFILE: str = (
    "computer science, software engineering, AI/ML, data science, hackathons, "
    "competitive programming, math and logic olympiads, robotics, "
    "entrepreneurship, startups, business and product"
)
```

**`src/processor/extractor.py`** — new `OpportunityDTO` fields and prompt bullets:

- `min_age`: integer or null, **only when the text states an age floor**. Never inferred
  from education level.
- `relevance`: 1–5 against `{RELEVANCE_PROFILE}`:
  - **5** squarely in profile · **4** adjacent STEM/quant/accelerator · **3** general but
    with real tech or business content · **2** other-field, little tech/business ·
    **1** clearly off-profile (art, music, sports, generic charity or cleanup volunteering)
  - Override rule: judge by **content, not label** — "build an app for an NGO" is 3–4,
    "collect trash from the Caspian shore" is 1.
- `relevance_reason`: ≤ 120 chars.

**Token budget is a hard constraint, not a note.** Current usage is ~2.5k tokens ×
~35 messages/day ≈ 87k against Groq's free 100k/day ceiling — documented at
[config.py:60-63](src/core/config.py#L60-L63). The added rubric must stay **≤ 150 tokens**;
anything larger pushes past the cap and starts silently dropping the day's tail. If logs
show daily 429s after this ships, the lever is `MAX_MESSAGES_PER_RUN: 7 → 6`.

**Validator policy differs per field, deliberately:**

- `relevance` out of 1–5 → **`None` + `logger.warning("relevance_out_of_range")`**, not a
  clamp and not a hard error. Clamping 9→5 hides a broken prompt; raising is worse —
  `ExtractionResult` validates the whole `{"opportunities": [...]}` object, so one bad
  integer fails the **entire message**, burns 6 tenacity retries
  ([extractor.py:177-184](src/processor/extractor.py#L177-L184)) and loses every
  opportunity in it. `None` keeps the item, sorts it last, and leaves a greppable signal.
- `min_age` outside 5–99 → **`None` + log**. Never clamp — 150→100 would fabricate a
  plausible-looking age gate out of a model error.

## Step 3 — Age parser (a real parser, not a regex pile)

New `src/processor/age.py`, `parse_min_age(text: str) -> int | None`. A naive
`\b(1[89]|2[01])\s*(years|лет)` gets "applicants aged 14–18" wrong (must be **14**, not 18),
which is the difference between correctly gating and needlessly blocking school posts.

Order matters — **ranges are checked before floors**, and the range's *lower* bound wins:

1. **Ranges** → lower bound: `ages 18-25`, `14–18 years`, `от 18 до 25 лет`, `18-25 лет`
2. **Floors**: `18+`, `18 or older`, `18 years old and above`, `at least 18`,
   `minimum age 18`, `от 18 лет`, `старше 18`, `не младше 18`
3. **Words** → 18: `adults only`, `совершеннолетн*`

Negative guards, each with a test:
- 1–2 digit match bounded by `\b`, so `2018` in "Founded in 2018" can never match
- reject matches adjacent to currency, `%`, `grade`, `class`, `since`, `©`
- result outside 5–99 → `None`

Called over the **full normalized source text: title + description + raw text +
eligibility** — a title like "AI Fellowship 18+" with a silent description is a real case.

**`src/processor/pipeline.py`**, right after audience resolution at
[pipeline.py:73-78](src/processor/pipeline.py#L73-L78): take
`max(llm_min_age, parsed_min_age)`, and if ≥ 18 map `both → university` and
`school → university`, logging `age_gate_applied` with old and new audience. The
`school → university` inversion is deliberate: school-only *and* 18+ is a contradiction in
the source, and downgrading beats dropping — the admin still sees it and can reject.

## Step 4 — Source permalink

`_resolve_channel_id` ([worker.py:162-165](src/processor/worker.py#L162-L165)) already
queries the `SourceChannel` row; widen it to return the row, not just the FK, and pass it
into `pipeline.run(...)`.

New `src/processor/source_link.py`:

```
username present  ->  https://t.me/<username>/<msg_id>
username NULL     ->  https://t.me/c/<bare_telegram_id>/<msg_id>   (opens for members only)
channel NULL      ->  None
```

Set on the `Opportunity(...)` construction at
[pipeline.py:84-109](src/processor/pipeline.py#L84-L109). The `t.me/c/` form stays labelled
"Original post" — Telegram itself handles the access check.

No backfill: old rows keep `source_url = NULL` and the queue omits the line.

## Step 5 — Queue UI

**`src/db/repositories/opportunity.py`** — `get_pending` orders by `created_at ASC` today.
Change to:

```sql
ORDER BY (relevance IS NULL) ASC, relevance DESC, created_at ASC
```

Not `NULLS LAST`: this form is portable across SQLite and Postgres with no dialect branch,
and puts pre-migration rows at the end.

**`src/bot/routers/queue.py`** — replace the card in `_show_queue_page`
([queue.py:96-100](src/bot/routers/queue.py#L96-L100)). Routing and age come **before**
deadline, because destination and eligibility decide the tap; the deadline rarely does:

```
⭐⭐⭐⭐☆ 4/5 · Strong AI/ML fit
📌 <b>{title}</b>
🏷 Hackathon · 🔞 18+
📍 🎓 University
📅 {deadline}
🔗 <a href="{source_url}">Original post</a>
```

`relevance_reason` is a scan-in-one-second fragment, never a sentence — the prompt asks for
a phrase and the 120-char column enforces it. Stars omitted when `relevance` is NULL;
`🔞 18+` only when `min_age >= 18`; source line only when `source_url` is set. Same
treatment in `_send_opportunity_card`
([queue.py:38-57](src/bot/routers/queue.py#L38-L57)).

**Bug fixed in passing:** `_send_opportunity_card` (line 56) and `preview_opportunity`
(line 133) send `format_opportunity()` HTML **without** `parse_mode="HTML"`, so the admin
sees raw `<b>` tags today. One-line fix, directly in the way of this work.

**Vercel constraint:** `src/bot/**` ships in the serverless bundle against the slim
[requirements.txt](requirements.txt). `queue.py` must not import anything from
`src/processor/**` — `source_url` and `relevance` are plain columns, so it doesn't need to.

## Step 6 — Card artwork can repeat, by construction

`_compose_prompt` ([live_background.py:153-197](src/publisher/live_background.py#L153-L197))
builds every image from four parts. Three rotate randomly; the fourth does not:

| Part | Source | Variants |
|---|---|---|
| style | `random.choice(_STYLES)` | 16 |
| mood | `random.choice(_MOODS)` | 10 |
| palette | `random.choice(_PALETTES)` | 13 |
| **scene** | `_SCENE_HINTS[category]` | **1, fixed** |

Every hackathon renders *"a laptop glowing with lines of code against a futuristic city
skyline"* ([live_background.py:111](src/publisher/live_background.py#L111)) — same subject,
different paint. And `random.choice` keeps no history: across 2080 combinations, the
birthday bound puts the chance of at least one exact style/mood/palette repeat at
**~45% within 50 posts**. A repeated triple on top of an identical scene is two
indistinguishable cards.

**Fix 1 — scenes become lists.** `_SCENE_HINTS: dict[str, list[str]]`, 8 entries for
`Hackathon` (a team hunched over glowing screens in a dark hall — no faces, per
`NEGATIVE_PROMPT`; a wall of sticky notes and diagrams; a giant countdown clock above a
stage; server racks with light trails; an abstract circuit-board landscape; a trophy resting
on a keyboard; a night-time open-plan office seen from above; a neon still life of energy
drinks and laptops). Other categories get 3–4 each; `_DEFAULT_SCENE_HINT` becomes a list too.

**Fix 2 — selection becomes deterministic on `opp.id`, not random.** Strides coprime to each
list length:

```python
style   = _STYLES  [(opp.id *  7) % len(_STYLES)]     # gcd(7, 16) = 1
mood    = _MOODS   [(opp.id *  3) % len(_MOODS)]      # gcd(3, 10) = 1
palette = _PALETTES[(opp.id *  5) % len(_PALETTES)]   # gcd(5, 13) = 1
scene   = scenes   [(opp.id * 11) % len(scenes)]      # gcd(11, 8) = 1
```

Consecutive ids differ on **all four** axes, and the full tuple repeats only after
`lcm(16, 10, 13, 8) = 1040` posts. Randomness was never the feature here — it was the
collision source. Determinism also makes this unit-testable, which `random.choice` is not.

Guard for `opp.id is None` (a card rendered before flush, as `scripts/render_preview.py`
can do) — fall back to `random.choice` there.

**Blast radius:** this changes artwork for **all 16 categories**, not just hackathons —
keeping two code paths in one function would be worse. Expect every category to look more
varied and somewhat different from today.

## Step 7 — Hackathons get their own caption

`format_opportunity` ([formatter.py:47](src/publisher/formatter.py#L47)) is one layout for
all 16 categories. For a hackathon the reader's questions are ordered differently: prize
pool and registration deadline first, format (online/onsite) next.

Add `_format_hackathon(opp)` selected on `opp.category == Category.Hackathon`, reusing the
same `_bold` / `_split_paragraphs` / hook-line / tag-footer helpers:

```
🔥 hooks
✨ <b>{title}</b>
💰 Prize pool: {rewards}
⏰ Registration closes: {deadline}
📍 Format: {location} · {duration}
👤 Who can enter: {eligibility}
📝 About: {description}
🔗 Register → {apply_link}
#Hackathon #SimurgOpportunities
```

**No new LLM fields.** The Groq budget is already at ~98k of 100k (Step 2), so this is a
reordering and relabelling of fields the extractor *already* produces — `rewards` → prize
pool, `deadline` → registration closes, `location` + `duration` → format. Zero token cost.
Team size and tech stack would need new extraction and are deliberately left out.

Every row stays NULL-safe and is omitted when empty, exactly like the current formatter.
`formatter.py` is already imported by `queue.py` inside the serverless bundle, so this must
stay dependency-free — it is.

## Step 8 — Tests (new: the project has none)

Minimal `pytest` setup plus a `test` job in CI. Scoped to pure functions only — no DB, no
network, so it runs in seconds and needs no secrets:

- `tests/test_age.py` — the full table from Step 3, including every negative case:
  `"Founded in 2018"`, `"applicants aged 14–18" → 14`, `"Participants 18-25" → 18`,
  `"$18,000 grant"`, `"grade 18"`, `"18 или старше" → 18`, `"" → None`.
- `tests/test_source_link.py` — public username, NULL username → `t.me/c/`, NULL channel →
  `None`.
- `tests/test_queue_render.py` — the card formatter with `relevance=None`,
  `source_url=None`, `min_age=None`, and a fully populated row.
- `tests/test_prompt_variety.py` — assert that ids 1..20 produce 20 distinct
  (style, mood, palette, scene) tuples, that consecutive ids differ on all four axes, and
  that `opp.id = None` still returns a valid prompt.
- `tests/test_hackathon_format.py` — hackathon layout with every optional field NULL, and
  a check that a non-hackathon category still routes to `format_opportunity`.

---

## Verification

1. **Migrate first.** Dispatch `migrate.yml`, confirm `alembic upgrade head` succeeds on
   Neon. Only then push application code. (Step 0 — skipping this breaks the live bot.)
2. **Unit tests** green in CI — especially the age table.
3. **CI regression** — `vercelcheck.yml` and `botcheck.yml` stay green, proving the slim
   dependency set is unchanged and `Settings()` still boots with fake env.
4. **Extraction** — dispatch `batch.yml`; logs should show populated `relevance` /
   `min_age`, any `age_gate_applied`, and **no** `relevance_out_of_range`,
   `min_age_out_of_range`, or Groq 429s. A 429 burst means the prompt grew too far — drop
   `MAX_MESSAGES_PER_RUN` to 6.
5. **Queue** — `📋 View Queue` in Telegram: stars present, best-first ordering, working
   `Original post` link, `🔞 18+` badge, and formatted (not raw-tag) `👁 Preview`.
6. **Age gate, targeted** — confirm a source post with an explicit `18+` produces
   `audience = university`, never `school` or `both`; and that a `14–18` post is **not**
   gated.
7. **Artwork variety** — dispatch `preview.yml` with `count: 8` and look at the artifact.
   Eight visibly different scenes, not eight recolours of one laptop. This is the only way
   to check it: the images are model output, and a unit test can prove the prompts differ
   but not that the pictures do.
8. **Hackathon caption** — confirm the new layout renders with prize and deadline on top,
   and that a row with `rewards = NULL` simply omits that line.
9. **Regression** — one unattended `drain.yml` cron cycle still approves and publishes.

Per [MEMORY.md](../../.claude/projects/c--Users-seymu-Simurg/memory/MEMORY.md), this project
cannot be run locally beyond migrations and the new unit tests — everything else is verified
via dispatched GitHub Actions runs and their logs.

## Out of scope

- **The hackathon channel** — separate plan, see the scope note at the top.
- Backfilling `source_url` / `relevance` for existing rows.
- Auto-rejection based on rating (explicitly declined — sort only).
- `MAX_MESSAGES_PER_RUN = 7` vs ~120-fetched backlog — separate throughput problem, touched
  here only as a 429 mitigation lever.
