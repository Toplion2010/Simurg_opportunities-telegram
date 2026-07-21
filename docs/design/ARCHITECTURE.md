# Simurg Visual System — Architecture RFC

**Version:** 1.1  **Status:** Frozen, amended by ADR-006  **Last Updated:** 2026-07-21

> **Frozen.** Real problems surface from publishing hundreds of real cards, not from more RFC
> revisions. Build *order* lives in [ROADMAP.md](ROADMAP.md); this document describes **how the
> system is structured**, not the sequence of coding it. Operational steps (e.g. restarting the bot)
> live in the repo README, not here.

## Lead principle

**Simplicity over cleverness.** Every new component must remove complexity somewhere else. If a
feature needs multiple special cases, reconsider the architecture.

## Why this architecture exists
- **Deterministic factual text** — title, dates, prize, CTA render identically from the database
  every time, regardless of what the background image looks like.
- **Live per-post backgrounds** (ADR-006) — each card's illustration is generated fresh, tied to
  that specific opportunity, rather than picked from a finite offline library.
- **Maintainability** — appearance and behavior are separable.
- **Extensibility** — new layouts/backgrounds are data, not code branches.
- **Recognizable branding** — one visual language across every card.
- **Fast publishing** — instant local render.

## Layered hierarchy (each layer constrains the next)

```
Visual Principles
        │
        ▼
Brand Identity
        │
        ▼
Design System  (appearance)
        │
        ▼
Grammar Engine (behavior)
        │
        ▼
Rendering Pipeline
        │
        ▼
Telegram
```

## Runtime data flow

**As of ADR-006 (2026-07-21), background generation is live and per-post,** superseding
ADR-001. Each approved opportunity gets a fresh, opportunity-specific illustration:

```
src/publisher/live_background.py   (Gemini "Nano Banana", live, per opportunity)
   ↓        prompt built from title/category/organizer/location/raw_message.text
   ↓        image required to contain ZERO text — no dates, numbers, names, URLs
Grammar Engine      (Layout · Priority · Responsive · Visibility)
   ↓
Design System       (tokens · typography · color · icons · spacing · animation)
   ↓
Rendering Pipeline  (HTML/CSS → Chromium → JPEG)
   ↓
Telegram
```

There is **no fallback**: if generation fails (rate limit, safety block, network error), the
publish attempt fails outright (`PublishError`) rather than silently substituting a generic
image — the admin just re-approves to retry. All factual text (title, dates, prize, CTA) is
rendered by the deterministic HTML/CSS Rendering Pipeline from the database, never by the
image model — image models are unreliable at rendering exact text, so none is ever asked of
them.

The offline pipeline (`tools/generate_ai_backgrounds.py`, `tools/prompt_composer.py`,
`tools/qc.py`, `backgrounds/`, `BackgroundManager`) still exists and still works, but the
runtime path described above no longer calls it. It's kept for manual/offline use (e.g.
curating a library for some future fallback mode) but isn't currently wired into publishing.

## Core Invariants
- The **Title is never removed**.
- The **Rendering Pipeline never modifies metadata.**
- **Design never decides content; Grammar never decides colors.**
- **Design tokens are immutable during rendering.**
- **Every card's factual text (title, dates, prize, CTA, category) is rendered by HTML/CSS
  from the database — never by the image model** (ADR-006).
- **A failed live generation fails the publish attempt; it never silently substitutes a
  different image** (ADR-006 — deliberately no fallback).

## Design Constraints (every card must satisfy)
- Readable on mobile and in **Telegram dark mode**.
- **Title always dominant**; no decorative element stronger than the title.
- **At most 3 visual focal points**; **no overlapping layers** competing for attention.
- **Every visual element must justify its existence.**

---

## Components

### 1. Visual Principles  *(detail: [principles.md](principles.md))*
Premium · readable in under 2 seconds · background never competes with text · accent guides attention
· empty space is intentional · consistency over novelty · information first, decoration second ·
simplicity over cleverness.

