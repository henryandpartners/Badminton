"""
🏸 Badminton Team Tracker
=========================
A mobile-optimised Streamlit frontend for tracking on-court badminton sessions,
splitting costs, and reconciling bank-transfer slips against players by reading
the received amount — all backed live by a Google Sheet.

Backend schema (Google Sheet)
-----------------------------
Worksheet "ผู้เล่น" (existing roster — READ ONLY):
    Player names are read from the "ชื่อผู้เล่น" column. Member/casual type and
    monthly fees are intentionally ignored — costs are split flat.

Worksheet "Payments" (created and owned by this app):
    | Date | Player | GamesPlayed | CourtShare | ShuttleShare |
    | AmountDue | PaymentStatus |
    One row per checked-in player, per session date. The app never writes to
    the existing monthly attendance tabs or the dashboard.

Cost model:
  • Court: total court cost = (sum of hours booked across courts 9 & 10) ×
    155 THB/hour/court, split equally among all checked-in players.
  • Shuttles: each game's shuttle cost (shuttles × 100 THB) is shared equally
    among that game's players; a player's shuttle bill sums their per-game shares.

Reconciliation: players pay the organiser however they like; at end of day the
Slip Verify tab reads each received slip's amount and matches it to who owes it.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import io
import re

import gspread
import pandas as pd
import streamlit as st

# --- Optional third-party imports are guarded so the app still boots and shows
# --- a friendly message if a dependency is missing in the deployment env. -----
try:
    from streamlit_gsheets import GSheetsConnection
except Exception:  # pragma: no cover - import guard
    GSheetsConnection = None  # type: ignore

try:
    import pytesseract
    from PIL import Image
except Exception:  # pragma: no cover - import guard
    pytesseract = None  # type: ignore
    Image = None  # type: ignore


# =============================================================================
# Configuration & constants
# =============================================================================
# Roster lives in the existing Thai "players" worksheet; we only read the name
# column (member/casual type & fees are intentionally ignored — flat split).
ROSTER_WS = "ผู้เล่น"
ROSTER_NAME_COL = "ชื่อผู้เล่น"

# The app writes its own daily split + payment status to a dedicated tab so it
# never disturbs the existing monthly attendance tabs or the dashboard formulas.
PAYMENTS_WS = "Payments"

PAYMENTS_COLUMNS = [
    "Date",
    "Player",
    "GamesPlayed",
    "CourtShare",
    "ShuttleShare",
    "AmountDue",
    "PaymentStatus",
]

# Courts and pricing.
COURTS = ["9", "10"]               # court names available to book
COURT_HOUR_RATE = 155.0            # THB per hour, per court
COURT_HOUR_OPTIONS = [0, 1, 2, 3]  # bookable hours per court (0 = not used)
DEFAULT_SHUTTLE_PRICE = 100.0      # THB per shuttle

STATUS_PENDING = "Pending"
STATUS_PAID = "Paid"

# Cache TTL (seconds) for sheet reads. Short so the court view stays "live"
# without hammering the Google API on every rerun.
READ_TTL = 5

st.set_page_config(
    page_title="🏸 Badminton Tracker",
    page_icon="🏸",
    layout="centered",  # centred + mobile-first
    initial_sidebar_state="collapsed",
)


# =============================================================================
# Mobile-first styling — big thumb-friendly buttons & high contrast
# =============================================================================
def inject_mobile_css() -> None:
    st.markdown(
        """
        <style>
        /* Make every button large, bold and easy to tap on a phone court-side */
        .stButton > button {
            width: 100%;
            min-height: 3.25rem;
            font-size: 1.15rem;
            font-weight: 700;
            border-radius: 14px;
        }
        /* Giant counter buttons get extra height + contrast */
        div[data-testid="column"] .stButton > button {
            min-height: 3.75rem;
            font-size: 1.6rem;
        }
        /* Toggle chips: chunky tap target */
        .stCheckbox, .stToggle { font-size: 1.1rem; }
        /* Tighten default top padding so more fits above the fold on mobile */
        .block-container { padding-top: 1.5rem; padding-bottom: 4rem; }
        /* Metric values nice and large */
        div[data-testid="stMetricValue"] { font-size: 2.2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Google Sheets connection helpers (CRUD)
# =============================================================================
@st.cache_resource(show_spinner=False)
def get_connection():
    """Create (and cache) the GSheets connection object."""
    if GSheetsConnection is None:
        st.error(
            "`st-gsheets-connection` is not installed. "
            "Add it to requirements.txt and redeploy."
        )
        st.stop()
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception as exc:
        st.error(
            "Could not establish the Google Sheets connection. Check that "
            "`[connections.gsheets]` in your secrets is filled in with a valid "
            f"service-account key.\n\nDetails: {exc}"
        )
        st.stop()


@st.cache_resource(show_spinner=False)
def _get_gspread_worksheet(worksheet_name: str):
    """Get a raw ``gspread.Worksheet`` object for row-level operations.

    ``GSheetsConnection.update()`` **clears and rewrites** the entire worksheet
    — there is no ``cell`` parameter.  For operations like ``append_row()`` and
    ``delete_rows()`` we need the underlying ``gspread`` worksheet directly.

    Builds a ``gspread`` client from the same service-account key that
    ``st.connection("gsheets")`` uses, so permissions are identical.
    """
    try:
        sa_info = dict(st.secrets["connections"]["gsheets"])
        spreadsheet_url = sa_info.pop("spreadsheet", None)
        worksheet_name_fallback = sa_info.pop("worksheet", None)
        gc = gspread.service_account_from_dict(sa_info)

        sh = gc.open_by_url(spreadsheet_url) if spreadsheet_url else gc.open("Badminton Tracker")
        return sh.worksheet(worksheet_name)
    except Exception as exc:
        st.error(f"Could not access worksheet '{worksheet_name}': {exc}")
        raise


def read_players() -> pd.DataFrame:
    """Read the player roster from the Thai 'ผู้เล่น' worksheet.

    Reads only the name column, drops blanks / repeated headers, and
    de-duplicates while preserving order. Returns a frame with a single
    'Name' column (empty on failure).
    """
    conn = get_connection()
    try:
        df = conn.read(worksheet=ROSTER_WS, ttl=READ_TTL)
        df = df.dropna(how="all")
        # The roster's name column is the Thai header; fall back to first column.
        if ROSTER_NAME_COL in df.columns:
            names = df[ROSTER_NAME_COL]
        else:
            names = df.iloc[:, 0]
        names = names.fillna("").astype(str).str.strip()
        seen, ordered = set(), []
        for n in names:
            if not n or n == ROSTER_NAME_COL or n in seen:
                continue  # skip blanks, repeated header rows, and duplicates
            seen.add(n)
            ordered.append(n)
        return pd.DataFrame({"Name": ordered})
    except Exception as exc:  # pragma: no cover - network/runtime guard
        st.error(f"Could not read the '{ROSTER_WS}' worksheet: {exc}")
        return pd.DataFrame(columns=["Name"])


def read_payments() -> pd.DataFrame:
    """Read the app-managed Payments tab. Returns an empty frame on failure."""
    conn = get_connection()
    try:
        df = conn.read(worksheet=PAYMENTS_WS, ttl=READ_TTL)
        df = df.dropna(how="all")
        for col in PAYMENTS_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        return df[PAYMENTS_COLUMNS].reset_index(drop=True)
    except Exception:
        # Tab may be empty — that's fine.
        return pd.DataFrame(columns=PAYMENTS_COLUMNS)


def write_payments(df: pd.DataFrame) -> bool:
    """Overwrite the Payments tab with `df`. Returns True on success.

    `st-gsheets-connection`'s `update()` replaces the entire worksheet, so the
    caller must pass the *complete* desired Payments state.
    """
    conn = get_connection()
    try:
        clean = df[PAYMENTS_COLUMNS].copy()
        conn.update(worksheet=PAYMENTS_WS, data=clean)
        return True
    except Exception as exc:  # pragma: no cover - network/runtime guard
        st.error(f"Failed to write to the '{PAYMENTS_WS}' tab: {exc}")
        return False


# Map month number to existing sheet tab name
MONTH_TABS = {
    1: "2026-01", 2: "2026-02", 3: "2026-03", 4: "2026-04",
    5: "2026-05", 6: "2026-06",
    7: "2026-07", 8: "2026-08", 9: "2026-09",
    10: "2026-10", 11: "2026-11", 12: "2026-12",
}


def get_month_tab(date: dt.date) -> str:
    """Return the worksheet name for the given date's month."""
    return MONTH_TABS.get(date.month, f"{date.year}-{date.month:02d}")


# ── Live games (shared across all users via Google Sheet) ──────────────
LIVE_GAMES_WS = "LiveGames"

GAME_LOG_COLUMNS = ["Date", "GameNum", "Players", "Shuttles", "AddedBy"]

# ── Live check-in (attendance, shared across all users) ──────────────────
LIVE_CHECKIN_WS = "LiveCheckin"


def read_live_checkin(session_date: dt.date) -> dict[str, bool]:
    """Read today's attendance from the ``LiveCheckin`` worksheet.

    Returns ``{player_name: True}`` for every player listed in today's row.
    Returns an empty dict if no check-in row exists for *session_date*.
    """
    conn = get_connection()
    date_str = session_date.isoformat()
    try:
        df = conn.read(worksheet=LIVE_CHECKIN_WS, ttl=0)
        if df is None or df.empty:
            return {}
        df = df.dropna(how="all")
        # First column is the date; subsequent columns are player names.
        if df.columns[0] == "Date" or "Date" in str(df.columns[0]):
            col = df.iloc[:, 0].astype(str).str.strip()
            mask = col == date_str
            if not mask.any():
                return {}
            row = df[mask].iloc[0]
            players = [str(v).strip() for v in row.iloc[1:]
                       if pd.notna(v) and str(v).strip() and str(v).strip() != "nan"]
            return {p: True for p in players}
        return {}
    except Exception:
        return {}


def save_live_checkin(session_date: dt.date, attendance: dict[str, bool]) -> bool:
    """Write today's attendance to the ``LiveCheckin`` worksheet.

    Replaces any existing row for this date with a fresh row listing
    all players whose attendance value is ``True``.
    """
    conn = get_connection()
    date_str = session_date.isoformat()
    present = sorted([n for n, v in attendance.items() if v])
    try:
        ws = _get_gspread_worksheet(LIVE_CHECKIN_WS)
        # Read existing rows to find a date match
        df = conn.read(worksheet=LIVE_CHECKIN_WS, ttl=0)
        row_to_overwrite = None
        if df is not None and not df.empty:
            df = df.dropna(how="all")
            # Check if our date already exists
            col0 = df.iloc[:, 0].astype(str).str.strip()
            matches = col0[col0 == date_str].index.tolist()
            if matches:
                row_to_overwrite = matches[0] + 1  # 1-indexed, header is row 1

        new_row = [date_str] + present

        if row_to_overwrite is not None:
            # Update the existing row in place (gspread row update)
            # Build a range that covers all columns we need
            end_col = len(new_row)
            cell_range = f"A{row_to_overwrite}:{chr(64 + end_col)}{row_to_overwrite}"
            cell_list = ws.range(cell_range)
            for i, val in enumerate(new_row):
                cell_list[i].value = val
            # Clear any extra cells that might remain from a longer previous row
            for i in range(len(new_row), len(cell_list)):
                cell_list[i].value = ""
            ws.update_cells(cell_list, value_input_option="USER_ENTERED")
        else:
            # Append a new row
            ws.append_row(new_row, value_input_option="USER_ENTERED")
        return True
    except Exception as exc:
        st.error(f"Could not save attendance: {exc}")
        return False


def read_live_games(session_date: dt.date) -> list[dict]:
    """Read today's live games from the sheet. Returns list of game dicts."""
    conn = get_connection()
    date_str = session_date.isoformat()
    try:
        df = conn.read(worksheet=LIVE_GAMES_WS, ttl=0)
        if df is None or df.empty:
            return []
        df = df.dropna(how="all")
        # Filter to today's date
        if "Date" in df.columns:
            df["Date"] = df["Date"].astype(str).str.strip()
            todays = df[df["Date"] == date_str]
            games = []
            for _, row in todays.iterrows():
                players_str = str(row.get("Players", "")).strip()
                players = [p.strip() for p in players_str.split(",") if p.strip()]
                games.append({
                    "players": players,
                    "shuttles": int(float(str(row.get("Shuttles", 0)))),
                })
            return games
        return []
    except Exception:
        return []


def add_live_game(session_date: dt.date, players: list[str], shuttles: int) -> bool:
    """Add one game to the live sheet via raw gspread ``append_row()``.

    Anyone who opens the app sees it immediately — no ``cell`` parameter needed.
    """
    date_str = session_date.isoformat()
    try:
        ws = _get_gspread_worksheet(LIVE_GAMES_WS)

        # Read existing game numbers (via GSheetsConnection.read for simpler parsing)
        conn = get_connection()
        existing = conn.read(worksheet=LIVE_GAMES_WS, ttl=0)
        next_num = 1
        if existing is not None and not existing.empty:
            existing = existing.dropna(how="all")
            if "GameNum" in existing.columns:
                nums = existing["GameNum"].dropna().astype(int).tolist()
                if nums:
                    next_num = max(nums) + 1

        row = [date_str, next_num, ", ".join(players), shuttles, "app"]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as exc:
        st.error(f"Could not add game: {exc}")
        return False


def delete_last_game(session_date: dt.date) -> bool:
    """Remove the last game for today from the live sheet via ``delete_rows()``."""
    date_str = session_date.isoformat()
    try:
        conn = get_connection()
        df = conn.read(worksheet=LIVE_GAMES_WS, ttl=0)
        if df is None or df.empty:
            return False
        df = df.dropna(how="all")
        if "Date" not in df.columns:
            return False
        dates = df["Date"].astype(str).str.strip()
        today_mask = dates == date_str
        if not today_mask.any():
            return False
        # Find the last row for today and remove it via gspread delete_rows
        today_idxs = df[today_mask].index.tolist()
        last_idx = today_idxs[-1]
        row_num = last_idx + 2  # 1-indexed + header row
        ws = _get_gspread_worksheet(LIVE_GAMES_WS)
        ws.delete_rows(row_num)
        return True
    except Exception:
        return False


# ── End-of-day: submit full block to monthly tab ──────────────────────

def submit_day_to_sheet(recorded_games: list, session_date: dt.date, court_hours: dict,
                        attendance: dict, shuttle_price: float) -> bool:
    """Submit the entire day to the monthly tab, matching the existing sheet format.

    Writes a block per date with:
      Row 0: Date header  (e.g. "2026-07-01 จันพุธ - สนาม 9 & 10 (20:00-23:00)")
      Row 1: Column headers (ผู้เล่น, ประเภท, เช็คอิน, เกม1..เกม15, จำนวนเกม, etc.)
      Rows 2+: Each player with their game checkboxes + shuttle/court costs
      Summary: รวมเซสชัน
      Court section: ค่าเช่าสนาม → court hours table
    """
    conn = get_connection()
    tab = get_month_tab(session_date)
    date_str = session_date.isoformat()
    price = shuttle_price

    # Map day name to Thai
    thai_days = ["จัน", "อัง", "พุธ", "พฤ", "ศุก", "เสา", "อาทิ"]
    day_name = thai_days[session_date.weekday()]

    # Present players list
    present = [n for n, v in attendance.items() if v]
    present_names = sorted(present) if present else []
    n_present = len(present_names)

    # Read full roster to get player types (ประจำ/ขาจร)
    roster_data = conn.read(worksheet=ROSTER_WS, ttl=0)
    player_types = {}
    if roster_data is not None and not roster_data.empty:
        df = roster_data.dropna(how="all")
        if len(df.columns) >= 2:
            name_col = "ชื่อผู้เล่น" if "ชื่อผู้เล่น" in df.columns else df.columns[0]
            type_col = "ประเภท" if "ประเภท" in df.columns else df.columns[1]
            for _, row in df.iterrows():
                nm = str(row[name_col]).strip()
                tp = str(row[type_col]).strip() if pd.notna(row[type_col]) else ""
                if nm and nm != name_col:
                    player_types[nm] = tp

    # Court usage
    total_court_hours = sum(court_hours.values())
    total_court_cost = total_court_hours * COURT_HOUR_RATE

    # Game analysis
    player_game_count = {p: 0 for p in present_names}
    player_shuttle_cost = {p: 0.0 for p in present_names}

    for g in recorded_games:
        players_in_game = [p for p in g.get("players", []) if p in player_game_count]
        cost = g.get("shuttles", 0) * price
        per = cost / len(players_in_game) if players_in_game else 0
        for p in players_in_game:
            player_game_count[p] = player_game_count.get(p, 0) + 1
            player_shuttle_cost[p] = player_shuttle_cost.get(p, 0) + per

    total_shuttle_cost = sum(player_shuttle_cost.values())

    # Build the block rows
    block = []
    blank = [""] * 26

    # Row 0: Date header
    date_header = f"{date_str} {day_name} - สนาม 9 & 10 (20:00-23:00)"
    row0 = blank.copy()
    row0[0] = date_header
    block.append(row0)

    # Row 1: Column headers
    row1 = blank.copy()
    headers = {
        0: "ผู้เล่น", 1: "ประเภท", 2: "เช็คอิน",
        3: "เกม1", 4: "เกม2", 5: "เกม3", 6: "เกม4", 7: "เกม5",
        8: "เกม6", 9: "เกม7", 10: "เกม8", 11: "เกม9", 12: "เกม10",
        13: "เกม11", 14: "เกม12", 15: "เกม13", 16: "เกม14", 17: "เกม15",
        18: "จำนวนเกม", 19: "ค่าลูก", 20: "ค่าสนามขาจร", 21: "ยอดรวม",
        22: "โอน", 23: "เงินสด", 24: "จ่ายแล้ว", 25: "ค้างชำระ"
    }
    for col, h in headers.items():
        row1[col] = h
    block.append(row1)

    # Player rows
    for player in present_names:
        row = blank.copy()
        row[0] = player
        row[1] = player_types.get(player, "ขาจร")
        row[2] = "TRUE"

        games_played = 0
        for gi, g in enumerate(recorded_games):
            if player in g.get("players", []):
                if gi < 15:
                    row[3 + gi] = "TRUE"
                games_played += 1

        row[18] = str(games_played)
        row[19] = f"{player_shuttle_cost.get(player, 0):.2f}"

        # Flat court fee: 80 THB per person (for both ประจำ and ขาจร)
        court_per_player = 80.0
        row[20] = f"{court_per_player:.2f}"
        row[21] = f"{player_shuttle_cost.get(player, 0) + court_per_player:.2f}"

        row[22] = "FALSE"
        row[24] = "0"
        row[25] = "0"
        block.append(row)

    # Summary row
    total_court_fees = n_present * 80.0
    summary = blank.copy()
    summary[0] = "รวมเซสชัน"
    summary[18] = str(sum(player_game_count.values()))
    summary[19] = f"{total_shuttle_cost:.2f}"
    summary[20] = f"{total_court_fees:.2f}"
    summary[21] = f"{total_shuttle_cost + total_court_fees:.2f}"
    summary[24] = "0"
    summary[25] = "0"
    block.append(summary)

    block.append(blank.copy())  # spacer

    # Court section (flat fee: 80 THB per player)
    court_header = blank.copy()
    court_header[0] = "ค่าเช่าสนาม (80 บาท/คน)"
    block.append(court_header)

    court_cols = blank.copy()
    court_cols[0] = "สนาม"
    court_cols[1] = "จำนวนผู้เล่น"
    court_cols[2] = "ค่าธรรมเนียม/คน"
    court_cols[3] = "รวม"
    block.append(court_cols)

    for court_id in ["9", "10"]:
        cr = blank.copy()
        cr[0] = f"สนาม {court_id}"
        h = court_hours.get(court_id, 0)
        cr[1] = str(n_present)
        cr[2] = "80"
        cr[3] = f"{n_present * 80.0:.2f}"
        block.append(cr)

    court_total = blank.copy()
    court_total[0] = "รวมค่าสนาม"
    court_total[2] = f"{n_present * 80.0:.2f}"
    block.append(court_total)

    block.append(blank.copy())

    try:
        ws = _get_gspread_worksheet(tab)
        # Find the next empty row (after existing content)
        existing = conn.read(worksheet=tab, ttl=0)
        if existing is not None and not existing.empty:
            existing_df = existing.dropna(how="all")
            start_row = len(existing_df) + 2
        else:
            start_row = 1
        # Update a range of cells starting at the computed start_row
        n_rows = len(block)
        n_cols = max(len(r) for r in block) if block else 1
        end_col_letter = chr(64 + n_cols) if n_cols <= 26 else "Z"
        cell_range = f"A{start_row}:{end_col_letter}{start_row + n_rows - 1}"
        cell_list = ws.range(cell_range)
        idx = 0
        for row in block:
            for val in row:
                cell_list[idx].value = val
                idx += 1
        ws.update_cells(cell_list, value_input_option="USER_ENTERED")
        return True
    except Exception as exc:
        st.error(f"Could not submit to tab '{tab}': {exc}")
        return False


def upsert_session_rows(session_rows: pd.DataFrame) -> bool:
    """Insert/replace all Payments rows for the session's date.

    Removes any pre-existing rows for the same Date (idempotent re-locking)
    and appends the freshly calculated rows, then pushes the whole tab back.
    """
    if session_rows.empty:
        st.warning("No checked-in players to write.")
        return False

    session_date = str(session_rows["Date"].iloc[0])
    existing = read_payments()
    # Drop prior rows for this date so re-running the split is idempotent.
    kept = existing[existing["Date"].astype(str) != session_date]
    combined = pd.concat([kept, session_rows], ignore_index=True)
    return write_payments(combined)


# =============================================================================
# Slip Matching Engine (local OCR — reads the amount printed on the slip)
# -----------------------------------------------------------------------------
# This reads the numbers printed on the uploaded slip image with Tesseract and
# matches them against what players still owe. It does NOT verify with the bank
# that the transfer actually happened — fine for a trusted group; swap in a
# verification API (e.g. SlipOk) if you need fraud-proofing.
# =============================================================================
# Matches Thai-slip money tokens: 1,234.56 / 1234.56 / 100 / ฿100.00 etc.
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?")


def extract_amounts_from_image(image_bytes: bytes) -> list[float]:
    """OCR the slip and return all plausible money amounts found, de-duplicated.

    Amounts on Thai bank slips are Arabic numerals, so English OCR is enough.
    Returns a sorted (desc) list of unique floats; empty list if none / OCR
    unavailable.
    """
    if pytesseract is None or Image is None:
        st.error(
            "OCR engine not available. Ensure `pytesseract` + `Pillow` are "
            "installed and the `tesseract-ocr` system package is present "
            "(packages.txt on Streamlit Cloud)."
        )
        return []
    try:
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
    except Exception as exc:  # pragma: no cover - runtime guard
        st.error(f"Could not read the image: {exc}")
        return []

    amounts: set[float] = set()
    for token in _AMOUNT_RE.findall(text):
        cleaned = token.replace(",", "")
        try:
            val = float(cleaned)
        except ValueError:
            continue
        # Ignore obviously-not-a-fee numbers (years, account digits, 0).
        if 0 < val < 1_000_000:
            amounts.add(round(val, 2))
    return sorted(amounts, reverse=True)


def match_amounts_to_pending(ledger: pd.DataFrame, amounts: list[float], tol: float = 0.5):
    """Return pending ledger rows whose AmountDue equals any extracted amount.

    Returns a list of (index, row) tuples — usually one, but can be several if
    multiple players owe the same amount, in which case the caller disambiguates.
    """
    if ledger.empty or not amounts:
        return []
    pending = ledger[
        ledger["PaymentStatus"].astype(str).str.lower() == STATUS_PENDING.lower()
    ]
    if pending.empty:
        return []
    due = pd.to_numeric(pending["AmountDue"], errors="coerce")
    matches = []
    for idx, owed in due.items():
        if pd.isna(owed):
            continue
        if any(abs(float(owed) - a) <= tol for a in amounts):
            matches.append((idx, ledger.loc[idx]))
    return matches


def mark_player_paid(payments: pd.DataFrame, idx) -> bool:
    """Flip a single Payments row to Paid and write the whole tab back."""
    payments.loc[idx, "PaymentStatus"] = STATUS_PAID
    return write_payments(payments)


# =============================================================================
# Session state initialisation
# =============================================================================
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("session_date", dt.date.today())
    ss.setdefault("shuttle_price", DEFAULT_SHUTTLE_PRICE)
    # Try loading attendance from the shared LiveCheckin sheet
    if "attendance" not in ss:
        ss["attendance"] = read_live_checkin(ss["session_date"])
    ss.setdefault("court_hours", {c: 0 for c in COURTS})  # {court: hours}
    # Games are read live from the sheet — no local state needed


# =============================================================================
# VIEW 1 — On-Court Live Tracker
# =============================================================================
def view_live_tracker(players: pd.DataFrame) -> None:
    st.header("🏟️ On-Court Live Tracker")

    # If the user changes the date, re-load attendance from the shared sheet.
    prev_date = st.session_state.get("_prev_live_date")
    session_date = st.date_input(
        "Session date", value=st.session_state.session_date
    )
    if prev_date is not None and session_date != prev_date:
        st.session_state.session_date = session_date
        st.session_state.attendance = read_live_checkin(session_date)
        st.session_state["_prev_live_date"] = session_date
        st.rerun()
    st.session_state.session_date = session_date
    st.session_state["_prev_live_date"] = session_date

    # ---- Daily attendance grid -------------------------------------------
    st.subheader("✅ Attendance")
    if players.empty:
        st.info(
            f"No players found. Add player names to the '{ROSTER_WS}' worksheet."
        )
    else:
        st.caption("Tap a player to flag them **Present** for today.")
        names = players["Name"].tolist()
        cols = st.columns(2)
        for i, name in enumerate(names):
            with cols[i % 2]:
                st.session_state.attendance[name] = st.toggle(
                    name,
                    value=st.session_state.attendance.get(name, False),
                    key=f"att_{name}",
                )
        present_count = sum(1 for v in st.session_state.attendance.values() if v)
        st.metric("Players present", present_count)

        # Auto-save attendance to shared sheet whenever a toggle changes
        if "attendance_snapshot" not in st.session_state:
            st.session_state.attendance_snapshot = dict(st.session_state.attendance)
        if st.session_state.attendance != st.session_state.attendance_snapshot:
            save_live_checkin(st.session_state.session_date, st.session_state.attendance)
            st.session_state.attendance_snapshot = dict(st.session_state.attendance)

    st.divider()

    # ---- Courts & hours ---------------------------------------------------
    st.subheader("🏟️ Courts & hours")
    st.caption("Court hours shown below for your reference. Court fee is a flat **80 THB/player**.")
    for c in COURTS:
        st.session_state.court_hours[c] = st.radio(
            f"Court {c} — hours",
            options=COURT_HOUR_OPTIONS,
            index=COURT_HOUR_OPTIONS.index(st.session_state.court_hours.get(c, 0)),
            horizontal=True,
            key=f"court_{c}",
        )
    total_court_hours = sum(st.session_state.court_hours.values())
    present_count = sum(1 for v in st.session_state.attendance.values() if v)
    total_court_cost = present_count * 80
    st.caption(
        f"Court cost: {present_count} players × 80 THB = **{total_court_cost:,.0f} THB** (not hourly)"
    )

    st.divider()

    # ---- Live games (shared across all users) -------------------------------
    st.subheader("🎮 Games")
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    st.session_state.shuttle_price = st.number_input(
        "Shuttle price (THB each)",
        min_value=0.0,
        value=float(st.session_state.shuttle_price),
        step=10.0,
    )

    # Read live games from sheet
    live_games = read_live_games(st.session_state.session_date)

    # Show current games list
    if live_games:
        st.markdown(f"**{len(live_games)} game(s) recorded today:**")
        for i, g in enumerate(live_games, start=1):
            players_str = ", ".join(g["players"])
            fee = g["shuttles"] * st.session_state.shuttle_price / max(len(g["players"]), 1)
            st.markdown(f"**Game {i}** · {g['shuttles']} shuttle(s) · {players_str} — _{fee:.0f} THB/player_")
    else:
        st.info("No games yet. Add the first game below!")

    # Quick totals preview
    if live_games:
        total_shuttle_cost = sum(g["shuttles"] for g in live_games) * st.session_state.shuttle_price
        present_count = sum(1 for v in st.session_state.attendance.values() if v)
        court_cost = present_count * 80
        st.caption(
            f"Running total: 🏸 {total_shuttle_cost:.0f} THB shuttles + "
            f"🏟️ {court_cost:.0f} THB court = **{total_shuttle_cost + court_cost:.0f} THB**"
        )

    st.divider()

    # ---- Add a new game ----
    st.subheader("➕ Add a Game")

    if not present_names:
        st.caption("Check players in above first.")
    else:
        # Find next game number
        next_game = len(live_games) + 1
        st.markdown(f"**Game {next_game}** — who played?")

        # Player selector — use multiselect for flexibility
        selected_players = st.multiselect(
            "Select players for this game",
            options=present_names,
            key="add_game_players",
        )

        shuttle_count = st.number_input(
            "Shuttles used",
            min_value=0, max_value=20, value=1, step=1,
            key="add_game_shuttles",
        )

        col_add, col_undo = st.columns(2)
        with col_add:
            if st.button("🎯 Add game", type="primary", use_container_width=True):
                if not selected_players:
                    st.warning("Select at least one player!")
                else:
                    ok = add_live_game(
                        st.session_state.session_date,
                        list(selected_players),
                        shuttle_count,
                    )
                    if ok:
                        st.success(f"Game {next_game} added! Everyone can see it now.")
                        st.rerun()
        with col_undo:
            if st.button("↩️ Undo last", use_container_width=True):
                if live_games:
                    ok = delete_last_game(st.session_state.session_date)
                    if ok:
                        st.rerun()
                else:
                    st.info("No games to undo.")

    st.divider()

    # ---- End of day: submit to monthly tab ----------------------------------
    st.subheader("📤 End of Day · Submit to Monthly Tab")

    n_present = len(present_names)
    total_shuttle_cost = sum(g["shuttles"] for g in live_games) * st.session_state.shuttle_price
    court_cost = n_present * 80
    grand_total = court_cost + total_shuttle_cost

    # Preview
    m1, m2, m3 = st.columns(3)
    m1.metric("Players", n_present)
    m2.metric("Court", f"{court_cost:,.0f} THB")
    m3.metric("Shuttles", f"{total_shuttle_cost:,.0f} THB")

    if st.button("📥 Submit day", type="primary", use_container_width=True):
        with st.spinner("Saving to Google Sheets…"):
            tab = get_month_tab(st.session_state.session_date)
            ok = submit_day_to_sheet(
                recorded_games=live_games,
                session_date=st.session_state.session_date,
                court_hours=st.session_state.court_hours,
                attendance=st.session_state.attendance,
                shuttle_price=float(st.session_state.shuttle_price),
            )
            if ok:
                st.success(f"✅ Day saved to '{tab}' under {st.session_state.session_date}!")
                st.balloons()


# =============================================================================

# =============================================================================
# VIEW 3 — End-of-Day Split
# =============================================================================
def compute_split(players: pd.DataFrame) -> pd.DataFrame:
    """Build the per-player split DataFrame for the active session date.

    Cost model:
      • Court: total court cost = (sum of hours across courts) × COURT_HOUR_RATE,
        split equally among all checked-in players.
      • Shuttles: each game's shuttle cost (shuttles × price) is shared equally
        among that game's players. A player's shuttle share is the sum of their
        per-game shares.
    """
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    count = len(present_names)
    if count == 0:
        return pd.DataFrame(columns=PAYMENTS_COLUMNS)

    # Court cost: flat 80 THB per checked-in player
    court_share = 80.0

    # Per-game shuttle cost shared among that game's players.
    price = float(st.session_state.shuttle_price)
    shuttle_cost = {name: 0.0 for name in present_names}
    games_played = {name: 0 for name in present_names}
    live_games = read_live_games(st.session_state.session_date)
    for g in live_games:
        valid = [p for p in g.get("players", []) if p in shuttle_cost]
        if not valid:
            continue
        game_cost = g.get("shuttles", 0) * price
        per = game_cost / len(valid)
        for p in valid:
            shuttle_cost[p] += per
            games_played[p] += 1

    rows = []
    for name in present_names:
        cs = round(court_share, 2)
        ss_ = round(shuttle_cost[name], 2)
        rows.append(
            {
                "Date": str(st.session_state.session_date),
                "Player": name,
                "GamesPlayed": games_played[name],
                "CourtShare": cs,
                "ShuttleShare": ss_,
                "AmountDue": round(cs + ss_, 2),
                "PaymentStatus": STATUS_PENDING,
            }
        )
    return pd.DataFrame(rows, columns=PAYMENTS_COLUMNS)


def view_ledger(players: pd.DataFrame) -> None:
    st.header("🧾 End-of-Day Split")

    present_names = [n for n, v in st.session_state.attendance.items() if v]
    if not present_names:
        st.info("No players are checked in yet. Use the **Live Tracker** first.")
        return

    n_present = len(present_names)
    total_court_cost = n_present * 80.0
    live_games = read_live_games(st.session_state.session_date)
    n_games = len(live_games)
    total_shuttle_cost = sum(
        g.get("shuttles", 0) for g in live_games
    ) * st.session_state.shuttle_price

    m1, m2, m3 = st.columns(3)
    m1.metric("Court (80/คน)", f"{total_court_cost:,.0f}")
    m2.metric("Shuttle cost", f"{total_shuttle_cost:,.0f}")
    m3.metric("Players", f"{n_present}")

    st.caption(
        f"Court: **80 THB/player** × {n_present} = **{total_court_cost:,.0f} THB**. "
        f"Shuttles: {total_shuttle_cost:,.0f} THB across {n_games} game(s), "
        f"each game shared among its players."
    )

    split_df = compute_split(players)

    st.subheader("Split summary")
    st.dataframe(split_df, use_container_width=True, hide_index=True)

    # ---- Lock & write back to the sheet ----------------------------------
    if st.button("🔒 Lock totals & write to Payments tab", type="primary"):
        with st.spinner("Writing to the Payments tab…"):
            if upsert_session_rows(split_df):
                st.session_state.locked_split = split_df
                st.success("Saved to the Payments tab. ✅")
                st.balloons()

    st.caption(
        "Collect payments as usual, then reconcile in the **Slip Verify** tab — "
        "upload the slips you received and they're matched to who owes that amount."
    )


# =============================================================================
# VIEW 3 — Slip Verification Dashboard
# =============================================================================
def _manual_reconcile(ledger: pd.DataFrame, key_prefix: str) -> None:
    """Fallback: pick a pending player and mark them Paid by hand."""
    pending = ledger[
        ledger["PaymentStatus"].astype(str).str.lower() == STATUS_PENDING.lower()
    ]
    if pending.empty:
        st.info("No pending players to reconcile.")
        return
    labels = {
        f"{r['Player']} — {float(r['AmountDue']):,.2f} THB ({r['Date']})": i
        for i, r in pending.iterrows()
    }
    choice = st.selectbox(
        "Mark a player paid manually", list(labels.keys()), key=f"{key_prefix}_sel"
    )
    if st.button("Mark as Paid", key=f"{key_prefix}_btn"):
        idx = labels[choice]
        with st.spinner("Updating Google Sheet…"):
            if mark_player_paid(ledger, idx):
                st.success(f"✅ {ledger.loc[idx, 'Player']} marked as Paid.")
                st.rerun()


def view_slip_verification() -> None:
    st.header("📥 Slip Verification")
    st.caption(
        "Drop a bank-transfer slip. We read the amount printed on it (OCR) and "
        "match it to the player who owes that amount — then you **confirm** to "
        "mark them Paid. (Reads the image only; doesn't verify with the bank.)"
    )

    ledger = read_payments()

    uploaded = st.file_uploader(
        "Upload transfer slip (JPG / PNG)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=False,
    )

    if uploaded is not None:
        st.image(uploaded, caption="Uploaded slip", width=220)
        if st.button("🔍 Read slip & match", type="primary"):
            with st.spinner("Reading slip with OCR…"):
                st.session_state["slip_amounts"] = extract_amounts_from_image(
                    uploaded.getvalue()
                )

        amounts = st.session_state.get("slip_amounts")
        if amounts is not None:
            if not amounts:
                st.warning(
                    "Couldn't read any amount from this slip. Try a clearer photo, "
                    "or reconcile manually below."
                )
            else:
                st.caption(
                    "Amounts read from slip: "
                    + ", ".join(f"{a:,.2f}" for a in amounts)
                )
                matches = match_amounts_to_pending(ledger, amounts)
                if not matches:
                    st.warning(
                        "No pending player owes any amount found on this slip. "
                        "Reconcile manually below."
                    )
                else:
                    st.success(
                        f"Matched {len(matches)} pending player(s). "
                        "Confirm to mark Paid:"
                    )
                    for idx, row in matches:
                        with st.container(border=True):
                            cols = st.columns([3, 2])
                            cols[0].markdown(
                                f"**{row['Player']}** — "
                                f"{float(row['AmountDue']):,.2f} THB ({row['Date']})"
                            )
                            if cols[1].button("✅ Confirm Paid", key=f"confirm_{idx}"):
                                with st.spinner("Updating Google Sheet…"):
                                    if mark_player_paid(ledger, idx):
                                        st.success(f"{row['Player']} marked as Paid!")
                                        st.balloons()
                                        st.session_state.pop("slip_amounts", None)
                                        st.rerun()

    st.divider()

    # Always-visible context: today's payment status.
    if not ledger.empty:
        today = str(st.session_state.session_date)
        todays = ledger[ledger["Date"].astype(str) == today]
        if not todays.empty:
            st.subheader("Today's payment status")
            st.dataframe(
                todays[["Player", "AmountDue", "PaymentStatus"]],
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("✋ Manual reconcile"):
        _manual_reconcile(ledger, "manual")


# =============================================================================
# VIEW 4 — Roster (read-only)
# =============================================================================
def view_roster(players: pd.DataFrame) -> None:
    st.header("👥 Roster")
    st.caption(
        f"Players are read live from the '{ROSTER_WS}' worksheet. Add or remove "
        "players there — this view is read-only so the app never overwrites "
        "your existing roster columns."
    )
    if players.empty:
        st.info(f"No players found in '{ROSTER_WS}'.")
        return
    st.metric("Players in roster", len(players))
    st.dataframe(players[["Name"]], use_container_width=True, hide_index=True)


# =============================================================================
# VIEW 5 — Season History
# =============================================================================
def view_history() -> None:
    st.header("📊 Season History")
    ledger = read_payments()
    if ledger.empty:
        st.info("No sessions recorded yet. Lock a session to start building history.")
        return

    led = ledger.copy()
    led["AmountDue"] = pd.to_numeric(led["AmountDue"], errors="coerce").fillna(0.0)
    led["GamesPlayed"] = pd.to_numeric(led["GamesPlayed"], errors="coerce").fillna(0)
    status = led["PaymentStatus"].astype(str).str.lower()
    led["_paid"] = status.eq(STATUS_PAID.lower())

    # ---- Top-line season metrics -----------------------------------------
    total_collected = led.loc[led["_paid"], "AmountDue"].sum()
    total_outstanding = led.loc[~led["_paid"], "AmountDue"].sum()
    n_sessions = led["Date"].astype(str).nunique()
    m1, m2, m3 = st.columns(3)
    m1.metric("Sessions", n_sessions)
    m2.metric("Collected", f"{total_collected:,.0f}")
    m3.metric("Outstanding", f"{total_outstanding:,.0f}")

    # ---- Per-player summary ----------------------------------------------
    st.subheader("Per player")
    per_player = (
        led.groupby("Player")
        .agg(
            Sessions=("Date", "nunique"),
            TotalDue=("AmountDue", "sum"),
            Paid=("AmountDue", lambda s: s[led.loc[s.index, "_paid"]].sum()),
        )
        .reset_index()
    )
    per_player["Outstanding"] = per_player["TotalDue"] - per_player["Paid"]
    per_player = per_player.sort_values("Outstanding", ascending=False)
    st.dataframe(
        per_player,
        use_container_width=True,
        hide_index=True,
        column_config={
            "TotalDue": st.column_config.NumberColumn(format="%.2f"),
            "Paid": st.column_config.NumberColumn(format="%.2f"),
            "Outstanding": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    # ---- Per-session summary ---------------------------------------------
    st.subheader("Per session")
    per_session = (
        led.groupby("Date")
        .agg(
            Players=("Player", "nunique"),
            Games=("GamesPlayed", "max"),
            Total=("AmountDue", "sum"),
            Paid=("_paid", "sum"),
        )
        .reset_index()
        .sort_values("Date", ascending=False)
    )
    st.dataframe(
        per_session,
        use_container_width=True,
        hide_index=True,
        column_config={"Total": st.column_config.NumberColumn(format="%.2f")},
    )

    # ---- Outstanding-by-player chart -------------------------------------
    chart_data = per_player[per_player["Outstanding"] > 0].set_index("Player")[
        ["Outstanding"]
    ]
    if not chart_data.empty:
        st.subheader("Who still owes")
        st.bar_chart(chart_data)


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    inject_mobile_css()
    init_state()

    st.title("🏸 Badminton Team Tracker")

    players = read_players()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "🏟️ Live Tracker",
            "🧾 Split",
            "📥 Slip Verify",
            "👥 Roster",
            "📊 History",
        ]
    )
    with tab1:
        view_live_tracker(players)
    with tab2:
        view_ledger(players)
    with tab3:
        view_slip_verification()
    with tab4:
        view_roster(players)
    with tab5:
        view_history()

    st.caption("Backed live by Google Sheets · OCR slip reading")


if __name__ == "__main__":
    main()
