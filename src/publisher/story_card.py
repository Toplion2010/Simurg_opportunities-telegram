"""Renders a Story image that looks like Telegram's own "Share post to Story":
the post shown as a message bubble (channel name, the post's photo, title and
a short excerpt ending in "Read More") over a blurred copy of the photo.

Telegram apps draw that bubble client-side before uploading, so a userbot has
to draw it too. The bubble's on-screen box is measured in the browser and
returned as percentages -- story.py places the tappable "open post" area there.
"""
import base64
import html
from dataclasses import dataclass

from src.db.models.opportunity import Opportunity

STORY_WIDTH = 1080
STORY_HEIGHT = 1920
_EXCERPT_CHARS = 200


@dataclass(frozen=True)
class CardBox:
    """The bubble's position, as percentages (0-100) of the story's size."""

    x: float  # center
    y: float  # center
    w: float
    h: float


def _excerpt(opp: Opportunity) -> str:
    text = " ".join((opp.card_summary or opp.description or opp.rewritten_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    cut = text[:_EXCERPT_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:-–— ") + "…"


def build_story_html(photo_bytes: bytes, channel_title: str, opp: Opportunity) -> str:
    photo = f"data:image/jpeg;base64,{base64.b64encode(photo_bytes).decode('ascii')}"
    excerpt = _excerpt(opp)
    more = '<span class="more">Read More</span>' if excerpt.endswith("…") else ""
    excerpt_html = f'<div class="text">{html.escape(excerpt)} {more}</div>' if excerpt else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {STORY_WIDTH}px; height: {STORY_HEIGHT}px; overflow: hidden;
    font-family: "Inter", system-ui, "DejaVu Sans", sans-serif;
    display: flex; align-items: center; justify-content: center;
    background: #101820;
  }}
  .bg {{
    position: absolute; inset: -80px;
    background: url("{photo}") center / cover;
    filter: blur(48px) brightness(0.6);
  }}
  .bubble {{
    position: relative; width: 860px; max-height: 1640px; overflow: hidden;
    background: #212d3b; border-radius: 36px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
  }}
  .channel {{
    padding: 26px 34px 20px; color: #6ab3f3; font-size: 34px; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .photo {{ display: block; width: 100%; max-height: 900px; object-fit: cover; }}
  .body {{ padding: 26px 34px 34px; color: #f5f5f5; }}
  .title {{ font-size: 42px; font-weight: 700; line-height: 1.25; }}
  .text {{ margin-top: 18px; font-size: 36px; line-height: 1.35; color: #e4e9ee; }}
  .more {{ color: #6ab3f3; }}
</style></head>
<body>
  <div class="bg"></div>
  <div class="bubble" id="bubble">
    <div class="channel">{html.escape(channel_title)}</div>
    <img class="photo" src="{photo}">
    <div class="body">
      <div class="title">{html.escape(opp.title or "Opportunity")}</div>
      {excerpt_html}
    </div>
  </div>
</body></html>"""


async def render_story_card(
    photo_bytes: bytes, channel_title: str, opp: Opportunity
) -> tuple[bytes, CardBox]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(viewport={"width": STORY_WIDTH, "height": STORY_HEIGHT})
            await page.set_content(
                build_story_html(photo_bytes, channel_title, opp), wait_until="load"
            )
            box = await page.locator("#bubble").bounding_box()
            img_bytes = await page.screenshot(type="jpeg", quality=92, full_page=False)
        finally:
            await browser.close()

    return img_bytes, CardBox(
        x=(box["x"] + box["width"] / 2) / STORY_WIDTH * 100,
        y=(box["y"] + box["height"] / 2) / STORY_HEIGHT * 100,
        w=box["width"] / STORY_WIDTH * 100,
        h=box["height"] / STORY_HEIGHT * 100,
    )