### 2. Brand Identity  *(detail: [brand.md](brand.md))*
One badge style, accent system, grid, typography, safe-zone policy → **recognizable in a 3-second
scroll**, before a word is read. Enforced through Design-System tokens.

### 3. Design System  *(detail: [system.md](system.md); `src/publisher/design/` — appearance only)*
`tokens.py · typography.py · spacing.py · colors.py · icons.py · animation.py` (no layout here).
- **Typography by Style + Brand + Density**, each with a **fallback chain**: Editorial→*Space Grotesk
  → Inter → system-ui*, Corporate→*Inter → system-ui*, Minimal→*Manrope → Inter → system-ui*. Fonts
  under `assets/fonts/{editorial,minimal,corporate}/`, embedded via `@font-face` base64 (offline).
- **Icons**: Lucide inline SVG, accent-tinted (replacing emoji).
- **Animation tokens**: hover/fade/transition/scale — for the future Simurg website.
- **Smart scrim**: from precomputed `brightness/contrast/visual_complexity/dominant_color`.

### 4. Grammar Engine  *(detail: [grammar.md](grammar.md); `src/publisher/grammar/` — behavior only)*
```
Grammar Engine
├── Layout Strategy    (layout.py)
├── Priority Engine    (priority.py)
├── Responsive Rules   (responsive.py)
└── Visibility Rules   (visibility.py)
```
- **Layout = configuration, not templates**: a `Layout` strategy object
  (`text_anchor, image_focus, title_width, footer, density`). New presets are data; the engine picks
  one from the image's **`primary_safe_area`** + content. Adding a layout requires **no Rendering
  Pipeline change**.
- **Priority Engine = category default + overrides**: base
  `Title > Deadline > Prize > Location > Organizer`, overridden per category (Conference → Location
  over Prize; Scholarship → Deadline first).
- **Responsive Rules**: long title → smaller/more lines; short → larger; long organizer → ellipsis;
  min margins; density switches.
- **Visibility Rules** (separate layer): when overloaded, drop the lowest-priority field, hide empty
  rows — **but never the Title** (Core Invariant).

### 5. Background System  *(`src/publisher/background_manager.py`, `background_map.py`)*
- **`BackgroundManager` is the single source of truth for selection.** Folder-first → tag-rank: brand
  (`backgrounds/brands/<name>/`) → mapped folder pool → `general`; rank within the pool by tag
  overlap + weight + least-used.
- **Metrics precomputed once into `metadata.json`** (extend `_auto_metadata`): `brightness, contrast,
  dominant_color`, **`visual_complexity`**, **`content_density`**, and **`primary_safe_area`** as a
  rectangle `{ "x":0.08,"y":0.12,"w":0.46,"h":0.72 }` (named *primary* so a secondary / L-shaped
  region can be added later without breaking schema). Read-only at render.

### 6. Offline Tools  *(`tools/` — never imported by `src/`)*
- **Prompt composer** (`prompt_composer.py`): **Design DNA** — Core (always) *Style · Mood · Palette ·
  Composition*; Advanced (sometimes) *Lighting · Camera · Texture · Perspective · Geometry*; **Visual
  Intent** *Prestige · Innovation · Competition · Discovery · Achievement*. Composition biased to
  text-safe negative space.
