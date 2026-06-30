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
    | Date | Player | GamesPlayed | CourtFee | ShuttleShare |
    | AmountDue | PaymentStatus |
    One row per checked-in player, per session date. The app never writes to
    the existing monthly attendance tabs or the dashboard.

Cost model: each checked-in player pays a flat court fee plus a shuttle share.
The day's shuttle cost is split across games and, within each game, shared
equally among the players who played it.

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
    "CourtFee",
    "ShuttleShare",
    "AmountDue",
    "PaymentStatus",
]

# Flat court fee charged to every checked-in player (THB).
DEFAULT_COURT_FEE_PER_PERSON = 80.0

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
    ss.setdefault("shuttles_used", 0)
    ss.setdefault("court_fee_per_person", DEFAULT_COURT_FEE_PER_PERSON)
    ss.setdefault("shuttle_price", 70.0)  # typical THB price per shuttle
    ss.setdefault("attendance", {})        # {player_name: bool}
    ss.setdefault("games", [])             # list[list[str]] — players per game
    ss.setdefault("locked_split", None)    # cached DataFrame after locking


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

    # ---- Shuttle counter --------------------------------------------------
    st.subheader("🏸 Shuttles popped")
    c_minus, c_count, c_plus = st.columns([1, 1, 1])
    with c_minus:
        if st.button("➖", key="shuttle_minus", use_container_width=True):
            st.session_state.shuttles_used = max(0, st.session_state.shuttles_used - 1)
    with c_count:
        st.metric("Total", st.session_state.shuttles_used)
    with c_plus:
        if st.button("➕", key="shuttle_plus", use_container_width=True):
            st.session_state.shuttles_used += 1

    st.session_state.shuttle_price = st.number_input(
        "Shuttle unit price (THB)",
        min_value=0.0,
        value=float(st.session_state.shuttle_price),
        step=5.0,
    )

    st.divider()

    # ---- Per-game player selection ---------------------------------------
    st.subheader("🎮 Games")
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    if not present_names:
        st.caption("Check players in above, then add games and pick who played.")
    else:
        st.caption(
            "Add a game per round and select who played. Shuttle cost is split "
            "across the games each player joined."
        )
        gc_add, gc_clear = st.columns(2)
        with gc_add:
            if st.button("➕ Add game", use_container_width=True):
                st.session_state.games.append([])
        with gc_clear:
            if st.button("🗑️ Clear games", use_container_width=True):
                st.session_state.games = []

        for gi in range(len(st.session_state.games)):
            row = st.columns([5, 1])
            with row[0]:
                # Keep only still-present players as valid defaults.
                default = [p for p in st.session_state.games[gi] if p in present_names]
                st.session_state.games[gi] = st.multiselect(
                    f"เกม {gi + 1} (Game {gi + 1})",
                    options=present_names,
                    default=default,
                    key=f"game_{gi}",
                )
            with row[1]:
                st.write("")
                if st.button("✕", key=f"delgame_{gi}", help="Remove this game"):
                    st.session_state.games.pop(gi)
                    st.rerun()

    st.divider()

    # ---- Court fee --------------------------------------------------------
    st.subheader("🏟️ Court fee")
    st.session_state.court_fee_per_person = st.number_input(
        "Court fee per checked-in person (THB)",
        min_value=0.0,
        value=float(st.session_state.court_fee_per_person),
        step=10.0,
    )

    # ---- Running cost preview --------------------------------------------
    n_present = len(present_names)
    total_court = st.session_state.court_fee_per_person * n_present
    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price
    grand_total = total_court + total_shuttle_cost
    st.success(
        f"**Running total:** {grand_total:,.2f} THB  "
        f"(Court {st.session_state.court_fee_per_person:,.0f}×{n_present} = "
        f"{total_court:,.0f} + Shuttles {total_shuttle_cost:,.2f} across "
        f"{len(st.session_state.games)} game(s))"
    )


# =============================================================================
# VIEW 2 — End-of-Day Split
# =============================================================================
def compute_split(players: pd.DataFrame) -> pd.DataFrame:
    """Build the per-player split DataFrame for the active session date.

    Cost model:
      • Court fee: a flat per-person fee charged to every checked-in player.
      • Shuttles: total shuttle cost is split across games; within each game it
        is shared equally among that game's players. A player's shuttle share is
        the sum of their per-game shares. If no games are recorded, the shuttle
        cost is split equally among all checked-in players (fallback).
    """
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    count = len(present_names)
    if count == 0:
        return pd.DataFrame(columns=PAYMENTS_COLUMNS)

    court_fee = float(st.session_state.court_fee_per_person)
    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price

    # Per-player shuttle "units": each game contributes 1/(players in game) to
    # each of its players. Games with no players are ignored.
    games = [g for g in st.session_state.games if g]
    units = {name: 0.0 for name in present_names}
    games_played = {name: 0 for name in present_names}
    for g in games:
        valid = [p for p in g if p in units]
        if not valid:
            continue
        share = 1.0 / len(valid)
        for p in valid:
            units[p] += share
            games_played[p] += 1
    total_units = sum(units.values())  # equals number of non-empty games

    rows = []
    for name in present_names:
        if total_units > 0:
            shuttle_share = total_shuttle_cost * units[name] / total_units
        else:
            # No games recorded — fall back to an equal split.
            shuttle_share = total_shuttle_cost / count
        shuttle_share = round(shuttle_share, 2)
        rows.append(
            {
                "Date": str(st.session_state.session_date),
                "Player": name,
                "GamesPlayed": games_played[name],
                "CourtFee": round(court_fee, 2),
                "ShuttleShare": shuttle_share,
                "AmountDue": round(court_fee + shuttle_share, 2),
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
    n_games = len([g for g in st.session_state.games if g])
    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price
    total_court = st.session_state.court_fee_per_person * n_present

    m1, m2, m3 = st.columns(3)
    m1.metric("Court (per person)", f"{st.session_state.court_fee_per_person:,.0f}")
    m2.metric("Shuttles", f"{st.session_state.shuttles_used}")
    m3.metric("Games", f"{n_games}")

    st.caption(
        f"Each player pays **{st.session_state.court_fee_per_person:,.0f} court** "
        f"+ their shuttle share. Total shuttle cost "
        f"{total_shuttle_cost:,.2f} THB is split across {n_games} game(s) "
        f"(per-game, shared among who played). Day total: "
        f"**{total_court + total_shuttle_cost:,.2f} THB**."
        + ("" if n_games else "  _No games recorded — shuttles split equally._")
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
