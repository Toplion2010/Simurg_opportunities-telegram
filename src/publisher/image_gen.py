"""Generate card images via HTML/CSS template rendered by playwright.

The Rendering Pipeline reads design tokens from ``src.publisher.design``;
it never mutates them (ADR-003 invariant).  All visual values come from
the Design System, not from hardcoded CSS.

Runtime flow (ARCHITECTURE.md):
    BackgroundManager → Grammar Engine → Design System → HTML/CSS → Chromium → JPEG

This module performs **no image analysis** and makes **no network requests**.
"""
import base64
import html
import mimetypes
from typing import TYPE_CHECKING

from src.core.enums import HookLabel
from src.core.logging import get_logger
from src.publisher.background_map import build_descriptor

if TYPE_CHECKING:
    from src.db.models.opportunity import Opportunity
    from src.publisher.background_manager import BackgroundManager, ImageEntry

logger = get_logger(__name__)

_bg_manager: "BackgroundManager | None" = None


def get_background_manager() -> "BackgroundManager | None":
    """Lazily build the shared BackgroundManager. Returns None if it can't be set up
    (e.g. Redis not initialised), so the caller falls back to the procedural background."""
    global _bg_manager
    if _bg_manager is not None:
        return _bg_manager
    try:
        from src.core.config import Settings
        from src.core.redis_client import get_redis
        from src.publisher.background_manager import BackgroundManager

        settings = Settings()
        try:
            redis = get_redis()
        except RuntimeError:
            redis = None  # not initialised (tests / standalone) — usage tracking disabled
        mgr = BackgroundManager(
            root=settings.BACKGROUNDS_DIR,
            redis=redis,
            refresh_interval=settings.BACKGROUND_REFRESH_SECONDS,
            history_size=settings.BACKGROUND_HISTORY_SIZE,
        )
        mgr.scan()
        _bg_manager = mgr
    except Exception as e:  # noqa: BLE001 — never block card generation on bg setup
        logger.warning("background_manager_init_failed", error=str(e))
        return None
    return _bg_manager


# ------------------------------------------------------------------ hooks

# value string → enum name, e.g. "🔥 #PremiumOpportunity" → "premium"
_HOOK_VALUE_TO_NAME: dict[str, str] = {label.value: label.name for label in HookLabel}


# ------------------------------------------------------------------ helpers

def _e(text: str | None) -> str:
    return html.escape(text or "")


