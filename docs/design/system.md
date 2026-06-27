# Design System (appearance)

Lives in `src/publisher/design/` — **appearance only, no layout/behavior** (that's
[grammar.md](grammar.md)). One concern per module so the package doesn't rot into a single dump.

```
src/publisher/design/
├── tokens.py       # the single source of design values; everything else imports from here
├── typography.py   # font sets, type scale, weights, line-heights
├── spacing.py      # margins, gaps, paddings, baseline rhythm
├── colors.py       # palette, accent system, badge colors
├── icons.py        # Lucide SVG icon set, accent-tinted
└── animation.py    # hover/fade/transition/scale tokens (future website)
```

> **Invariant:** design tokens are **immutable during rendering**. The Rendering Pipeline reads
> tokens; it never mutates them.

## Typography — chosen by Style + Brand + Density
Not by Style alone — a long title at high density may need a different face/weight even within the
same style. Each set has a **fallback chain** (so a missing bundled font degrades gracefully):

| Style | Font fallback chain |
|---|---|
| Editorial | Space Grotesk → Inter → system-ui |
| Corporate | Inter → system-ui |
| Minimal | Manrope → Inter → system-ui |

Fonts are bundled under `assets/fonts/{editorial,minimal,corporate}/` and embedded via `@font-face`
**base64 data-URIs** (the Rendering Pipeline runs offline in Chromium — never rely on a web CDN).

## Icons
Replace emoji with **Lucide** inline SVG, tinted to the card's accent. Crisp at any scale, consistent
stroke weight, on-brand.

## Color
- One **accent per card** (category-derived, hook override) — the only loud color.
- Token palette for text, muted surfaces, badges, footer.

## Smart scrim (overlay)
Legibility overlay strength is derived from the background's **precomputed** metrics
(`brightness, contrast, visual_complexity, dominant_color` in `metadata.json`) — never computed at
render time. Brighter / busier images get a stronger scrim automatically.

## Animation tokens
`hover · fade · transition · scale` — unused by Telegram (static images) but defined now so the
future Simurg website inherits the same motion language.
