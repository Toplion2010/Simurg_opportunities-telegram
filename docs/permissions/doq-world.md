# doq.world: republication permission

> **STATUS: NOT VERIFIED.** The sender and verification fields below are test
> placeholders. They are not evidence of authorization. Until they are replaced
> with the real sender identity and evidence, Simurg must not fetch or republish
> doq.world listings, and the source stays out of `WEB_SOURCES`.

## Record

| Field | Value |
|---|---|
| Sender | `@love_doq` (TEST PLACEHOLDER, not verified) |
| Date | 2026-09-29 |
| Verification | **Pending.** No evidence attached. Needed: the real Telegram username or email of an identifiable doq.world representative, plus a screenshot or forwardable copy of the message. |
| Recorded by | Toplion2010, via Claude Code |

## Permission text (as supplied, unverified)

> Yes, doq.world gives Simurg permission to automatically check our competition
> listings a few times per day, collect the information from those listings, and
> republish the competition details in Simurg's Telegram channels. You may link
> directly to the original organizer or registration pages contained in the
> listing instead of linking back to the doq.world listing page. Please credit
> the source with a short 'via doq.world' line in each post. Automated access is
> allowed as long as it is done at a reasonable low request rate and does not
> place unnecessary load on our website.

## Conditions the source must meet once this is verified

- Check the listings a few times per day at most (every 6–8 hours).
- Make requests one at a time, at least 3 seconds apart. Cache results and fetch only new or changed listings.
- Use an official API, feed or structured endpoint if one exists. Otherwise fetch the HTML politely.
- Build posts only from the competition information in each listing.
- Link to the organizer or registration URL contained in the listing. Never use the doq.world listing URL as the published destination.
- End every doq.world post with exactly `via doq.world`.
- Dedupe against opportunities already collected from other Simurg sources.
- First run: the first 10 listings only, reviewed before anything is scheduled.

## Context

- doq.world's Terms (checked 2026-09-29) prohibit automated extraction and
  republication without prior written permission. They claim database rights,
  and they say identifying markers are embedded in the dataset.
- Its robots.txt (checked 2026-09-29) disallows `ClaudeBot`, `Claude-Web` and
  `anthropic-ai` site-wide. Only a verified written permission from doq.world
  would override that for Simurg's collector, and this record is what the
  source must cite. Verification comes first.

## To mark this verified

Replace the Sender and Verification rows with the real details, attach the
evidence, change the status banner to VERIFIED with a date, and commit that
change. That commit is the trigger for building and enabling the source.
