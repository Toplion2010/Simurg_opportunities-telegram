# Roadmap

> **ROADMAP is intentionally mutable; [ARCHITECTURE.md](ARCHITECTURE.md) is intentionally stable.**
> This file describes the *order* of implementation and may change freely. It must never contradict
> the architecture — only sequence it.

## Status today
- ✅ Background Library System built (`BackgroundManager`, `background_map`, `image_gen` integration).
- ✅ Procedural generator + 150 starter backgrounds (15 themes × 10) on disk.
- ✅ This architecture RFC frozen at v1.0.
- ⬜ Everything below.

## Stages

1. **Selection + precomputed metrics** — evolve `background_manager.py`: folder-first → tag-rank;
   nest brands under `backgrounds/brands/`; precompute `brightness, contrast, dominant_color,
   visual_complexity, content_density, primary_safe_area` into `metadata.json`.
2. **Design System package** — `src/publisher/design/{tokens,typography,spacing,colors,icons,
   animation}.py`; bundle fonts under `assets/fonts/{editorial,minimal,corporate}/`; Lucide SVG
   icons; smart scrim from precomputed metrics. Refactor `image_gen.py` to consume tokens.
3. **Grammar Engine** — `src/publisher/grammar/{layout,priority,responsive,visibility}.py`; Layout
   strategy objects, Priority Engine (category overrides), responsive + visibility rules. Wire into
   the Rendering Pipeline.
4. **Prompt composer + backend** — `tools/prompt_composer.py` (Design DNA + Visual Intent),
   `tools/prompts/negative.txt`, `tools/generate_ai_backgrounds.py` (backend interface).
5. **Generators + QC** — improve `tools/generate_backgrounds.py` (procedural); QC pipeline
   (Resolution → Brightness → Entropy → Blur → Duplicate → optional Vision); rejects → `tools/rejected/`.
6. **Visual regression** — `tools/visual_regression.py`: fixtures vs committed baselines.
7. **Diversity gallery** — `tools/render_samples.py`: large-scale validation set → HTML gallery +
   near-duplicate clustering.
8. **Launch & freeze** — ship the design-system + grammar card, confirm real posts, then stop
   polishing and iterate from real published cards.

## Sequencing note
Stages 1–3 (the design language) deliver more perceived quality than expanding the AI library
(stages 4–5). Do them first. The AI generator is offline and optional — the system already renders
from the procedural library.
