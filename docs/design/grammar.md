# Card Grammar (behavior)

Lives in `src/publisher/grammar/` — **behavior only, no appearance** (that's [system.md](system.md)).
This is what makes a card *think* instead of just *draw*: it decides layout, what to show, what to
shrink, and what to drop, based on the content and the chosen background.

```
Grammar Engine
├── Layout Strategy    (layout.py)
├── Priority Engine    (priority.py)
├── Responsive Rules   (responsive.py)
└── Visibility Rules   (visibility.py)
```

## Layout Strategy — configuration, not templates
A layout is a **config object**, never an `if template == N` branch:

```python
Layout(
    text_anchor="left",      # where the text column sits
    image_focus="right",     # where the image's subject should be
    title_width=620,
    footer="bottom",
    density="comfortable",   # comfortable | compact
)
```

Named presets (e.g. *text-left / photo-right*, *photo-top / text-bottom*, *diagonal*, *centered*) are
**data**. The engine selects a preset using the image's **`primary_safe_area`** (from `metadata.json`)
plus the content. **Adding a new layout requires no Rendering Pipeline change.**

## Priority Engine — category default + overrides
Field importance is a base order plus per-category overrides — not one global list:

- **Base:** `Title > Deadline > Prize > Location > Organizer`
- **Overrides:** e.g. Conference → *Location* over *Prize*; Scholarship → *Deadline* first.

The engine resolves `effective_priority = category_override or base`.

## Responsive Rules
- Very long title → smaller font / more lines; very short title → larger font.
- Long organizer/location → truncate with ellipsis.
- Minimum margins and density switches (comfortable ↔ compact) based on how much content fits.

## Visibility Rules (separate layer)
Deciding *what to remove* is distinct from *how to resize*:
- When the card is overloaded, **drop the lowest-priority field** (per the Priority Engine).
- Hide empty rows (no deadline → no deadline row).
- **Invariant: never hide the Title** — regardless of any future reordering (see
  [ARCHITECTURE.md](ARCHITECTURE.md) → Core Invariants).

## Boundary with Design
Grammar decides **position, size, presence**. It **never decides colors** — those come from the
Design System. Keeping this boundary is an Acceptance Criterion.
