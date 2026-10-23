# Prompt: build the approved doq.world source

Paste everything below the line into a new coding-agent session in this repo.

---

Build doq.world as a Simurg web source. The permission record is
`docs/permissions/doq-world.md`.

**Step 0: check approval before anything else.** Read the permission record.
Go on only if the status line reads APPROVED and the written approval, sender,
date, authorized scope, and production-use decision are recorded there. If any
of those are missing, stop and tell me what is missing. Do not fetch doq.world.

## Where things live

- Web sources: `src/collector/web/sources/<name>.py`, one `WebSource` subclass
  each, registered in `src/collector/web/registry.py`. `sirel.py`, `zhaslink.py`
  and `extracurricularhub.py` are the models to follow.
- Seed labels: `scripts/seed_web_sources.py`.
  Aggregator list: `scripts/validate_scoring_rubric.py`.
- WebItem → post data: `src/collector/web/to_dto.py`.
  Post text: `src/publisher/formatter.py`.
- Simurg cannot run locally. Verify only through dispatched GitHub Actions runs
  and their logs. Unit tests run locally with `pytest tests/`.

## Requirements

1. **Access method.** Look for an official API, feed or structured endpoint first
   (their sitemap, JSON-LD on listing pages, any feed the permission mentions).
   Use polite HTML fetching only if none exists. Keep out of every path their
   robots.txt disallows (`/api/`, `/auth`, `/r/`, `/mcp`, and so on) unless the
   permission explicitly covers it.
2. **Rate.** Requests go one at a time, at least 3 seconds apart. The shared
   `Fetcher` paces requests with `WEB_FETCH_SLEEP_SECONDS` (1 s). Add a
   per-source minimum so doq.world gets 3 s without slowing the other sources.
3. **Frequency.** No more than once every 8 hours. `webscan.yml` runs once a
   day. Add a separate doq.world schedule, but leave it **commented out or
   disabled** until I approve (point 9).
4. **Only new or changed listings.** Reuse the existing seen-check
   (`raw_messages.external_id`). If the sitemap has `lastmod`, use it to spot
   listings that changed and re-fetch only those.
5. **Content.** Build each post only from the opportunity text and retain all
   useful opportunity information present there, including title, organizer,
   deadline, eligibility, cost, format, location, description, and any other
   substantive application details. Do not infer missing facts from page
   metadata, navigation, rankings, prestige ratings, or editorial commentary.
6. **Links.** Never publish or send the doq.world opportunity/listing URL. It
   may be stored only as `page_url`/`source_url`, which admins see. Preserve only
   relevant organizer or registration URLs literally present in the opportunity
   text. A link exposed only by a page button, metadata,
   navigation, JSON-LD, or the source URL is not eligible unless the same URL is
   also present in the opportunity text. If the text contains multiple relevant
   links, preserve them without replacing them with the doq.world URL. If it
   contains no relevant link, render the post with no link; do not invent one,
   fall back to doq.world, or reject the listing solely because it has no link.
   Turn off `to_dto`'s current source-URL fallback for this source.
7. **Dedupe.** Do not make dedupe depend on a link being present. Check that a
   doq.world item matching an opportunity from Telegram, ZhasLink, SIREL or
   ExtracurricularHub is caught when title + an eligible in-text link match,
   and also exercise the best existing link-independent dedupe path for a
   no-link item. Cover both cases with tests and report any limitation rather
   than weakening the no-fallback link rule.
8. **Tests.** Save a small fixture from real listings under `tests/fixtures/web/`.
   Test parsing, opportunity-text-only extraction, link provenance, the no-link
   case, the 3 s pacing and dedupe. Include a regression test
   proving that the doq.world listing URL never enters a rendered post.
   `pytest tests/` must pass.
9. **Dry run first.** Add a dry-run mode to `src/routines/web_collector.py` (and
    as a `webscan.yml` input) that processes the **first 10** listings and
    writes nothing to the database. Dispatch it with `--source doqworld`, and
    for each of the 10 show me:
    - the extracted structured data,
    - the opportunity text used as the source of that data,
    - every retained link and the exact text fragment it came from (or `none`),
    - the dedupe result (new, or a duplicate of which existing opportunity),
    - the rendered Telegram post.
    Then stop. Do not seed the source row, do not enable the schedule, and do
    not ingest anything until I approve the dry run.
10. Open a PR, check that CI passes, and give me a short summary with the
    dry-run output.
