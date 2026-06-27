# Background Library

Drop background images (`.png`, `.jpg`, `.jpeg`, `.webp`) into the folders here. The app scans this
tree on startup and refreshes every few minutes (`BACKGROUND_REFRESH_SECONDS`, default 300s), so
**adding or removing an image takes effect with no code change and no restart**.

## Generating starter backgrounds

To populate the theme folders with free, procedurally generated, category-themed backgrounds:

```bash
python -m scripts.generate_backgrounds                 # ~10 per theme
python -m scripts.generate_backgrounds --count 20      # more variety
python -m scripts.generate_backgrounds --themes startup,finance --count 5
python -m scripts.generate_backgrounds --force         # regenerate from _01
```

It writes `<theme>_NN.jpg` files plus their `metadata.json` entries (with `tags`, `dominant_color`,
`brightness`). Re-running **adds** more images without clobbering existing ones. Brand collections
(`google/`, `nasa/`, …) are skipped by default — add real logos/photos there yourself, or pass
`--include-collections` to fill them with neutral art. See `scripts/generate_backgrounds.py`.

## How a background is chosen

For each opportunity the app builds a style descriptor (category → theme, plus light keyword tags)
and picks an image using this fallback chain:

1. **Brand collection** — a folder matching the opportunity's organizer/title (see below).
2. **Mapped theme** — the theme folder for the opportunity's category (+ any `theme_*` variants).
3. **`general/`** — the catch-all.
4. If the library is empty, the app draws the original procedurally generated background.

Within the chosen pool, selection is **weighted + least-used**: higher `weight`/`quality` images
appear more often, recently used images are skipped, and a Redis usage counter keeps all images
rotating evenly over time.

## Folders

**Themes** (mapped from categories): `academic`, `business`, `technology`, `nature`, `space`,
`finance`, `medicine`, `design`, `startup`, `hackathon`, `research`, `conference`, `exchange`,
`volunteer`, `general`.

- A folder named `<theme>_<variant>` (e.g. `academic_dark`, `startup_neon`) is pooled into its base
  theme automatically — no code change needed.

**Brand collections** — any folder whose name is *not* a theme (e.g. `google/`, `mit/`, `nasa/`).
If the opportunity's organizer or title contains the folder name, that collection is preferred.

## `metadata.json` (optional, per folder)

Curated, static fields keyed by filename. Every field is optional; unknown fields are ignored.

```json
{
  "oxford_01.jpg": {
    "weight": 5,
    "quality": 4,
    "tags": ["modern", "prestigious", "blue"],
    "author": "unsplash/jane",
    "dominant_color": "#1A2B3C",
    "brightness": 0.35,
    "blur_safe": true
  }
}
```

| Field | Meaning | Default |
|---|---|---|
| `weight` | Relative pick frequency | `1` |
| `quality` | Curation quality 1–5 (boosts/penalises odds) | `3` |
| `tags` | Style tags, matched against the opportunity descriptor | `[]` |
| `dominant_color` | Hex; auto-computed if missing | auto |
| `brightness` | 0–1 luminance; tunes the readability scrim | auto |
| `author`, `blur_safe`, … | Free metadata for future use | — |

### Auto metadata

When you add an image with **no** entry, the app computes `dominant_color` and `brightness` with
Pillow and writes a default entry back into the folder's `metadata.json`. You only need to hand-edit
the fields you care about (e.g. bump `weight` for your best images). Your edits are never overwritten.

> Image binaries are git-ignored; only the folder structure, `metadata.json`, and this README are
> tracked.
