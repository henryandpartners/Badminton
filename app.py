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
    max_games = max((g.get("shuttles", 0) for g in recorded_games), default=0)
    player_game_count = {p: 0 for p in present_names}
    player_shuttle_cost = {p: 0.0 for p in present_names}

    for i, g in enumerate(recorded_games):
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
        row[2] = "TRUE"  # checked in

        # Mark which games this player played
        games_played = 0
        for gi, g in enumerate(recorded_games):
            if player in g.get("players", []):
                col_idx = 3 + gi if gi < 15 else 17  # max 15 games
                if gi < 15:
                    row[col_idx] = "TRUE"
                games_played += 1

        row[18] = str(games_played)
        row[19] = f"{player_shuttle_cost.get(player, 0):.2f}"

        # Court cost for ขาจร only
        if player_types.get(player, "") == "ขาจร" and n_present > 0:
            court_share = total_court_cost / n_present
            row[20] = f"{court_share:.2f}"
            row[21] = f"{player_shuttle_cost.get(player, 0) + court_share:.2f}"
        else:
            row[21] = f"{player_shuttle_cost.get(player, 0):.2f}"

        row[22] = "FALSE"
        row[24] = "0"
        row[25] = "0"
        block.append(row)

    # Summary row
    summary = blank.copy()
    summary[0] = "รวมเซสชัน"
    summary[18] = str(sum(player_game_count.values()))
    summary[19] = f"{total_shuttle_cost:.2f}"
    summary[20] = f"{total_court_cost:.2f}"
    summary[21] = f"{total_shuttle_cost + total_court_cost:.2f}"
    summary[24] = "0"
    summary[25] = "0"
    block.append(summary)

    # Blank separator
    block.append(blank.copy())

    # Court section
    court_section = blank.copy()
    block.append(court_section)  # empty row for spacing

    court_header = blank.copy()
    court_header[0] = "ค่าเช่าสนาม (155 บาท/ชม./สนาม)"
    block.append(court_header)

    court_cols = blank.copy()
    court_cols[0] = "สนาม"
    court_cols[1] = "20:00-21:00"
    court_cols[2] = "21:00-22:00"
    court_cols[3] = "22:00-23:00"
    court_cols[4] = "ชั่วโมง"
    court_cols[5] = "ค่าใช้จ่าย"
    block.append(court_cols)

    court9 = blank.copy()
    court9[0] = "สนาม 9"
    h9 = court_hours.get("9", 0)
    # Mark hours used
    for h in range(h9):
        if h < 3:
            court9[1 + h] = "TRUE"
    court9[4] = str(h9)
    court9[5] = f"{h9 * COURT_HOUR_RATE:.2f}"
    block.append(court9)

    court10 = blank.copy()
    court10[0] = "สนาม 10"
    h10 = court_hours.get("10", 0)
    for h in range(h10):
        if h < 3:
            court10[1 + h] = "TRUE"
    court10[4] = str(h10)
    court10[5] = f"{h10 * COURT_HOUR_RATE:.2f}"
    block.append(court10)

    court_total = blank.copy()
    court_total[0] = "รวมค่าสนาม"
    court_total[4] = str(total_court_hours)
    court_total[5] = f"{total_court_cost:.2f}"
    block.append(court_total)

    # Blank row at end
    block.append(blank.copy())

    try:
        existing = conn.read(worksheet=tab, ttl=0)
        if existing is not None and not existing.empty:
            existing_df = existing.dropna(how="all")
            start_row = len(existing_df) + 2
        else:
            start_row = 1

        conn.update(worksheet=tab, data=block, cell=f"A{start_row}")
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
    ss.setdefault("attendance", {})        # {player_name: bool}
    ss.setdefault("court_hours", {c: 0 for c in COURTS})  # {court: hours}
    # games: list of {"players": [names], "shuttles": int}
    ss.setdefault("games", [])  # list of {"players": [names], "shuttles": int}


