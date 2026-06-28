#!/usr/bin/env python3
"""
SF Board of Supervisors Agenda Discord Notifier
Monitors Granicus RSS feeds for newly posted SF BOS agendas and notifies Discord.
"""

import os
import json
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
SEEN_IDS_FILE   = Path("seen_event_ids.json")

# Granicus RSS feeds for SF BOS
# view_id=10  → Full Board of Supervisors
# view_id=11  → Budget & Finance Committee  
# view_id=14  → Land Use & Transportation Committee
# view_id=12  → Rules Committee
# view_id=13  → Government Audit & Oversight Committee
# view_id=22  → Public Safety & Neighborhood Services Committee
FEEDS = [
    {
        "name": "Full Board of Supervisors",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=10",
        "color": 0x1a5276,
    },
    {
        "name": "Budget & Finance Committee",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=11",
        "color": 0x1e8449,
    },
    {
        "name": "Land Use & Transportation Committee",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=14",
        "color": 0x7d3c98,
    },
    {
        "name": "Rules Committee",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=12",
        "color": 0xb7950b,
    },
    {
        "name": "Government Audit & Oversight Committee",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=13",
        "color": 0x2e86c1,
    },
    {
        "name": "Public Safety & Neighborhood Services",
        "url":  "https://sanfrancisco.granicus.com/ViewPublisherRSS.php?view_id=22",
        "color": 0xcb4335,
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_seen_ids() -> set:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()

def save_seen_ids(ids: set):
    SEEN_IDS_FILE.write_text(json.dumps(sorted(ids)))

def fetch_rss(url: str) -> list:
    """Fetch and parse an RSS feed, return list of items as dicts."""
    r = requests.get(url, timeout=30, headers={"User-Agent": "SF-BOS-Bot/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"media": "http://search.yahoo.com/mrss/"}
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

def is_agenda_item(item: dict) -> bool:
    """Return True if this RSS item is an agenda (not just a video archive)."""
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    # Granicus RSS items for agendas typically mention "agenda" in title or desc
    # Items that are purely video archives say "has been archived"
    # We want NEW agenda postings, not archived video notices
    if "agenda" in title:
        return True
    if "agenda" in desc and "archived" not in desc:
        return True
    # Also include upcoming meeting notices
    if "notice" in title or "upcoming" in title:
        return True
    return True  # Include all items — seen_ids handles dedup; user can filter later

def build_embed(item: dict, feed: dict) -> dict:
    """Build a Discord embed for an RSS item."""
    title   = item.get("title", "New Meeting Posted")
    link    = item.get("link", "")
    pub     = item.get("pubDate", "")
    desc    = item.get("description", "")

    # Clean up description (strip HTML tags)
    import re
    desc_clean = re.sub(r"<[^>]+>", "", desc).strip()
    if len(desc_clean) > 300:
        desc_clean = desc_clean[:297] + "…"

    fields = []
    if pub:
        fields.append({"name": "📅 Posted", "value": pub, "inline": False})
    if desc_clean:
        fields.append({"name": "📋 Details", "value": desc_clean, "inline": False})
    if link:
        fields.append({"name": "🔗 Link", "value": f"[View on SFGovTV]({link})", "inline": False})

    return {
        "title": f"📋 {feed['name']}: {title}",
        "color": feed["color"],
        "fields": fields,
        "footer": {"text": "SF Board of Supervisors • sanfrancisco.granicus.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def post_to_discord(embeds: list):
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i+10]
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": chunk}, timeout=15)
        if r.status_code not in (200, 204):
            print(f"Discord error {r.status_code}: {r.text}")
            r.raise_for_status()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Checking SF BOS Granicus RSS feeds for new agendas…")
    seen_ids = load_seen_ids()
    new_embeds = []
    new_ids    = set()

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
            if guid in seen_ids:
                continue
            new_ids.add(guid)
            new_embeds.append(build_embed(item, feed))

    print(f"\n{len(new_embeds)} new item(s) to notify")

    if new_embeds:
        # Post summary header
        requests.post(DISCORD_WEBHOOK, json={
            "content": f"🏛️ **{len(new_embeds)} new SF BOS agenda item{'s' if len(new_embeds) != 1 else ''} posted!**"
        }, timeout=15)
        post_to_discord(new_embeds)
        print("✅ Posted to Discord")
    else:
        print("Nothing new — no Discord message sent.")

    # Save all seen IDs (new + old)
    for feed in FEEDS:
        try:
            items = fetch_rss(feed["url"])
            for item in items:
                seen_ids.add(item["guid"])
        except Exception:
            pass
    seen_ids.update(new_ids)
    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
