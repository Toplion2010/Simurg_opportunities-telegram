"""Publishes the channel's pinned navigation post and About description.

Run manually, not on the cron — the channel's furniture changes only when
the source list or post format does. Re-running with --edit rewrites the
existing pinned post in place, so subscribers keep the same pinned message
instead of getting a second one.

    python setup_channel.py --dry-run          # print, touch nothing
    python setup_channel.py                    # post + pin + set About
    python setup_channel.py --edit 42          # rewrite post 42 in place

The source list is derived from config.SOURCES so it cannot silently drift
out of sync with what the watcher actually tracks.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import config
from pipeline.telegram import (
    CHAT_DESCRIPTION_MAX,
    edit_message,
    pin_message,
    send_message_returning_id,
    set_chat_description,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("setup_channel")

# How each config.SOURCES key is written for humans. A key missing here is a
# hard error rather than a silent omission from the post.
SOURCE_LABELS: dict[str, str] = {
    "devpost": "Devpost",
    "devevents": "dev.events",
    "mlh": "MLH",
    "devfolio": "Devfolio",
    "reskilll": "reskilll",
    "ethglobal": "ETHGlobal",
    "hackathoncom": "hackathon.com",
    "allhackathons": "allhackathons.com",
    "hackclub": "Hack Club",
    "lablab": "lablab.ai",
    "mlcontests": "ML Contests",
}

DESCRIPTION = (
    "Free hackathons & AI/ML competitions, auto-tracked across 11 platforms "
    "(Devpost, MLH, Devfolio, ETHGlobal, lablab.ai and more). Checked every 3 "
    "hours. Only open events, each with prize, deadline and eligibility. "
    "Details in the pinned post."
)


def _enabled_source_labels() -> list[str]:
    labels = []
    for name, entry in config.SOURCES.items():
        if not entry.get("enabled"):
            continue
        if name not in SOURCE_LABELS:
            raise KeyError(f"add a SOURCE_LABELS entry for the {name!r} source")
        labels.append(SOURCE_LABELS[name])
    return labels


def build_nav_message() -> str:
    labels = _enabled_source_labels()
    hours = "3"  # matches the workflow's cron: "0 */3 * * *"
    return (
        "🚀 <b>Simurg Hackathons</b>\n\n"
        "Hackathons and AI/ML competitions, found automatically and posted "
        f"as soon as they open — every {hours} hours, around the clock.\n\n"
        f"<b>📡 Tracked sources ({len(labels)})</b>\n"
        f"{' · '.join(labels)}\n\n"
        "<b>📖 How to read a post</b>\n"
        "🏆 prize pool (converted to $ when listed in another currency)\n"
        "🌐 online  ·  📍 in-person, with the city\n"
        "⏳ how long is left before the deadline\n"
        "⚠️ who can enter — age or student restrictions\n"
        "🏢 organizer\n"
        "🔗 extra links, such as rules or registration\n"
        "#tags for the topic\n\n"
        "<b>✅ What you can rely on</b>\n"
        "• Nothing expired — closed events are filtered out\n"
        "• Nothing repeated — each hackathon is posted once\n"
        "• Every post carries a real description, not just a title\n\n"
        "<i>Tap a title to open the official page.</i>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the channel's pinned navigation post")
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="print the message, send nothing"
    )
    parser.add_argument(
        "--edit", type=int, metavar="MESSAGE_ID",
        help="rewrite an existing pinned post in place instead of posting a new one",
    )
    parser.add_argument(
        "--skip-description", action="store_true", help="don't touch the channel's About text"
    )
    args = parser.parse_args()

    text = build_nav_message()

    if args.dry_run:
        print(text)
        print("\n" + "-" * 60)
        print(f"About ({len(DESCRIPTION)}/{CHAT_DESCRIPTION_MAX} chars):\n{DESCRIPTION}")
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; nothing sent")
        sys.exit(1)

    if args.edit:
        if edit_message(token, chat_id, args.edit, text):
            logger.info("updated pinned post %d", args.edit)
        else:
            logger.error("failed to update post %d", args.edit)
            sys.exit(1)
    else:
        message_id = send_message_returning_id(token, chat_id, text, disable_preview=True)
        if message_id is None:
            logger.error("failed to post the navigation message")
            sys.exit(1)
        logger.info("posted navigation message %d", message_id)
        if pin_message(token, chat_id, message_id):
            logger.info("pinned message %d", message_id)
        else:
            logger.error(
                "posted but could not pin — the bot needs 'Pin Messages' admin rights"
            )
        logger.info("re-run later with: python setup_channel.py --edit %d", message_id)

    if not args.skip_description:
        if set_chat_description(token, chat_id, DESCRIPTION):
            logger.info("channel About description updated")
        else:
            logger.error(
                "could not set the About description — the bot needs "
                "'Change Channel Info' admin rights"
            )


if __name__ == "__main__":
    main()
