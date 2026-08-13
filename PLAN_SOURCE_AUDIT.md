# Source audit: where do online hackathons actually come from?

## Context

A dedicated hackathons channel (`PLAN_HACKATHON_CHANNEL.md`) promises "new ones daily".
Supply currently comes from **~40 Telegram channels only**, seeded in
[seed_channels.py:45-92](scripts/seed_channels.py#L45-L92). Nobody has measured how many
hackathons that actually yields per week, or how many of the world's online hackathons it
misses.

This plan answers two questions **in order**, and the first is far cheaper than the second:

1. What does Simurg already find? (free — the database knows)
2. Which external platforms would add *genuinely new* opportunities? (research + build)

## The constraint that dominates everything

**Simurg's collector is Telegram-only, by schema.**

- `source_channels.telegram_id` — `BigInteger, nullable=False, unique=True`
  ([source_channel.py:11-13](src/db/models/source_channel.py#L11-L13))
- `raw_messages.source_channel_id` — FK to that table
- Both collector paths ([fetcher.py](src/collector/fetcher.py), [handlers.py](src/collector/handlers.py))
  are Telethon; the cursor is `last_seen_msg_id`, a Telegram message id

Devpost, MLH, HackerEarth and Kaggle do not fit this shape. Adding any of them means a
**second collector type**: a source model that isn't keyed on a Telegram id, an HTTP/RSS
fetch path, its own cursor semantics, and dedup that works *across* source types — the
current dedup hashes `title + apply_link`
([deduplicator.py:45-47](src/processor/deduplicator.py#L45-L47)), which is actually the one
part that would survive unchanged.

That is a project on the scale of both current plans combined. It should not be started on
a hunch — hence Phase 1 below.

---

## Phase 1 — Ask the database first (zero tokens, zero new code)

Run through `diagnose.yml`, which is already read-only and dispatch-only. No LLM calls, no
Telethon, no cost.

**1a. Current hackathon supply rate**

```sql
SELECT date_trunc('week', created_at) AS week, count(*)
FROM opportunities
WHERE category = 'Hackathon'
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
```

Decides whether the channel has enough supply to justify itself. If the answer is 3/week,
"new ones daily" is a promise the pipeline cannot keep, and the pinned copy must change
before anything else does.

**1b. Which Telegram channels actually produce hackathons**

```sql
SELECT sc.username, sc.name, count(*) AS hackathons
FROM opportunities o
JOIN raw_messages rm ON rm.id = o.raw_message_id
JOIN source_channels sc ON sc.id = rm.source_channel_id
WHERE o.category = 'Hackathon'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

Two findings for the price of one: which channels earn their keep, and — from the tail —
which of the ~40 contribute nothing and are just burning the
`MAX_MESSAGES_PER_RUN = 7` budget every run.

**1c. Online vs onsite split — by keyword, not by `GROUP BY location`**

A plain `GROUP BY location` produces a tidy-looking but useless histogram: the column is
free text and holds `Online`, `Worldwide`, `Remote`, `Online / New York`, `Hybrid`, `NULL`
and a hundred city names, each as its own row. Bucket it instead, across
`location || description || eligibility`:

```sql
SELECT
  CASE
    WHEN t ~* '(online|remote|virtual|worldwide|anywhere)'
     AND t ~* '(onsite|on-site|in.person|physical|venue)' THEN 'ambiguous/hybrid'
    WHEN t ~* '(online|remote|virtual|worldwide|anywhere)' THEN 'online'
    WHEN t ~* '(onsite|on-site|in.person|physical|venue)'  THEN 'onsite'
    ELSE 'unstated'
  END AS mode, count(*)
FROM (
  SELECT coalesce(location,'') || ' ' || coalesce(description,'') || ' ' ||
         coalesce(eligibility,'') AS t
  FROM opportunities WHERE category = 'Hackathon'
) s GROUP BY 1 ORDER BY 2 DESC;
```

Read `ambiguous/hybrid` and `unstated` as their own answer — a large `unstated` bucket means
the extractor isn't capturing the mode at all, which is a different problem from a supply
gap and would be fixed in the prompt, not with a new source.

The channel copy promises online *and* onsite. If 90% are local events in one country, the
promise is wrong.

**1d. Classifier check for CTF / datathon** (also gates the hackathon plan's Step 0)

```sql
SELECT category, count(*), min(title) FROM opportunities
WHERE title ILIKE '%ctf%' OR title ILIKE '%datathon%'
   OR title ILIKE '%capture the flag%' OR title ILIKE '%case competition%'
GROUP BY 1 ORDER BY 2 DESC;
```

**1e. Cross-source overlap — currently IMPOSSIBLE to measure, and that must be fixed first**

The obvious queries do not work, neither counting distinct `similarity_hash` (that measures
rows that were *stored*, not collisions) nor grouping by
`count(DISTINCT rm.source_channel_id) > 1`. Both return ≈ nothing, and for a misleading
reason: **deduplication happens before insert.**

```python
if await self._deduplicator.check(dto, self._opp_repo):
    continue            # pipeline.py:117-118 — no logger call on this path
```

A hackathon arriving from a second Telegram channel never becomes a row, and the `continue`
emits no log line. The collision leaves **no trace in the database and none in the logs**.
So today the overlap between the ~40 Telegram sources is not merely unmeasured — it is
unmeasurable.

**Prerequisite, one line of code:**

```python
if await self._deduplicator.check(dto, self._opp_repo):
    logger.info("duplicate_skipped", raw_id=raw.id,
                source_channel_id=raw.source_channel_id, title=dto.title)
    continue
```

Zero token cost, zero risk, and it makes overlap countable from the next batch run onward.
It cannot answer the question retroactively — a week of data is needed before 1e means
anything, so **ship this line first and run the rest of Phase 1 while it accumulates.**

The resulting ratio — duplicates skipped ÷ opportunities created — is the baseline every
external platform must beat. If the existing Telegram sources already collide heavily with
each other, a 41st source of any kind has predictably low marginal yield.

> **Phase 1 may end the project.** If it shows healthy weekly volume with good online
> coverage, no external source is needed and this plan stops here. That is a real possible
> outcome and the cheapest one.

### Required Phase 1 output — fill this in, then decide

The decision must be a written table, not an impression:

```
CURRENT SUPPLY
├── Hackathons / week ............  ?
├── Online % .....................  ?
├── Onsite % .....................  ?
├── Ambiguous or unstated % ......  ?
├── Duplicate-skipped ratio ......  ?   (needs the 1e log line + ~1 week)
├── Sources producing ≥1 .........  ? of ~40
└── Sources producing 0 ..........  ?

SUPPLY GAP → do we need external sources?   YES / NO
```

Worked examples of how to read it:

- `42/week · 71% online · 8 sources carry 95% of supply · 18% duplicated`
  → **NO.** Supply is fine. Prune the dead sources instead and stop here.
- `7/week · 29% online · 6 useful sources · 41% duplicated`
  → **YES.** Audit Devpost and lablab.ai.

## Phase 2 — Rank candidate platforms (research, no code)

Only if Phase 1 shows a supply gap.

### Preliminary ranking — ALL ROWS ARE HYPOTHESIS

Nothing in this table has been checked. It is a shortlist to verify, not a finding. Two
columns are separated on purpose, because they fail differently:

- **Volume / audience** — reasonably stable guesses; wrong by a factor, not a category.
- **Collection method** — pure hypothesis, and the column that decides effort. A documented
  API is a day's work; an undocumented JSON endpoint is a day's work that breaks silently in
  three weeks when the markup is redesigned. Terms of service and `robots.txt` can also
  forbid the whole approach outright, turning "low effort" into "not happening".

**Verify the collection method before believing any effort estimate**, and record the answer
as Verified / Refuted next to each row.

| Source | Online volume | International | Collection method (**hypothesis**) | Effort *if true* | Verdict |
|---|---|---|---|---|---|
| **Devpost** | very high | yes | JSON behind the public hackathon list | low | **Tier 1** — highest-yield candidate; most company-run online hackathons list here |
| **lablab.ai** | high, all online | yes | structured pages | low | **Tier 1** — pure AI hackathons, near-perfect fit for the CS/AI profile |
| **MLH** | medium | yes, student-focused | structured season page | low | **Tier 2** — high quality, but heavily in-person and US/EU-weighted |
| **HackerEarth** | high | open, India-weighted | structured challenge list | low | **Tier 2** — good volume; verify eligibility isn't region-locked |
| **Kaggle** | high | yes | official documented API | low | **Tier 2**, but these are competitions, not hackathons — likely classify as `Competition` and route elsewhere |
| **DoraHacks / ETHGlobal / Devfolio / TAIKAI** | medium | yes | varies | medium | **Tier 3** — web3-heavy niche; only if that audience matters |
| **Unstop / Hack2skill** | very high | often **India-only** | structured | low | **Tier 3** — volume is real, but eligibility filtering is the whole job |
| **Hackathon.com** | high listing count | mixed | scraping | medium | **Tier 4** — aggregator, historically stale and duplicated |
| **Luma** | high events, low signal | mixed | search-based | high | **Tier 4** — separating hackathons from everything else is the hard part |
| **Company communities** (Google, MS, AWS, NVIDIA) | medium | yes | none uniform | high | **Tier 4** — mostly announced on Devpost anyway; covered transitively by Tier 1 |
| **University pages** | low each | no | none | very high | **Skip** — per-site scrapers, constant breakage, tiny yield |
| **Discord** | medium | yes | needs a Discord bot | very high | **Skip for now** — a third collector type and a new always-on process |

Rationale for the shape of this table: **two Tier-1 sources probably capture most of the
achievable gain.** Devpost is where company-run online hackathons are announced, and
lablab.ai is narrow but perfectly aligned with the profile. Everything below Tier 2 is
either niche, region-locked, or transitively covered.

### The measurement that actually decides it

Volume is a vanity metric. The number that matters is **unique yield**: opportunities a
source produces that Simurg would not otherwise see.

Do this without building anything:

1. Pull one week of hackathons from a candidate source **by hand** (~20 entries is enough).
2. Compute Simurg's own dedup hash for each — `sha256(normalize(title) + normalize(apply_link))`,
   the exact function in [deduplicator.py:45-47](src/processor/deduplicator.py#L45-L47).
3. `SELECT count(*) FROM opportunities WHERE similarity_hash IN (...)`.
4. Unique yield = misses ÷ total.

A source at 1000 listings and 95% overlap is worth less than one at 40 listings and 80%
unique. Twenty hand-collected rows answer this in an afternoon; a built integration answers
it in a week and costs a rewrite if the answer is bad.

**Two thresholds, both required, decided now so neither is rationalised later:**

```
BUILD  only if   unique yield ≥ 30%
           AND   ≥ 5 genuinely new, relevant hackathons per week
```

The second one exists because a percentage alone can be won on a tiny source: 8 listings a
week at 80% unique is a beautiful ratio and about six new hackathons a month — nowhere near
enough to justify a second collector type, an HTTP fetch path, and a scraper that will need
repairing every time the site is redesigned. "Relevant" means it would actually be approved:
online or accessible, open to students, in profile.

## Phase 3 — Build (only for sources that clear the threshold)

Sketch only; not designed until Phase 2 produces a winner.

- `sources` table replacing the Telegram-specific assumption: `kind` (`telegram` | `http`),
  `identifier`, `cursor` (opaque per kind), `active`
- `src/collector/http_fetcher.py` beside the Telethon one, emitting the **same payload dict**
  the pipeline already consumes: `{telegram_msg_id, channel_id, text, received_at, media_path}`
  ([fetcher.py:153-178](src/collector/fetcher.py#L153-L178)) — renamed, but shape preserved,
  so `processor/` needs no changes at all
- `source_url` (from the triage plan) generalises from `t.me/…` to any origin URL — it was
  already designed as free text
- Rate limiting and `robots.txt` compliance per source; a cached ETag/Last-Modified cursor
- **Token cost check before shipping:** every new source multiplies extraction volume, and
  Groq's free tier is already at ~87k of 100k tokens/day. A high-volume source without
  filtering *at fetch time* would blow the budget on day one. Structured sources have an
  advantage here — a Devpost entry already has title, deadline and link as fields, so it may
  need cheaper extraction, or none.

---

## Verification

1. Phase 1 queries run via `diagnose.yml`; results recorded in this file.
2. An explicit written decision: is there a supply gap, yes or no?
3. If yes: unique-yield measured by hand for the top 2 candidates, against the 30% threshold.
4. Only then does Phase 3 get its own plan.

## The stop rule

> **No external collector is built unless Phase 1 demonstrates a supply gap AND Phase 2
> demonstrates both sufficient unique yield (≥ 30%) and sufficient weekly volume (≥ 5 new
> relevant hackathons/week).**

This exists to guard against the standard failure mode, which is not technical: finding an
interesting API and therefore deciding an integration must be written. An available endpoint
is not evidence of a need. Phase 1 is the evidence, and it is allowed to say no.

## Relationship to the other plans

Three independent decisions, deliberately not entangled:

| Plan | Decides |
|---|---|
| `PLAN_TRIAGE.md` | quality of what is already found |
| `PLAN_HACKATHON_CHANNEL.md` | where `Hackathon` gets published |
| `PLAN_SOURCE_AUDIT.md` | whether supply needs expanding at all |

- **`PLAN_TRIAGE.md`** — fully independent. This plan must never block it.
- **`PLAN_HACKATHON_CHANNEL.md`** — Phase 1a/1c/1d **gate the channel copy**, not the code.
  The routing can ship without this; the sentence "new ones daily" cannot. Query 1d is the
  same one that plan's Step 0 requires, so run it once and use it twice.
