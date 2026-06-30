# 🏸 Badminton Team Tracker

A mobile-optimised **Streamlit** web app for tracking on-court badminton
sessions. It uses a **Google Sheet as the live backend** (read/write via
`st-gsheets-connection`), splits each session's cost, and reconciles
**bank-transfer slips** by reading the amount off the photo with **local OCR
(Tesseract)** — no third-party API or keys required.

Designed thumb-first: big high-contrast buttons and toggle chips that work on a
phone browser court-side.

---

## Features

| View | What it does |
|------|--------------|
| 🏟️ **Live Tracker** | Toggle player check-in, giant ➕/➖ shuttle counter, and **per-game player selection** (pick who played each game), plus the court fee per person. |
| 🧾 **Split** | Each player pays `court fee + their shuttle share`; the day's shuttle cost is split across games and shared among each game's players. Writes each row to the `Payments` tab. |
| 📥 **Slip Verify** | Drag-and-drop a JPG/PNG slip → OCR reads the amount → it's matched to the player who owes it → you confirm → their row flips `Pending → Paid`. Includes a manual-reconcile fallback. |
| 👥 **Roster** | Read-only list of players, read live from the `ผู้เล่น` worksheet. |
| 📊 **History** | Per-player and per-session summaries + outstanding-balance chart from the `Payments` tab. |

---

## Google Sheet schema

The app works against an existing Thai badminton sheet:

**`ผู้เล่น`** (existing roster — **read only**)
: Player names are read from the `ชื่อผู้เล่น` column. Member/casual type and
  monthly fees are ignored.

**`Payments`** (created and owned by the app)

| Date | Player | GamesPlayed | CourtFee | ShuttleShare | AmountDue | PaymentStatus |
|------|--------|-------------|----------|--------------|-----------|---------------|

The app **never** writes to the existing monthly attendance tabs or the
dashboard — only to its own `Payments` tab.

> Share the Sheet with your service account's `client_email` (Editor access).

---

## Setup

```bash
pip install -r requirements.txt

# Configure secrets (copy the template and fill in real values)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#   → paste your Google service-account JSON fields (slip OCR needs no keys)

streamlit run app.py
```

On **Streamlit Community Cloud**, paste the contents of
`secrets.toml.example` (filled in) into **App → Settings → Secrets** instead of
committing a file.

The real `.streamlit/secrets.toml` is git-ignored — only the `.example`
template is tracked.

---

## How the split works

Each checked-in player owes a **flat court fee** (default 80 THB) plus a
**shuttle share**:

```
Court    = court_fee_per_person                       (per checked-in player)

Shuttle  = total_shuttle_cost split across games; within each game the cost is
           shared equally among the players who played it. A player's shuttle
           share is the sum of their per-game shares.
           (If no games are recorded, shuttles are split equally instead.)

Amount Due = Court + Shuttle share
```

So playing more games — or games with fewer people — costs more. Locking writes
one `Payments` row per present player for that date; re-locking the same date is
idempotent (it replaces that date's rows).
