# SF Board of Supervisors — Discord Agenda Bot

Automatically notifies a Discord channel whenever a new agenda is posted for
the **SF Board of Supervisors** (full board) or any of its **committees**
(Budget & Finance, Land Use & Transportation, Rules, Government Audit &
Oversight, Public Safety & Neighborhood Services, etc.).

Uses the public [Legistar Web API](https://webapi.legistar.com/v1/sfgov/events)
— no scraping, no login needed.

---

## Quick Setup (5 minutes)

### 1. Create a Discord Webhook

1. Open Discord → your server → the channel you want notifications in.
2. **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Give it a name (e.g. "SF BOS Agendas"), copy the **Webhook URL**.

### 2. Fork / create this repo on GitHub

Push all files to a new GitHub repo (public or private — both work).

### 3. Add the webhook as a GitHub Secret

1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `DISCORD_WEBHOOK_URL`
3. Value: paste the webhook URL from step 1.

### 4. Enable GitHub Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.
The bot will now run automatically twice a day (9 AM and 3 PM Pacific).

### 5. Test it manually

Go to **Actions → SF BOS Agenda Notifier → Run workflow** to trigger it
immediately and verify notifications appear in Discord.

---

## How it works

```
GitHub Actions (cron: 9 AM + 3 PM PT)
  └─▶ check_agendas.py
        ├─ Calls Legistar API for events modified in the last 13 hours
        ├─ Filters for events that have an agenda document attached
        ├─ Skips event IDs already seen (stored in seen_event_ids.json)
        ├─ Posts a rich Discord embed for each new agenda
        └─ Commits updated seen_event_ids.json back to the repo
```

---

## Customisation

### Watch only specific committees

In `check_agendas.py`, change:

```python
WATCH_BODIES = None  # watch everything
```

to, for example:

```python
WATCH_BODIES = ["Board of Supervisors", "Budget", "Land Use"]
```

Any body whose name *contains* one of those strings (case-insensitive) will
be included.

### Change the schedule

Edit `.github/workflows/agenda_notifier.yml` — the two `cron` lines use UTC.
`0 17 * * *` = 9 AM PT (17:00 UTC), `0 1 * * *` = 5 PM PT (01:00 UTC next day).

### Run locally

```bash
pip install requests
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python check_agendas.py
```

---

## Meeting bodies tracked

| Committee | Schedule |
|---|---|
| Full Board of Supervisors | Tuesdays at 2 PM |
| Budget & Finance Committee | Wednesdays at 10 AM |
| Budget & Appropriations Committee | Wednesdays at 1:30 PM (Feb–Aug) |
| Land Use & Transportation Committee | Mondays at 1:30 PM |
| Rules Committee | Mondays at 10 AM |
| Government Audit & Oversight Committee | 1st & 3rd Thursdays at 10 AM |
| Public Safety & Neighborhood Services | 2nd & 4th Thursdays at 10 AM |
| LAFCo | Selected Fridays at 10 AM |

Agendas typically post on Fridays for the following week's meetings.

---

## Files

| File | Purpose |
|---|---|
| `check_agendas.py` | Main bot script |
| `.github/workflows/agenda_notifier.yml` | GitHub Actions schedule |
| `seen_event_ids.json` | Tracks already-notified event IDs (auto-updated) |