# =============================================================================
# VIEW 1 — On-Court Live Tracker
# =============================================================================
def view_live_tracker(players: pd.DataFrame) -> None:
    st.header("🏟️ On-Court Live Tracker")

    st.session_state.session_date = st.date_input(
        "Session date", value=st.session_state.session_date
    )

    # ---- Daily attendance grid -------------------------------------------
    st.subheader("✅ Attendance")
    if players.empty:
        st.info(
            f"No players found. Add player names to the '{ROSTER_WS}' worksheet."
        )
    else:
        st.caption("Tap a player to flag them **Present** for today.")
        names = players["Name"].tolist()
        cols = st.columns(2)  # two chunky columns of toggles on mobile
        for i, name in enumerate(names):
            with cols[i % 2]:
                st.session_state.attendance[name] = st.toggle(
                    name,
                    value=st.session_state.attendance.get(name, False),
                    key=f"att_{name}",
                )
        present_count = sum(1 for v in st.session_state.attendance.values() if v)
        st.metric("Players present", present_count)

    st.divider()

    # ---- Courts & hours ---------------------------------------------------
    st.subheader("🏟️ Courts & hours")
    st.caption(f"{COURT_HOUR_RATE:,.0f} THB per hour, per court — split equally among checked-in players.")
    for c in COURTS:
        st.session_state.court_hours[c] = st.radio(
            f"Court {c} — hours",
            options=COURT_HOUR_OPTIONS,
            index=COURT_HOUR_OPTIONS.index(st.session_state.court_hours.get(c, 0)),
            horizontal=True,
            key=f"court_{c}",
        )
    total_court_hours = sum(st.session_state.court_hours.values())
    total_court_cost = total_court_hours * COURT_HOUR_RATE
    st.caption(
        f"Court cost: {total_court_hours} court-hour(s) × {COURT_HOUR_RATE:,.0f} = "
        f"**{total_court_cost:,.0f} THB**"
    )

    st.divider()

    # ---- Per-game players + shuttles -------------------------------------
    st.subheader("🎮 Games & shuttles")
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    st.session_state.shuttle_price = st.number_input(
        "Shuttle price (THB each)",
        min_value=0.0,
        value=float(st.session_state.shuttle_price),
        step=10.0,
    )
    if not present_names:
        st.caption("Check players in above, then add games, pick who played, and set shuttles used.")
    else:
        st.caption(
            "Each game's shuttle cost is shared among its players "
            "(e.g. 1 shuttle, 4 players → 25 THB each)."
        )
        gc_add, gc_clear = st.columns(2)
        with gc_add:
            if st.button("➕ Add game", use_container_width=True):
                st.session_state.games.append({"players": [], "shuttles": 1})
        with gc_clear:
            if st.button("🗑️ Clear games", use_container_width=True):
                st.session_state.games = []

        for gi in range(len(st.session_state.games)):
            game = st.session_state.games[gi]
            with st.container(border=True):
                default = [p for p in game.get("players", []) if p in present_names]
                game["players"] = st.multiselect(
                    f"เกม {gi + 1} — players",
                    options=present_names,
                    default=default,
                    key=f"game_players_{gi}",
                )
                row = st.columns([3, 1])
                with row[0]:
                    game["shuttles"] = st.number_input(
                        "Shuttles used",
                        min_value=0,
                        value=int(game.get("shuttles", 1)),
                        step=1,
                        key=f"game_shuttles_{gi}",
                    )
                with row[1]:
                    st.write("")
                    if st.button("✕", key=f"delgame_{gi}", help="Remove this game"):
                        st.session_state.games.pop(gi)
                        st.rerun()
                np_ = len(game["players"])
                if np_:
                    per = game["shuttles"] * st.session_state.shuttle_price / np_
                    st.caption(
                        f"{game['shuttles']} shuttle(s) × {st.session_state.shuttle_price:,.0f} "
                        f"÷ {np_} = **{per:,.2f} THB each**"
                    )

    # ---- End of day: submit to sheet ---------------------------------------
    st.divider()
    st.subheader("📤 End of Day · Submit to Sheet")

    present_names = [n for n, v in st.session_state.attendance.items() if v]
    n_present = len(present_names)
    total_shuttle_cost = sum(
        g.get("shuttles", 0) for g in st.session_state.games
    ) * st.session_state.shuttle_price
    grand_total = total_court_cost + total_shuttle_cost

    # Preview
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Players", n_present)
    m2.metric("Court", f"{total_court_cost:,.0f} THB")
    m3.metric("Shuttles", f"{total_shuttle_cost:,.0f} THB")
    m4.metric("Total", f"{grand_total:,.0f} THB")

    st.caption(
        f"Submits to the **{get_month_tab(st.session_state.session_date)}** tab "
        f"under date **{st.session_state.session_date}**."
        " All games, court hours, and totals will be saved."
    )

    if st.button("📥 Submit day", type="primary", use_container_width=True):
        with st.spinner("Saving to Google Sheets…"):
            tab = get_month_tab(st.session_state.session_date)
            ok = submit_day_to_sheet(
                recorded_games=st.session_state.games,
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

    # Court cost split equally among checked-in players.
    total_court_hours = sum(st.session_state.court_hours.values())
    total_court_cost = total_court_hours * COURT_HOUR_RATE
    court_share = total_court_cost / count

    # Per-game shuttle cost shared among that game's players.
    price = float(st.session_state.shuttle_price)
    shuttle_cost = {name: 0.0 for name in present_names}
    games_played = {name: 0 for name in present_names}
    for g in st.session_state.games:
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
    n_games = len([g for g in st.session_state.games if g.get("players")])
    total_court_hours = sum(st.session_state.court_hours.values())
    total_court_cost = total_court_hours * COURT_HOUR_RATE
    total_shuttle_cost = sum(
        g.get("shuttles", 0) for g in st.session_state.games
    ) * st.session_state.shuttle_price

    m1, m2, m3 = st.columns(3)
    m1.metric("Court cost", f"{total_court_cost:,.0f}")
    m2.metric("Shuttle cost", f"{total_shuttle_cost:,.0f}")
    m3.metric("Players", f"{n_present}")

    st.caption(
        f"Court: {total_court_hours} court-hour(s) × {COURT_HOUR_RATE:,.0f} = "
        f"**{total_court_cost:,.0f}**, split equally → "
        f"**{(total_court_cost / n_present if n_present else 0):,.2f}/player**. "
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
