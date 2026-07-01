# 🏸 Badminton Tracker

A mobile-friendly app for tracking badminton sessions, backed by a **database**
(SQLite locally, or **Supabase/Postgres** in the cloud). Tracks daily check-ins,
per-game players & shuttles, court hours, payments, and monthly summaries — with
CSV export and a raw-data audit view so you can trace mistakes.

Two frontends share the same database layer (`db.py`):

- **`main.py` — NiceGUI** (recommended): smooth, no full-page reruns, sortable/
  searchable data tables. Run with `python main.py`.
- **`app.py` — Streamlit**: the original UI. Run with `streamlit run app.py`.

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

python main.py                # NiceGUI → http://localhost:8080
# or
streamlit run app.py          # Streamlit → http://localhost:8501
```

The starting roster (โรจน์, น้อย, ภูมี, …) is seeded automatically on first run,
into a local `sqlite:///badminton.db` file.

### Persistent data (Supabase)

For a deployed app, point it at Supabase (free Postgres) so data survives:

1. Supabase project → **Project Settings → Database → Connection string (URI)** (use the **pooling** URI, port 6543).
2. Provide it as either an env var or a Streamlit secret:
   ```bash
   export DATABASE_URL="postgresql://USER:PASSWORD@HOST:6543/postgres"   # NiceGUI / any host
   ```
   ```toml
   # .streamlit/secrets.toml (Streamlit)
   [database]
   url = "postgresql://USER:PASSWORD@HOST:6543/postgres"
   ```
Tables are created automatically on first run.

### Hosting

- **NiceGUI (`main.py`)** runs a long-lived server — deploy on **Render**,
  **Railway**, **Fly.io**, or a VPS. Set `DATABASE_URL` (Supabase) and it reads
  `PORT` from the environment. It is **not** compatible with Streamlit Community Cloud.
- **Streamlit (`app.py`)** deploys on **Streamlit Community Cloud**, but its disk
  is ephemeral — use Supabase there too.

---

## Data model

`players` · `sessions` · `attendance` · `games` · `game_players` ·
`shuttle_purchases` — see `db.py`. The database is the source of truth, so every
number on screen can be traced back to raw rows in the **Data** tab.
