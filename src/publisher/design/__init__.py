"""Design System — appearance only, no layout/behavior (ADR-003).

Everything visual flows through tokens. The Rendering Pipeline reads tokens;
it never mutates them (invariant from system.md).

Modules:
    tokens       — single source of design values
    typography   — font sets, type scale, weights, line-heights
    spacing      — margins, gaps, paddings, baseline rhythm
    colors       — palette, accent system, badge colors
    icons        — Lucide SVG icon set, accent-tinted
    animation    — hover/fade/transition/scale tokens (future website)
"""
