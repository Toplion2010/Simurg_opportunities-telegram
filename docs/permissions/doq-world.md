# doq.world: republication permission

> **STATUS: APPROVED.** Written permission was supplied on 2026-09-29 for
> automated collection and republication of doq.world competition listings.
> Production use is allowed, subject to the scope and conditions below.

## Record

| Field | Value |
|---|---|
| Sender | [jiayichensas@gmail.com](mailto:jiayichensas@gmail.com) |
| Date | 2026-09-29 |
| Decision | Approved |
| Production use | Allowed |
| Evidence | Written approval reproduced verbatim below |

## Permission text

> Yes, doq.world gives Simurg permission to automatically check our competition
> listings a few times per day, collect the information contained in those
> listings, and republish the competition details in Simurg's Telegram
> channels.
>
> Simurg may use relevant organizer and registration links that are explicitly
> contained within the opportunity text. Simurg does not need to publish or
> link back to the doq.world listing itself.
>
> Automated access is permitted provided requests are made at a reasonable low
> rate and do not place unnecessary load on doq.world.

## Authorized scope

- Automatically check doq.world competition listings a few times per day.
- Collect information contained in those listings.
- Republish the competition details in Simurg's Telegram channels.
- Publish relevant organizer and registration links only when they are
  explicitly contained within the opportunity text.
- Omit links back to the doq.world listing.
- Run in production.

## Conditions

- Keep requests at a reasonable low rate.
- Avoid unnecessary load on doq.world.
- Do not treat the approval as permission to crawl unrelated doq.world content
  or to publish links that are not explicitly contained in opportunity text.

## Simurg implementation safeguards

These are conservative implementation choices, not additional terms quoted
from doq.world:

- Run no more than once every 8 hours.
- Make requests serially and at least 3 seconds apart.
- Cache results and fetch only new or changed listings where practical.
- Never put a doq.world listing URL in a published Telegram post.
- Begin with a 10-listing, write-free dry run before enabling ingestion.
