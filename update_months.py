"""
Update Jul-Dec 2026 month tabs to only have Mon/Wed session blocks.

Reads existing monthly summary (สรุปประจำเดือน) from each tab, builds new
session blocks for correct Mon/Wed dates, and replaces the tab content,
preserving the summary section at the bottom.
"""
import datetime as dt
import gspread

# ── Load service account ──────────────────────────────────────────────
import re
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
roster = []
for row in roster_data[1:26]:  # rows 2-26 (skip header row 1, stop before duplicate header)
    name = row[0].strip() if row and row[0].strip() else ""
    ptype = row[1].strip() if len(row) > 1 and row[1].strip() else "ขาจร"
    if name and name != "ชื่อผู้เล่น":
        roster.append((name, ptype))

print(f"Roster: {len(roster)} players")
for name, ptype in roster:
    print(f"  {name} ({ptype})")

# ── Thai day names ────────────────────────────────────────────────────
thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]

# ── Build session blocks for each month ───────────────────────────────
blank = [""] * 26

COL_HEADERS = {
    0: "ผู้เล่น", 1: "ประเภท", 2: "เช็คอิน",
    3: "เกม1", 4: "เกม2", 5: "เกม3", 6: "เกม4", 7: "เกม5",
    8: "เกม6", 9: "เกม7", 10: "เกม8", 11: "เกม9", 12: "เกม10",
    13: "เกม11", 14: "เกม12", 15: "เกม13", 16: "เกม14", 17: "เกม15",
    18: "จำนวนเกม", 19: "ค่าลูก", 20: "ค่าสนามขาจร", 21: "ยอดรวม",
    22: "โอน", 23: "เงินสด", 24: "จ่ายแล้ว", 25: "ค้างชำระ"
}

def make_player_rows():
    """Return 26-column rows for each roster player, all zeroed out."""
    rows = []
    for name, ptype in roster:
        row = blank.copy()
        row[0] = name
        row[1] = ptype
        row[2] = "FALSE"
        row[18] = "0"
        row[19] = "0"
        row[20] = "0"
        row[21] = "0"
        row[22] = "FALSE"
        row[24] = "0"
        row[25] = "0"
        rows.append(row)
    return rows

def make_session_block(date_obj: dt.date):
    """Build a full session block for the given date (empty data)."""
    block = []
    day_name = thai_days[date_obj.weekday()]
    date_str = date_obj.isoformat()

    # Date header
    r = blank.copy()
    r[0] = f"{date_str} {day_name} - สนาม 9 & 10 (20:00-23:00)"
    block.append(r)

    # Column headers
    r = blank.copy()
    for col, h in COL_HEADERS.items():
        r[col] = h
    block.append(r)

    # Player rows
    block.extend(make_player_rows())

    # Summary
    r = blank.copy()
    r[0] = "รวมเซสชัน"
    r[18] = "0"
    r[19] = "0"
    r[20] = "0"
    r[21] = "0"
    r[24] = "0"
    r[25] = "0"
    block.append(r)

    # Spacer
    block.append(blank.copy())

    # Court section
    r = blank.copy()
    r[0] = "ค่าเช่าสนาม (80 บาท/คน)"
    block.append(r)
    r = blank.copy()
    r[0] = "สนาม"
    r[1] = "จำนวนผู้เล่น"
    r[2] = "ค่าธรรมเนียม/คน"
    r[3] = "รวม"
    block.append(r)
    for cid in ["9", "10"]:
        r = blank.copy()
        r[0] = f"สนาม {cid}"
        r[1] = "0"
        r[2] = "80"
        r[3] = "0"
        block.append(r)
    r = blank.copy()
    r[0] = "รวมค่าสนาม"
    r[2] = "0"
    block.append(r)

    # Spacer between sessions
    block.append(blank.copy())
    return block

def update_tab(tab_name: str, dates: list):
    """Replace session blocks in a month tab, preserving the monthly summary."""
    ws = sh.worksheet(tab_name)

    # Read existing full content
    existing = ws.get_all_values()

    # Find where the monthly summary starts
    summary_start = None
    for i, row in enumerate(existing):
        if row and row[0].strip() == "สรุปประจำเดือน":
            summary_start = i  # 0-indexed
            break

    if summary_start is None:
        print(f"  ⚠ No monthly summary found in {tab_name}! Will just clear and write blocks.")
        summary_rows = []
    else:
        # Preserve everything from summary row onwards
        summary_rows = existing[summary_start:]
        print(f"  Preserving monthly summary starting at row {summary_start + 1} ({len(summary_rows)} rows)")

    # Build all session blocks
    all_blocks = []
    for d in dates:
        all_blocks.extend(make_session_block(d))

    # Total content
    n_cols = 26
    total_rows = all_blocks + summary_rows

    print(f"  Writing {len(all_blocks)} block rows + {len(summary_rows)} summary rows = {len(total_rows)} total")

    # Clear the entire worksheet and rewrite
    # Resize to fit
    ws.resize(rows=max(len(total_rows) + 5, 500), cols=n_cols)
    ws.clear()

    # Write all data
    n_rows = len(total_rows)
    end_col = chr(64 + n_cols)
    cell_range = f"A1:{end_col}{n_rows}"
    cell_list = ws.range(cell_range)

    idx = 0
    for row_data in total_rows:
        for val in row_data:
            cell_list[idx].value = val
            idx += 1
    # Pad remaining if range is bigger
    while idx < len(cell_list):
        cell_list[idx].value = ""
        idx += 1

    ws.update_cells(cell_list, value_input_option="USER_ENTERED")
    print(f"  ✓ {tab_name} updated with {len(dates)} sessions")
    return True


# ── Generate Mon/Wed dates for each month ──────────────────────────
months = {
    '2026-07': (7, 2026),
    '2026-08': (8, 2026),
    '2026-09': (9, 2026),
    '2026-10': (10, 2026),
    '2026-11': (11, 2026),
    '2026-12': (12, 2026),
}

for tab_name, (month, year) in months.items():
    print(f"\n{'='*60}")
    print(f"Processing {tab_name}...")
    print(f"{'='*60}")

    # Generate all Mon/Wed dates for this month
    dates = []
    current = dt.date(year, month, 1)
    if month == 12:
        end_day = 31
    else:
        end_day = (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day

    for day in range(1, end_day + 1):
        d = dt.date(year, month, day)
        if d.weekday() in (0, 2):  # Mon=0, Wed=2
            dates.append(d)

    print(f"  {len(dates)} sessions: {[str(d) for d in dates]}")

    update_tab(tab_name, dates)

print("\n✅ All tabs updated!")
