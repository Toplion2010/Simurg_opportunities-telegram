# Simurg Visual System — Architecture RFC

**Version:** 1.0  **Status:** Frozen  **Last Updated:** 2026-06-27

> **Frozen.** Real problems surface from publishing hundreds of real cards, not from more RFC
> revisions. Build *order* lives in [ROADMAP.md](ROADMAP.md); this document describes **how the
> system is structured**, not the sequence of coding it. Operational steps (e.g. restarting the bot)
> live in the repo README, not here.

## Lead principle

**Simplicity over cleverness.** Every new component must remove complexity somewhere else. If a
feature needs multiple special cases, reconsider the architecture.

## Why this architecture exists
- **Deterministic rendering** — same input → same card.
- **Offline-first** — no runtime network, no API dependency.
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

```
tools/  (offline: prompt composer, image-generator backend, QC)
   ↓        produces images + metadata.json
backgrounds/   (immutable library, API-free)
   ↓
BackgroundManager   (folder-first → tag-rank selection)
   ↓
Grammar Engine      (Layout · Priority · Responsive · Visibility)
   ↓
Design System       (tokens · typography · color · icons · spacing · animation)
   ↓
Rendering Pipeline  (HTML/CSS → Chromium → JPEG)
   ↓
Telegram
```

Generation is **offline only**; the runtime path touches **no network and no image analysis**.

## Core Invariants
- The **Title is never removed**.
- **Runtime never calls image generation.**
- The **Rendering Pipeline never modifies metadata.**
- **Design never decides content; Grammar never decides colors.**
- **Design tokens are immutable during rendering.**
- **Backgrounds are immutable during rendering**; **no runtime component writes to `backgrounds/`.**
- **Every card is renderable offline.**
- **`BackgroundManager` is the single source of truth for image selection.**

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
- Rendering fast enough for **real-time publishing**.
- **No runtime network requests.**
- **Metadata lookups O(1)** (precomputed; no per-render image analysis).
- **Image processing happens only offline.**

---

## Non-goals
Generate images at runtime · guarantee every card is unique · replace manual art direction · optimize
for every social platform · support arbitrary layouts.

## Future ideas intentionally excluded (do not reopen the RFC)
Video cards · animated cards · AI layout generation · per-card AI backgrounds · dynamic typography
generation · runtime AI Vision · ratings / preference engines · ML / self-learning · analytics.

## Acceptance Criteria (checkable)
- Rendering Pipeline performs **no image analysis** and makes **no runtime API calls**.
- **No runtime component writes to `backgrounds/`.**
- **Title always visible.**
- **Grammar and Design remain isolated** (no layout code in `design/`; no color decisions in
  `grammar/`).
- **Adding a new layout requires no Rendering Pipeline changes.**
- **Visual regression passes.**

## Architecture Decisions (ADR)
- **ADR-001 — Runtime never generates images.** *Reason:* deterministic rendering, zero API
  dependency.
- **ADR-002 — Folder-first selection, not global tag search.** *Reason:* keeps the mental model
  simple; avoids search-engine complexity.
- **ADR-003 — Appearance and behavior are separated (`design/` vs `grammar/`).** *Reason:* lets
  visuals and layout logic evolve independently.
- **ADR-004 — Image metrics precomputed into metadata.** *Reason:* keeps the render path O(1) and
  network-free.
- **ADR-005 — Image Generator Backend is an interface, not a vendor.** *Reason:* models change
  yearly; the architecture shouldn't.

---

## Document map
- [README.md](README.md) — pointer.
- **ARCHITECTURE.md** — this RFC (stable).
- [principles.md](principles.md) · [brand.md](brand.md) · [system.md](system.md) ·
  [grammar.md](grammar.md) — per-component detail.
- [ROADMAP.md](ROADMAP.md) — build order (mutable).