def _image_data_uri(entry: "ImageEntry") -> str:
    mime = mimetypes.guess_type(entry.path.name)[0] or "image/jpeg"
    data = base64.b64encode(entry.path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


# ------------------------------------------------------------------ backgrounds


def _photo_bg(entry: "ImageEntry") -> tuple[str, str]:
    """CSS + markup for a real photo background with a smart legibility scrim.

    Scrim strength is derived from precomputed image metrics
    (brightness, contrast, visual_complexity) via the Design System's
    ``colors.compute_scrim()`` — never computed at render time.
    """
    from src.publisher.design.colors import compute_scrim, scrim_css

    uri = _image_data_uri(entry)
    scrim = compute_scrim(
        brightness=entry.brightness,
        contrast=entry.contrast,
        visual_complexity=entry.visual_complexity,
    )
    gradient = scrim_css(scrim)
    css = f"""
  .bg-photo {{
    position: absolute;
    inset: 0;
    background: url('{uri}') center / cover no-repeat;
  }}
  .bg-scrim {{
    position: absolute;
    inset: 0;
    background: linear-gradient(105deg, {gradient});
    pointer-events: none;
  }}"""
    markup = '  <div class="bg-photo"></div>\n  <div class="bg-scrim"></div>'
    return css, markup


def _procedural_bg(accent: str, glow: str) -> tuple[str, str]:
    """CSS + markup for the procedural fallback background.

    Uses design tokens for colours and grid values.  No emoji decoration
    — the fallback should stay minimal so the accent is the only loud element.
    """
    from src.publisher.design.colors import BG_DARK, GRID_COLOR, GRID_SIZE
    from src.publisher.design.tokens import CARD_HEIGHT, CARD_WIDTH

    css = f"""
  /* Gradient wash */
  .bg-gradient {{
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg,
      {BG_DARK} 0%,
      {accent}18 40%,
      {accent}30 60%,
      {BG_DARK} 100%);
    pointer-events: none;
  }}

  /* Grid */
  .bg-grid {{
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient({GRID_COLOR} 1px, transparent 1px),
      linear-gradient(90deg, {GRID_COLOR} 1px, transparent 1px);
    background-size: {GRID_SIZE}px {GRID_SIZE}px;
    pointer-events: none;
  }}

  /* Glowing orb */
  .bg-orb {{
    position: absolute;
    top: -{CARD_HEIGHT // 2 + 40}px;
    right: -{CARD_HEIGHT // 2 + 40}px;
    width: {CARD_WIDTH // 2 + 200}px;
    height: {CARD_WIDTH // 2 + 200}px;
    border-radius: 50%;
    background: radial-gradient(circle, {glow}55 0%, {glow}22 35%, transparent 70%);
    pointer-events: none;
  }}

  /* Second orb bottom-left */
  .bg-orb2 {{
    position: absolute;
    bottom: -100px;
    left: -80px;
    width: 320px;
    height: 320px;
    border-radius: 50%;
    background: radial-gradient(circle, {glow}22 0%, transparent 65%);
    pointer-events: none;
  }}"""
    markup = (
        '  <div class="bg-gradient"></div>\n'
        '  <div class="bg-grid"></div>\n'
        '  <div class="bg-orb"></div>\n'
        '  <div class="bg-orb2"></div>'
    )
    return css, markup


# ------------------------------------------------------------------ HTML builder


def _build_css(
    accent: str,
    bg_entry: "ImageEntry | None",
    font_style: str = "editorial",
    density: str = "comfortable",
) -> str:
    """Generate the full CSS block from design tokens.

    All visual values come from the Design System — no hardcoded sizes
    or colours in this function.
    """
    from src.publisher.design.colors import (
        FOOTER_BG,
        FOOTER_BLUR,
        TEXT_MUTED,
        TEXT_PRIMARY,
        TEXT_SECONDARY,
        BG_DARK,
    )
    from src.publisher.design.spacing import get_spacing
    from src.publisher.design.tokens import CARD_HEIGHT, CARD_WIDTH
    from src.publisher.design.typography import DEFAULT_STYLE, font_stack, get_scale

    sp = get_spacing(density)
    ts = get_scale(density)
    stack = font_stack(font_style if font_style in ("editorial", "corporate", "minimal") else DEFAULT_STYLE)

    if bg_entry is not None:
        from src.publisher.design.colors import compute_scrim, scrim_css

        uri = _image_data_uri(bg_entry)
        scrim = compute_scrim(
            brightness=bg_entry.brightness,
            contrast=bg_entry.contrast,
            visual_complexity=bg_entry.visual_complexity,
        )
        gradient = scrim_css(scrim)
        bg_block = f"""
  .bg-photo {{
    position: absolute;
    inset: 0;
    background: url('{uri}') center / cover no-repeat;
  }}
  .bg-scrim {{
    position: absolute;
    inset: 0;
    background: linear-gradient(105deg, {gradient});
    pointer-events: none;
  }}"""
        background_color = BG_DARK
    else:
        from src.publisher.design.colors import BG_DARK, GRID_COLOR, GRID_SIZE

        bg_block = f"""
  .bg-gradient {{
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg,
      {BG_DARK} 0%, {accent}18 40%, {accent}30 60%, {BG_DARK} 100%);
    pointer-events: none;
  }}
  .bg-grid {{
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient({GRID_COLOR} 1px, transparent 1px),
      linear-gradient(90deg, {GRID_COLOR} 1px, transparent 1px);
    background-size: {GRID_SIZE}px {GRID_SIZE}px;
    pointer-events: none;
  }}
  .bg-orb {{
    position: absolute;
    top: -160px; right: -160px;
    width: 560px; height: 560px;
    border-radius: 50%;
    background: radial-gradient(circle, {accent}55 0%, {accent}22 35%, transparent 70%);
    pointer-events: none;
  }}
  .bg-orb2 {{
    position: absolute;
    bottom: -100px; left: -80px;
    width: 320px; height: 320px;
    border-radius: 50%;
    background: radial-gradient(circle, {accent}22 0%, transparent 65%);
    pointer-events: none;
  }}"""
        background_color = BG_DARK

    return (
        f"  * {{ margin: 0; padding: 0; box-sizing: border-box; }}\n"
        f"\n"
        f"  body {{\n"
        f"    width: {CARD_WIDTH}px;\n"
        f"    height: {CARD_HEIGHT}px;\n"
        f"    font-family: {stack};\n"
        f"    background: {background_color};\n"
        f"    color: {TEXT_PRIMARY};\n"
        f"    overflow: hidden;\n"
        f"    position: relative;\n"
        f"  }}\n"
        f"{bg_block}\n"
        f"\n"
        f"  .accent-bar {{\n"
        f"    position: absolute;\n"
        f"    left: 0; top: 0; bottom: 0;\n"
        f"    width: {sp.accent_bar_width}px;\n"
        f"    background: linear-gradient(to bottom, {accent}, {accent}66, transparent);\n"
        f"  }}\n"
        f"\n"
        f"  .accent-top {{\n"
        f"    position: absolute;\n"
        f"    top: 0; left: 0; right: 0;\n"
        f"    height: {sp.accent_top_height}px;\n"
        f"    background: linear-gradient(to right, {accent}, {accent}44, transparent 60%);\n"
        f"  }}\n"
        f"\n"
        f"  .content {{\n"
        f"    position: absolute;\n"
        f"    top: {sp.content_top}px;\n"
        f"    left: {sp.content_left}px;\n"
        f"    right: {sp.content_right}px;\n"
        f"    bottom: {sp.content_bottom}px;\n"
        f"    display: flex;\n"
        f"    flex-direction: column;\n"
        f"    justify-content: space-between;\n"
        f"  }}\n"
        f"\n"
        f"  .top-section {{\n"
        f"    display: flex;\n"
        f"    flex-direction: column;\n"
        f"    gap: {sp.section_gap}px;\n"
        f"  }}\n"
        f"\n"
        f"  .badges {{\n"
        f"    display: flex;\n"
        f"    gap: {sp.badge_gap}px;\n"
        f"    align-items: center;\n"
        f"    flex-wrap: wrap;\n"
        f"  }}\n"
        f"\n"
        f"  .category-badge {{\n"
        f"    background: {accent};\n"
        f"    color: #000;\n"
        f"    font-size: {ts.badge_size}px;\n"
        f"    font-weight: {ts.badge_weight};\n"
        f"    letter-spacing: {ts.badge_letter_spacing};\n"
        f"    padding: 7px 18px;\n"
        f"    border-radius: 20px;\n"
        f"    text-transform: uppercase;\n"
        f"    box-shadow: 0 0 20px {accent}66;\n"
        f"  }}\n"
        f"\n"
        f"  .hook-badge {{\n"
        f"    border: 2px solid {accent};\n"
        f"    color: {accent};\n"
        f"    font-size: {ts.hook_size}px;\n"
        f"    font-weight: {ts.hook_weight};\n"
        f"    letter-spacing: {ts.hook_letter_spacing};\n"
        f"    padding: 5px 14px;\n"
        f"    border-radius: 20px;\n"
        f"    background: {accent}18;\n"
        f"    box-shadow: 0 0 12px {accent}44;\n"
        f"  }}\n"
        f"\n"
        f"  .title {{\n"
        f"    font-size: {ts.title_size}px;\n"
        f"    font-weight: {ts.title_weight};\n"
        f"    line-height: {ts.title_line_height};\n"
        f"    letter-spacing: {ts.title_letter_spacing};\n"
        f"    color: {TEXT_PRIMARY};\n"
        f"    text-shadow: 0 2px 20px rgba(0,0,0,0.5);\n"
        f"    display: -webkit-box;\n"
        f"    -webkit-line-clamp: {ts.title_max_lines};\n"
        f"    -webkit-box-orient: vertical;\n"
        f"    overflow: hidden;\n"
        f"  }}\n"
        f"\n"
        f"  .divider {{\n"
        f"    width: {sp.divider_width}px;\n"
        f"    height: {sp.divider_height}px;\n"
        f"    background: {accent};\n"
        f"    border-radius: 2px;\n"
        f"    box-shadow: 0 0 10px {accent};\n"
        f"  }}\n"
        f"\n"
        f"  .meta {{\n"
        f"    display: flex;\n"
        f"    flex-direction: column;\n"
        f"    gap: {sp.meta_gap}px;\n"
        f"  }}\n"
        f"\n"
        f"  .meta-row {{\n"
        f"    display: flex;\n"
        f"    align-items: center;\n"
        f"    gap: {sp.meta_row_gap}px;\n"
        f"    font-size: {ts.meta_row_size}px;\n"
        f"  }}\n"
        f"\n"
        f"  .meta-icon {{\n"
        f"    font-size: {ts.meta_icon_size}px;\n"
        f"    width: 24px;\n"
        f"    flex-shrink: 0;\n"
        f"  }}\n"
        f"\n"
        f"  .meta-label {{\n"
        f"    color: {accent};\n"
        f"    font-weight: {ts.meta_label_weight};\n"
        f"    min-width: {sp.meta_label_min_width}px;\n"
        f"    font-size: {ts.meta_label_size}px;\n"
        f"    letter-spacing: {ts.meta_label_letter_spacing};\n"
        f"  }}\n"
        f"\n"
        f"  .meta-value {{\n"
        f"    color: {TEXT_SECONDARY};\n"
        f"    font-weight: {ts.meta_value_weight};\n"
        f"    font-size: {ts.meta_value_size}px;\n"
        f"  }}\n"
        f"\n"
        f"  .footer {{\n"
        f"    position: absolute;\n"
        f"    bottom: 0; left: 0; right: 0;\n"
        f"    height: {sp.footer_height}px;\n"
        f"    background: {FOOTER_BG};\n"
        f"    backdrop-filter: blur({FOOTER_BLUR}px);\n"
        f"    display: flex;\n"
        f"    align-items: center;\n"
        f"    justify-content: space-between;\n"
        f"    padding: 0 {sp.footer_padding_horizontal}px;\n"
        f"    border-top: 1px solid {accent}33;\n"
        f"  }}\n"
        f"\n"
        f"  .footer-brand {{\n"
        f"    font-size: {ts.footer_brand_size}px;\n"
        f"    font-weight: {ts.footer_brand_weight};\n"
        f"    letter-spacing: {ts.footer_brand_letter_spacing};\n"
        f"    color: {accent};\n"
        f"    text-transform: uppercase;\n"
        f"    text-shadow: 0 0 12px {accent}88;\n"
        f"  }}\n"
        f"\n"
        f"  .footer-url {{\n"
        f"    font-size: {ts.footer_url_size}px;\n"
        f"    color: {TEXT_MUTED};\n"
        f"    letter-spacing: {ts.footer_url_letter_spacing};\n"
        f"  }}"
    )


def _build_html(opp: "Opportunity", bg_entry: "ImageEntry | None") -> str:
    """Build the full HTML document for a card.

    Behaviour comes from the Grammar Engine (layout, priority, responsive,
    visibility).  Visual values come from the Design System tokens (ADR-003).
    """
    from src.publisher.design.tokens import (
        FOOTER_BRAND_TEXT,
        FOOTER_URL_TEXT,
        resolve_tokens,
    )
    from src.publisher.design.icons import icon_svg
    from src.publisher.grammar.engine import resolve as resolve_grammar

    # Resolve grammar (behavior): layout, priority, responsive, visibility
    grammar = resolve_grammar(opp, bg_entry)

    # Resolve design tokens (appearance): accent, glow
    category = opp.category.value if opp.category else ""
    hook_values: list[str] = opp.hooks or []
    hook_names = [_HOOK_VALUE_TO_NAME.get(v) for v in hook_values]
    tokens = resolve_tokens(category=category, hook_names=hook_names)

    # Hook badge (from grammar — visibility-aware)
    hook_badge_html = (
        f'<div class="hook-badge">{_e(grammar.hook_display)}</div>'
        if grammar.has_hook else ""
    )

    # Meta rows — from Grammar Engine (already ordered, truncated, filtered)
    meta_rows: list[str] = []
    for mf in grammar.meta_fields:
        icon = icon_svg(mf.icon, tokens.accent)
        meta_rows.append(
            f'<div class="meta-row"><span class="meta-icon">{icon}</span>'
            f'<span class="meta-label">{_e(mf.label)}</span>'
            f'<span class="meta-value">{_e(mf.value)}</span></div>'
        )
    meta_html = "\n".join(meta_rows)

    css = _build_css(tokens.accent, bg_entry, density=grammar.responsive.density)

    bg_markup = ""
    if bg_entry is not None:
        bg_css, bg_markup = _photo_bg(bg_entry)
    else:
        bg_css, bg_markup = _procedural_bg(tokens.accent, tokens.glow)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{css}
</style>
</head>
<body>
{bg_markup}
  <div class="accent-bar"></div>
  <div class="accent-top"></div>

  <div class="content">
    <div class="top-section">
      <div class="badges">
        <div class="category-badge">{_e(grammar.category)}</div>
        {hook_badge_html}
      </div>
      <div class="title">{grammar.title}</div>
      <div class="divider"></div>
    </div>

    <div class="meta">
      {meta_html}
    </div>
  </div>

  <div class="footer">
    <span class="footer-brand">{FOOTER_BRAND_TEXT}</span>
    <span class="footer-url">{FOOTER_URL_TEXT}</span>
  </div>
</body>
</html>"""


# ------------------------------------------------------------------ render


async def _render_html(html_content: str) -> bytes:
    from playwright.async_api import async_playwright
    from src.publisher.design.tokens import CARD_HEIGHT, CARD_WIDTH

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT})
        await page.set_content(html_content, wait_until="domcontentloaded")
        img_bytes = await page.screenshot(type="jpeg", quality=92, full_page=False)
        await browser.close()
        return img_bytes


async def _select_background(opp: "Opportunity") -> "ImageEntry | None":
    mgr = get_background_manager()
    if mgr is None:
        return None
    try:
        return await mgr.get_background(build_descriptor(opp))
    except Exception as e:  # noqa: BLE001 — fall back to procedural on any error
        logger.warning("background_select_failed", opp_id=getattr(opp, "id", None), error=str(e))
        return None


async def generate_card(opp: "Opportunity") -> bytes:
    bg_entry = await _select_background(opp)
    html_content = _build_html(opp, bg_entry)
    return await _render_html(html_content)
