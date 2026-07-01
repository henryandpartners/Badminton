"""
One-time backfill: read existing session data from all monthly tabs
(2026-07 through 2026-12) and populate the local SQLite summary DB.

Run this once to seed `.badminton.db` with past sessions.
Usage:  python3 backfill_db.py
"""
import datetime as dt
import gspread
import summary_db as sdb
import re

# ── Load service account ──────────────────────────────────────────────
with open('.streamlit/secrets.toml') as f:
    content = f.read()

start = content.index('[connections.gsheets]')
section = content[start:]

sa = {}
for line in section.strip().split('\n'):
    line = line.strip()
    if not line or line.startswith('[') or line.startswith('#'):
        continue
    if '=' in line:
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k not in ('spreadsheet', 'worksheet'):
            v = bytes(v, 'utf-8').decode('unicode_escape')
            sa[k] = v

spreadsheet_url = None
for line in section.strip().split('\n'):
    if line.strip().startswith('spreadsheet'):
        spreadsheet_url = line.split('=', 1)[1].strip().strip('"')

gc = gspread.service_account_from_dict(sa)
sh = gc.open_by_url(spreadsheet_url)

# ── Roster ────────────────────────────────────────────────────────────
roster_ws = sh.worksheet('ผู้เล่น')
roster_data = roster_ws.get_all_values()
roster = {}
for row in roster_data[1:26]:
    name = row[0].strip() if row and row[0].strip() else ""
    ptype = row[1].strip() if len(row) > 1 and row[1].strip() else "ขาจร"
    if name and name != "ชื่อผู้เล่น":
        roster[name] = ptype

print(f"Roster: {len(roster)} players")

thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]

# ── Parse a session block ─────────────────────────────────────────────
def parse_block(rows, start_idx):
    """Parse a session block starting at start_idx.

    Returns (date_str, day_name, player_rows, summary_row) or None.
    """
    if start_idx >= len(rows):
        return None

    header = rows[start_idx][0] if rows[start_idx] else ""
    if not header or len(header) < 10 or header[4] != '-' or header[7] != '-':
        return None

    date_str = header[:10]
    try:
        date_obj = dt.date.fromisoformat(date_str)
    except ValueError:
        return None

    # Find the summary row
    summary_idx = None
    for i in range(start_idx + 2, min(start_idx + 40, len(rows))):
        if rows[i] and rows[i][0].strip() == "รวมเซสชัน":
            summary_idx = i
            break

    if summary_idx is None:
        return None

    # Player rows are between start_idx+2 and summary_idx
    player_rows_raw = rows[start_idx + 2 : summary_idx]
    player_rows = []
    for pr in player_rows_raw:
        name = pr[0].strip() if pr else ""
        if name and name not in ("ผู้เล่น", ""):
            row_data = {
                "name": name,
                "type": pr[1].strip() if len(pr) > 1 else "",
                "attended": pr[2].strip() if len(pr) > 2 else "",
                "games_played": int(float(pr[18])) if len(pr) > 18 and pr[18].strip() and pr[18].strip().replace('.','',1).replace('-','',1).isdigit() else 0,
                "shuttle_cost": float(pr[19]) if len(pr) > 19 and pr[19].strip() and pr[19].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
                "court_fee": float(pr[20]) if len(pr) > 20 and pr[20].strip() and pr[20].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
                "total": float(pr[21]) if len(pr) > 21 and pr[21].strip() and pr[21].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
            }
            player_rows.append(row_data)

    summary = {}
    if summary_idx < len(rows) and rows[summary_idx]:
        srow = rows[summary_idx]
        summary = {
            "total_games": int(float(srow[18])) if len(srow) > 18 and srow[18].strip() and srow[18].strip().replace('.','',1).replace('-','',1).isdigit() else 0,
            "shuttle_cost": float(srow[19]) if len(srow) > 19 and srow[19].strip() and srow[19].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
            "court_fee": float(srow[20]) if len(srow) > 20 and srow[20].strip() and srow[20].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
            "total": float(srow[21]) if len(srow) > 21 and srow[21].strip() and srow[21].strip().replace('.','',1).replace('-','',1).isdigit() else 0.0,
        }

    return (date_str, date_obj, player_rows, summary)


# ── Scan each month tab ───────────────────────────────────────────────
months = ['2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11', '2026-12']

sdb.init_db()
total_saved = 0

for tab_name in months:
    print(f"\n--- {tab_name} ---")
    ws = sh.worksheet(tab_name)
    all_rows = ws.get_all_values()
    print(f"  {len(all_rows)} total rows")

    # Find all session date headers
    i = 0
    sessions_found = 0
    while i < len(all_rows):
        parsed = parse_block(all_rows, i)
        if parsed is None:
            i += 1
            continue

        date_str, date_obj, player_rows, summary = parsed

        # Skip sessions with no data (all zeros, no one attended)
        attended = [p for p in player_rows if p.get("attended", "") == "TRUE"]
        if not attended:
            print(f"  Skipping {date_str}: no attendance data")
            i += 1
            continue

        day_name = thai_days[date_obj.weekday()]

        # Build data structures for save_session
        attendance = {p["name"]: p["attended"] == "TRUE" for p in player_rows}
        player_types = {}
        for p in player_rows:
            if p["name"] in roster:
                player_types[p["name"]] = roster[p["name"]]
            else:
                player_types[p["name"]] = p["type"] or "ขาจร"

        player_game_count = {p["name"]: p["games_played"] for p in player_rows if p["attended"] == "TRUE"}
        player_shuttle_cost = {p["name"]: p["shuttle_cost"] for p in player_rows if p["attended"] == "TRUE"}

        # We don't have court_hours or recorded_games from the tab format,
        # so use empty/defaults (per-player totals are accurate)
        ok = sdb.save_session(
            session_date=date_obj,
            day_name=day_name,
            court_hours={"9": 0, "10": 0},
            attendance=attendance,
            player_types=player_types,
            recorded_games=[],
            shuttle_price=100.0,
            player_game_count=player_game_count,
            player_shuttle_cost=player_shuttle_cost,
        )

        if ok:
            total_saved += 1
            n_attended = len(attended)
            print(f"  ✓ {date_str} ({day_name}) — {n_attended} players, {summary.get('total', 0):.0f} THB")
        else:
            print(f"  ✗ {date_str} — FAILED")

        sessions_found += 1
        # Move past this block (approx 25-30 rows per block)
        i += 1  # will scan forward from next row

    print(f"  Found {sessions_found} sessions in {tab_name}")

print(f"\n{'='*50}")
print(f"Total sessions saved to DB: {total_saved}")
print(f"DB stats: {sdb.get_stats()}")