- **Negative prompt in a file** — `tools/prompts/negative.txt` (edit without code).
- **Image Generator Backend** (`generate_ai_backgrounds.py`): an **interface, not a vendor** (a
  FLUX-class model is today's reference). Reads its own local token; resumable; `--dry-run` cost.
- **Procedural generator** kept/improved (`generate_backgrounds.py`) — Library + Procedural =
  unlimited variety.

### 7. Quality Control  *(`tools/`)*
Cheap → expensive, **Vision last/optional**: `Resolution → Brightness → Entropy → Blur → Duplicate →
(then) Vision accept/reject`. Rejects → `tools/rejected/`, never the library.

### 8. Testing  *(`tools/`)*
- **Visual regression** (`visual_regression.py`): fixed fixtures → baselines (perceptual-hash / pixel
  diff) → fail on unintended drift.
- **Diversity** (`render_samples.py`): a **large-scale validation set** → HTML gallery +
  near-duplicate / low-variance clustering.

### 9. Target performance
- Rendering fast enough for **real-time publishing**, including one live image-generation
  round-trip per post (ADR-006).
- **Metadata lookups O(1)** (precomputed; no per-render image analysis on the HTML/CSS side).
- **Factual text is always deterministic** — never subject to model variance.

---

## Non-goals
Guarantee every card is unique beyond what live generation naturally produces · replace manual
art direction · optimize for every social platform · support arbitrary layouts · ask the image
model to render any factual text.

## Future ideas intentionally excluded (do not reopen the RFC)
Video cards · animated cards · AI layout generation · dynamic typography generation · runtime AI
Vision (image *analysis*, as opposed to generation) · ratings / preference engines · ML /
self-learning · analytics.

*(Per-card AI backgrounds moved from "excluded" to "adopted" — see ADR-006.)*

## Acceptance Criteria (checkable)
- **Live-generated images never contain model-rendered text** — verify the negative prompt in
  `live_background.py` still excludes text/words/letters/numbers/logos.
- **A failed live generation raises**, it never falls back to a different/generic image.
- **Title always visible.**
- **Grammar and Design remain isolated** (no layout code in `design/`; no color decisions in
  `grammar/`).
- **Adding a new layout requires no Rendering Pipeline changes.**
- **Visual regression passes** for the HTML/CSS layer given a fixed background.

## Architecture Decisions (ADR)
- **ADR-001 — ~~Runtime never generates images.~~ Superseded by ADR-006 (2026-07-21).**
  *Original reason:* deterministic rendering, zero API dependency.
- **ADR-002 — Folder-first selection, not global tag search.** *Reason:* keeps the mental model
  simple; avoids search-engine complexity. *(Still applies to the now-unused offline library, if
  it's ever reactivated as a fallback.)*
- **ADR-003 — Appearance and behavior are separated (`design/` vs `grammar/`).** *Reason:* lets
  visuals and layout logic evolve independently.
- **ADR-004 — Image metrics precomputed into metadata.** *Reason:* keeps the render path O(1) and
  network-free. *(Applies to the offline library; live-generated images compute brightness/
  contrast inline instead, since there's no persistent metadata file to precompute into.)*
- **ADR-005 — Image Generator Backend is an interface, not a vendor.** *Reason:* models change
  yearly; the architecture shouldn't. *(The interface pattern lives on in `tools/`; the live
  runtime path currently talks to Gemini directly rather than through that interface, since it
  has different constraints — no disk cache, no QC pass, bounded retries instead of resumable
  batch jobs.)*
- **ADR-006 — Live, per-post background generation, no fallback.** *Reason:* the product owner
  wants each post's background to be a fresh illustration tied to that specific opportunity
  (title/category/organizer/location/original announcement text), not picked from a finite
  pre-built library — richer and more varied, at the cost of a live API call per publish.
  *Guardrails carried over from ADR-001's original concerns:* the image model is never asked to
  render factual text (dates, prize amounts, URLs are exactly the kind of thing image models
  render unreliably), so all of that stays in the deterministic HTML/CSS layer; and there is no
  silent fallback — a failed generation fails the publish attempt loudly (`PublishError`) so a
  bad or missing image is never posted, rather than being masked by a generic substitute.

---

## Document map
- [README.md](README.md) — pointer.
- **ARCHITECTURE.md** — this RFC (stable).
- [principles.md](principles.md) · [brand.md](brand.md) · [system.md](system.md) ·
  [grammar.md](grammar.md) — per-component detail.
- [ROADMAP.md](ROADMAP.md) — build order (mutable).
