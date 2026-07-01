# Plan: Local SQLite Summary Database for Badminton Tracker

## Goal

Add a local SQLite database to the Streamlit app so historical summaries, per-player totals, and per-session data can be read instantly without hitting the Google Sheets API. The app writes to Google Sheets as the source of truth, but reads summaries from SQLite for speed and reliability.

## Motivation

- Google Sheets API has a **60 reads/min quota** that gets exhausted easily
- The History tab, Split tab, and Slip Verify tab all read from Sheets
- A local SQLite DB eliminates those reads for historical data
- Live attendance/games still use Sheets (they need real-time sharing)

## Design

### Database schema

A single SQLite file at `.badminton.db` (in the app's working directory) with these tables:

```sql
-- One row per submitted session
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,          -- '2026-07-01'
    day_name TEXT NOT NULL,              -- 'จันทร์' / 'พุธ'
    court_hours_court9 REAL DEFAULT 0,
    court_hours_court10 REAL DEFAULT 0,
    shuttle_price REAL DEFAULT 100.0,
    total_shuttle_cost REAL DEFAULT 0,
    total_court_fees REAL DEFAULT 0,
    total_amount REAL DEFAULT 0,
    player_count INTEGER DEFAULT 0,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per player per session
CREATE TABLE session_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    player_name TEXT NOT NULL,
    player_type TEXT NOT NULL,           -- 'ประจำ' / 'ขาจร'
    attended BOOLEAN NOT NULL DEFAULT 0,
    games_played INTEGER DEFAULT 0,
    shuttle_cost REAL DEFAULT 0,
    court_fee REAL DEFAULT 0,
    total REAL DEFAULT 0,
    payment_status TEXT DEFAULT 'Pending',
    UNIQUE(session_id, player_name)
);

-- Games within each session
CREATE TABLE session_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    game_number INTEGER NOT NULL,
    players TEXT NOT NULL,               -- comma-separated
    shuttles INTEGER NOT NULL
);

CREATE INDEX idx_sessions_date ON sessions(date);
CREATE INDEX idx_session_players_session ON session_players(session_id);
CREATE INDEX idx_session_players_name ON session_players(player_name);
```

### Sync flow

1. **On "Submit day"** → after successfully writing to Google Sheets, also write/update the SQLite DB with the same data
2. **On app startup** → check if there's cached data in SQLite. If the DB is empty (first run), optionally backfill from existing Google Sheet data
3. **Reading summaries** → always read from SQLite first. Only fall back to Sheets if SQLite is empty

### Changes to `app.py`

**New file:** `summary_db.py`
- `init_db()` — create tables if not exist
- `save_session(session_data)` — insert/update a submitted session
- `get_all_sessions()` — return list of all sessions for History tab
- `get_session_summary()` — per-player totals, overall stats
- `get_player_history(player_name)` — a single player's history

**Changes in `app.py`:**
- Import `summary_db`
- Call `summary_db.init_db()` at startup
- In `submit_day_to_sheet()` — after successful sheet write, also call `summary_db.save_session()`
- In `view_history()` — query SQLite instead of `read_payments()`
- In `compute_split()` — prefer SQLite for historical splits

### Files to change

| File | Change |
|------|--------|
| `summary_db.py` | **New** — SQLite wrapper |
| `app.py` | Import + use summary_db in submit_day_to_sheet, view_history, compute_split |
| `requirements.txt` | Add `sqlite3` (stdlib — no change needed) |

### Verification

1. Submit a day → check `.badminton.db` has the new session
2. Open History tab → should load instantly (no Google API call)
3. Toggle offline → History tab still works
4. Submit another day → same date updates existing row, doesn't duplicate

### Risks & Tradeoffs

- **Staleness** — SQLite is only as fresh as the last "Submit day". If someone edits the sheet directly, the DB won't reflect it. The app reads live data (attendance, games) from Sheets for the current day, so this is acceptable.
- **First-run backfill** — for sessions that were already submitted before this feature was added, the DB will be empty. A one-time backfill script can read from Sheets and populate it.
- **Streamlit Cloud persistence** — SQLite files on Streamlit Cloud are **ephemeral** (lost on redeploy). This is meant for the self-hosted / local deployment. If needed later, we can add a toggle or fallback.

## Implementation order

1. Create `summary_db.py` with schema + CRUD functions
2. Add `summary_db.init_db()` to app startup
3. Wire `summary_db.save_session()` into `submit_day_to_sheet()`
4. Rewrite `view_history()` to read from SQLite
5. Rewrite `compute_split()` to read past sessions from SQLite
6. Test locally
7. Optionally: add backfill script for existing sessions
