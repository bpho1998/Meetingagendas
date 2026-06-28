#!/usr/bin/env python3
"""
SF Board of Supervisors Agenda Discord Notifier
Polls the Legistar Web API for newly posted agendas and sends Discord notifications.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
LEGISTAR_CLIENT = "sfgov"
LEGISTAR_BASE   = f"https://webapi.legistar.com/v1/{LEGISTAR_CLIENT}"
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# How far back to look for newly-posted agendas (GitHub Actions runs once/day)
LOOKBACK_HOURS  = int(os.environ.get("LOOKBACK_HOURS", "25"))

# File that persists seen event IDs between runs (committed back to the repo)
SEEN_IDS_FILE   = Path("seen_event_ids.json")

# Bodies we care about — None means ALL bodies (full board + all committees)
# Uncomment and edit to filter specific bodies by name substring:
# WATCH_BODIES = ["Board of Supervisors", "Budget", "Land Use", "Rules", "Government Audit", "Public Safety"]
WATCH_BODIES = None  # Watch everything

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_seen_ids() -> set:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()

def save_seen_ids(ids: set):
    SEEN_IDS_FILE.write_text(json.dumps(sorted(ids)))

def legistar_get(path: str, params: dict = None) -> list:
    url = f"{LEGISTAR_BASE}/{path}"
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_recent_events() -> list:
    """Fetch events with agendas published in the last LOOKBACK_HOURS hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    # Legistar filter: events where LastModifiedUtc >= cutoff
    date_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "$filter": f"EventLastModifiedUtc ge datetime'{date_str}'",
        "$orderby": "EventDate desc",
        "$top": 100,
    }
    return legistar_get("events", params)

def has_agenda(event: dict) -> bool:
    """Return True if this event has an agenda document attached."""
    agenda_url = event.get("EventAgendaFile") or event.get("EventAgendaURL") or ""
    return bool(agenda_url.strip())

def body_matches(event: dict) -> bool:
    """Return True if this event's body is in our watch list."""
    if WATCH_BODIES is None:
        return True
    body_name = event.get("EventBodyName", "")
    return any(w.lower() in body_name.lower() for w in WATCH_BODIES)

def format_date(date_str: str) -> str:
    """Convert ISO date string to readable format."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%A, %B %-d, %Y at %-I:%M %p")
    except Exception:
        return date_str

def build_discord_embed(event: dict) -> dict:
    """Build a rich Discord embed for a single event."""
    body_name  = event.get("EventBodyName", "Unknown Body")
    event_date = format_date(event.get("EventDate", ""))
    location   = event.get("EventLocation", "").strip() or "Location TBD"
    agenda_url = (event.get("EventAgendaFile") or event.get("EventAgendaURL") or "").strip()
    event_id   = event.get("EventId", "")
    legistar_url = f"https://sfgov.legistar.com/MeetingDetail.aspx?ID={event_id}&GUID=&Search="

    # Color by body type
    color = 0x1a5276  # deep blue default (full board)
    body_lower = body_name.lower()
    if "budget" in body_lower:
        color = 0x1e8449  # green
    elif "land use" in body_lower:
        color = 0x7d3c98  # purple
    elif "rules" in body_lower:
        color = 0xb7950b  # gold
    elif "public safety" in body_lower:
        color = 0xcb4335  # red
    elif "government audit" in body_lower:
        color = 0x2e86c1  # light blue

    fields = [
        {"name": "📅 Date & Time", "value": event_date, "inline": False},
        {"name": "📍 Location",    "value": location,   "inline": False},
    ]
    if agenda_url:
        fields.append({"name": "📄 Agenda", "value": f"[View Agenda PDF]({agenda_url})", "inline": False})
    fields.append({"name": "🔗 Legistar", "value": f"[Full Meeting Details]({legistar_url})", "inline": False})

    return {
        "title": f"📋 New Agenda: {body_name}",
        "color": color,
        "fields": fields,
        "footer": {"text": "SF Board of Supervisors • sfgov.legistar.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def post_to_discord(embeds: list):
    """Post up to 10 embeds per Discord webhook call."""
    # Discord allows max 10 embeds per message
    for i in range(0, len(embeds), 10):
        chunk = embeds[i:i+10]
        payload = {"embeds": chunk}
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
        if r.status_code not in (200, 204):
            print(f"Discord error {r.status_code}: {r.text}")
            r.raise_for_status()

def post_summary_header(count: int):
    """Post a brief header message before the embeds."""
    payload = {
        "content": f"🏛️ **{count} new SF BOS agenda{'s' if count != 1 else ''} posted!**",
    }
    requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Checking for new SF BOS agendas (last {LOOKBACK_HOURS}h)…")
    seen_ids = load_seen_ids()

    try:
        events = get_recent_events()
    except Exception as e:
        print(f"ERROR fetching events: {e}")
        raise

    print(f"  Legistar returned {len(events)} recently-modified events")

    new_events = []
    for event in events:
        eid = str(event.get("EventId", ""))
        if eid in seen_ids:
            continue
        if not has_agenda(event):
            continue
        if not body_matches(event):
            continue
        new_events.append(event)

    print(f"  {len(new_events)} new events with agendas to notify")

    if not new_events:
        print("  Nothing new — no Discord message sent.")
        return

    # Post to Discord
    post_summary_header(len(new_events))
    embeds = [build_discord_embed(e) for e in new_events]
    post_to_discord(embeds)
    print(f"  ✅ Posted {len(new_events)} notification(s) to Discord")

    # Persist seen IDs
    for event in new_events:
        seen_ids.add(str(event.get("EventId", "")))
    # Also track ALL events we saw (even without agendas) to avoid re-checking
    for event in events:
        seen_ids.add(str(event.get("EventId", "")))
    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
