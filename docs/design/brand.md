# Brand Identity

**Goal:** a card is recognizably **Simurg even without the logo**. The test:

> **Every card should be recognizable in a 3-second scroll** — before a single word is read.

This is achieved by keeping a small set of brand elements **constant** across every card, enforced
through Design-System tokens (not ad-hoc CSS):

| Element | Rule |
|---|---|
| **Badges** | One badge style (category badge + optional hook badge); same shape, weight, padding. |
| **Accent system** | One accent per card, derived from category (with hook override); used for badge, divider, meta labels, footer brand, icons. |
| **Grid** | One layout grid + safe zones; content never touches the edges. |
| **Typography** | One type system (see [system.md](system.md)); consistent scale and hierarchy. |
| **Footer** | Constant brand mark: `SIMURG OPPORTUNITIES` + channel URL. |
| **Safe zones** | Text always sits in a protected region with a legibility scrim. |

### Consistency rules
- The **Title is always the dominant element** on the card.
- The **accent color is the only "loud" color**; backgrounds stay muted under the scrim.
- Brand elements (badge style, footer, accent usage) **do not vary by background or layout** — only
  content and the chosen image change.

See [ARCHITECTURE.md](ARCHITECTURE.md) → Core Invariants and Design Constraints for the hard rules
that protect this identity.
