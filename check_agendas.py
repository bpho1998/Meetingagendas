#!/usr/bin/env python3
"""
SF Board of Supervisors Agenda Discord Notifier
Monitors Granicus RSS feeds for newly posted SF BOS agendas and notifies Discord.
"""

import os
import json
import time
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
SEEN_IDS_FILE   = Path("seen_event_ids.json")

# On the very first run (empty seen_event_ids.json), just mark everything as
# seen without posting — avoids flooding Discord with historical items.
FIRST_RUN_SILENT = True

FEEDS = [
    {"name": "Full Board of Supervisors",              "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=10", "color": 0x1a5276},
    {"name": "Budget & Finance Committee",             "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=11", "color": 0x1e8449},
    {"name": "Land Use & Transportation Committee",    "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=14", "color": 0x7d3c98},
    {"name": "Rules Committee",                        "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=12", "color": 0xb7950b},
    {"name": "Government Audit & Oversight Committee", "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=13", "color": 0x2e86c1},
    {"name": "Public Safety & Neighborhood Services",  "url": "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=22", "color": 0xcb4335},
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_seen_ids() -> set:
    if SEEN_IDS_FILE.exists():
        try:
            return set(json.loads(SEEN_IDS_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_seen_ids(ids: set):
    SEEN_IDS_FILE.write_text(json.dumps(sorted(ids)))

def fetch_rss(url: str) -> list:
    r = requests.get(url, timeout=30, headers={"User-Agent": "SF-BOS-Bot/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for item in root.findall(".//item"):
        entry = {
            "guid":        (item.findtext("guid") or "").strip(),
            "title":       (item.findtext("title") or "").strip(),
            "link":        (item.findtext("link") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "pubDate":     (item.findtext("pubDate") or "").strip(),
        }
        if entry["guid"]:
            items.append(entry)
    return items

def build_embed(item: dict, feed: dict) -> dict:
    title = item.get("title", "New Meeting Posted")
    link  = item.get("link", "")
    pub   = item.get("pubDate", "")
    desc  = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()
    if len(desc) > 300:
        desc = desc[:297] + "…"

    fields = []
    if pub:
        fields.append({"name": "📅 Posted", "value": pub, "inline": False})
    if desc:
        fields.append({"name": "📋 Details", "value": desc, "inline": False})
    if link:
        fields.append({"name": "🔗 Link", "value": f"[View on SFGovTV]({link})", "inline": False})

    return {
        "title": f"📋 {feed['name']}: {title}",
        "color": feed["color"],
        "fields": fields,
        "footer": {"text": "SF Board of Supervisors • sanfrancisco.granicus.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def post_embed_with_retry(embed: dict):
    """Post a single embed to Discord with rate-limit handling."""
    for attempt in range(5):
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=15)
        if r.status_code in (200, 204):
            return
        if r.status_code == 429:
            retry_after = r.json().get("retry_after", 1)
            print(f"    Rate limited — waiting {retry_after}s…")
            time.sleep(float(retry_after) + 0.1)
        else:
            print(f"    Discord error {r.status_code}: {r.text}")
            r.raise_for_status()
    raise Exception("Failed to post to Discord after 5 attempts")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Checking SF BOS Granicus RSS feeds…")
    seen_ids  = load_seen_ids()
    is_first  = len(seen_ids) == 0

    if is_first and FIRST_RUN_SILENT:
        print("First run — marking all existing items as seen (no Discord posts).")

    all_new_items = []  # (item, feed)
    all_guids     = set()

    for feed in FEEDS:
        print(f"  Fetching: {feed['name']}")
        try:
            items = fetch_rss(feed["url"])
        except Exception as e:
            print(f"    ERROR: {e}")
            continue
        print(f"    {len(items)} items found")
        for item in items:
            guid = item["guid"]
            all_guids.add(guid)
            if guid not in seen_ids:
                all_new_items.append((item, feed))

    print(f"\n{len(all_new_items)} new item(s) found")

    if is_first and FIRST_RUN_SILENT:
        # Just save everything as seen, post nothing
        seen_ids.update(all_guids)
        save_seen_ids(seen_ids)
        print("All items marked as seen. Future runs will only notify about new agendas.")
        return

    if not all_new_items:
        print("Nothing new — no Discord message sent.")
        seen_ids.update(all_guids)
        save_seen_ids(seen_ids)
        return

    # Post header
    requests.post(DISCORD_WEBHOOK, json={
        "content": f"🏛️ **{len(all_new_items)} new SF BOS agenda item{'s' if len(all_new_items) != 1 else ''} posted!**"
    }, timeout=15)
    time.sleep(0.5)

    # Post embeds one at a time with rate-limit handling
    posted = 0
    for item, feed in all_new_items:
        try:
            post_embed_with_retry(build_embed(item, feed))
            seen_ids.add(item["guid"])
            posted += 1
            time.sleep(0.5)  # gentle pacing between posts
        except Exception as e:
            print(f"    Failed to post item: {e}")
            # Save progress so far and re-raise
            seen_ids.update(all_guids)
            save_seen_ids(seen_ids)
            raise

    seen_ids.update(all_guids)
    save_seen_ids(seen_ids)
    print(f"✅ Posted {posted} notification(s) to Discord")

if __name__ == "__main__":
    main()
