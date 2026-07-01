# 🏸 Badminton Tracker

A mobile-friendly **Streamlit** app for tracking badminton sessions, backed by a
**database** (SQLite locally, or **Supabase/Postgres** in the cloud). Tracks
daily check-ins, per-game players & shuttles, court hours, payments, and monthly
summaries — with CSV export and a raw-data audit view so you can trace mistakes.

No Google Sheets, no API keys required for local use.

---

## Features

| Tab | What it does |
|-----|--------------|
| 📋 **Session** | Pick the date, set hours per court (9 & 10), check players in, add ad-hoc/guest players, and add games (pick who played + shuttles used). Edit or delete any submitted game. |
| 💰 **Daily** | Per-player breakdown (games, shuttle cost, court fee, total) with a **✅ Paid** tickbox each. Exports the day to CSV. |
| 📅 **Monthly** | Court-hours rented & rental cost, shuttles bought & cost, fees collected, and **net P&L**; per-player owed/paid/outstanding. CSV export. |
| 🛒 **Shuttles** | Record shuttle purchases (qty × unit cost) for cost tracking. |
| 👥 **Players** | Manage the roster; deactivate players (keeps their history). |
| 🗄️ **Data** | Raw tables for auditing/tracing, each exportable to CSV. |

---

## Cost model

- **Court fee (what each player pays):** flat **80 THB / person / day**.
- **Court rental cost (your venue expense):** **155 THB / court / hour** (courts 9 & 10, 1–3 h/day) — summed monthly.
- **Shuttles:** **100 THB each**, split among a game's players → **25 THB each for a 4-player game**. A player's shuttle bill = sum of their per-game shares.
- **Daily total per player = 80 + shuttle share.** Monthly **net** = fees collected − (court rental + shuttle purchases).

All defaults live in `db.py` and are easy to change; court hours/fee/shuttle price are stored per session.

---

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py          # uses a local SQLite file, seeded with the roster
```

The starting roster (โรจน์, น้อย, ภูมี, …) is seeded automatically on first run.

### Deploy on Streamlit Cloud (with persistent data)

Streamlit Cloud's disk is wiped on restart, so **use Supabase** (free Postgres)
so your data survives:

1. Create a Supabase project → **Project Settings → Database → Connection string (URI)** (use the pooling URI).
2. In the deployed app → **Settings → Secrets**, add:
   ```toml
   [database]
   url = "postgresql://USER:PASSWORD@HOST:PORT/postgres"
   ```
3. Deploy (repo + branch + `app.py`). Tables are created automatically on first run.

Locally, no secrets are needed — it falls back to `sqlite:///badminton.db`.

---

## Data model

`players` · `sessions` · `attendance` · `games` · `game_players` ·
`shuttle_purchases` — see `db.py`. The database is the source of truth, so every
number on screen can be traced back to raw rows in the **Data** tab.
