"""
🏸 Badminton Team Tracker
=========================
A mobile-optimised Streamlit frontend for tracking on-court badminton sessions,
splitting costs, generating PromptPay QR codes, and reconciling bank-transfer
slips against players — all backed live by a Google Sheet.

Backend schema (Google Sheet)
-----------------------------
Worksheet "Players":
    | Name | PromptPayID |
    PromptPayID is a Thai mobile number (e.g. 0812345678) or a 13-digit
    national ID / tax ID used to receive PromptPay transfers.

Worksheet "Ledger":
    | Date | Player | Present | ShuttlesUsed | ShuttlePrice |
    | CourtFee | AmountDue | PaymentStatus |
    One row is written per checked-in player, per session date.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import io
import re
from typing import Optional

import pandas as pd
import streamlit as st

# --- Optional third-party imports are guarded so the app still boots and shows
# --- a friendly message if a dependency is missing in the deployment env. -----
try:
    from streamlit_gsheets import GSheetsConnection
except Exception:  # pragma: no cover - import guard
    GSheetsConnection = None  # type: ignore

try:
    from promptpay import qrcode as promptpay_qrcode
except Exception:  # pragma: no cover - import guard
    promptpay_qrcode = None  # type: ignore

try:
    import pytesseract
    from PIL import Image
except Exception:  # pragma: no cover - import guard
    pytesseract = None  # type: ignore
    Image = None  # type: ignore


# =============================================================================
# Configuration & constants
# =============================================================================
PLAYERS_WS = "Players"
LEDGER_WS = "Ledger"

LEDGER_COLUMNS = [
    "Date",
    "Player",
    "Present",
    "ShuttlesUsed",
    "ShuttlePrice",
    "CourtFee",
    "AmountDue",
    "PaymentStatus",
]

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
    """Read the registered player roster. Returns an empty frame on failure."""
    conn = get_connection()
    try:
        df = conn.read(worksheet=PLAYERS_WS, ttl=READ_TTL)
        df = df.dropna(how="all")
        # Normalise expected columns
        if "Name" not in df.columns:
            st.warning(
                f"Worksheet '{PLAYERS_WS}' is missing a 'Name' column. "
                "Expected columns: Name, PromptPayID."
            )
            return pd.DataFrame(columns=["Name", "PromptPayID"])
        if "PromptPayID" not in df.columns:
            df["PromptPayID"] = ""
        df["Name"] = df["Name"].astype(str).str.strip()
        df["PromptPayID"] = df["PromptPayID"].fillna("").astype(str).str.strip()
        return df[df["Name"] != ""].reset_index(drop=True)
    except Exception as exc:  # pragma: no cover - network/runtime guard
        st.error(f"Could not read the '{PLAYERS_WS}' worksheet: {exc}")
        return pd.DataFrame(columns=["Name", "PromptPayID"])


def write_players(df: pd.DataFrame) -> bool:
    """Overwrite the Players worksheet with `df`. Returns True on success."""
    conn = get_connection()
    try:
        clean = df.copy()
        # Keep only the canonical columns, in order.
        for col in ["Name", "PromptPayID"]:
            if col not in clean.columns:
                clean[col] = ""
        clean = clean[["Name", "PromptPayID"]]
        clean["Name"] = clean["Name"].astype(str).str.strip()
        clean["PromptPayID"] = clean["PromptPayID"].fillna("").astype(str).str.strip()
        clean = clean[clean["Name"] != ""].reset_index(drop=True)
        conn.update(worksheet=PLAYERS_WS, data=clean)
        return True
    except Exception as exc:  # pragma: no cover - network/runtime guard
        st.error(f"Failed to write to the '{PLAYERS_WS}' worksheet: {exc}")
        return False


def read_ledger() -> pd.DataFrame:
    """Read the full ledger. Returns an empty (typed) frame on failure."""
    conn = get_connection()
    try:
        df = conn.read(worksheet=LEDGER_WS, ttl=READ_TTL)
        df = df.dropna(how="all")
        # Guarantee all expected columns exist
        for col in LEDGER_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        return df[LEDGER_COLUMNS].reset_index(drop=True)
    except Exception:
        # Sheet may simply be empty / not created yet — that's fine.
        return pd.DataFrame(columns=LEDGER_COLUMNS)


def write_ledger(df: pd.DataFrame) -> bool:
    """Overwrite the Ledger worksheet with `df`. Returns True on success.

    `st-gsheets-connection`'s `update()` replaces the entire worksheet, so the
    caller is responsible for passing the *complete* desired ledger state.
    """
    conn = get_connection()
    try:
        clean = df[LEDGER_COLUMNS].copy()
        conn.update(worksheet=LEDGER_WS, data=clean)
        return True
    except Exception as exc:  # pragma: no cover - network/runtime guard
        st.error(f"Failed to write to the '{LEDGER_WS}' worksheet: {exc}")
        return False


def upsert_session_rows(session_rows: pd.DataFrame) -> bool:
    """Insert/replace all ledger rows for the session's date.

    Removes any pre-existing rows for the same Date (idempotent re-locking)
    and appends the freshly calculated rows, then pushes the whole ledger back.
    """
    if session_rows.empty:
        st.warning("No checked-in players to write.")
        return False

    session_date = str(session_rows["Date"].iloc[0])
    existing = read_ledger()
    # Drop prior rows for this date so re-running the split is idempotent.
    kept = existing[existing["Date"].astype(str) != session_date]
    combined = pd.concat([kept, session_rows], ignore_index=True)
    return write_ledger(combined)


# =============================================================================
# PromptPay QR generation
# =============================================================================
def generate_promptpay_qr(promptpay_id: str, amount: float) -> Optional[bytes]:
    """Return PNG bytes of a PromptPay QR encoding `amount` for `promptpay_id`.

    Uses the `promptpay` library to build the EMVCo payload, then renders it to
    a PNG. Returns None (and surfaces a message) if generation fails.
    """
    if promptpay_qrcode is None:
        st.error("`promptpay` library not installed — cannot generate QR codes.")
        return None
    if not promptpay_id:
        st.warning("No PromptPay ID on file for this player.")
        return None
    try:
        payload = promptpay_qrcode.generate_payload(
            str(promptpay_id), amount=round(float(amount), 2)
        )
        img = promptpay_qrcode.to_image(payload)  # PIL.Image
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # pragma: no cover - runtime guard
        st.error(f"QR generation failed for {promptpay_id}: {exc}")
        return None


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


def mark_player_paid(ledger: pd.DataFrame, idx) -> bool:
    """Flip a single ledger row to Paid and write the whole ledger back."""
    ledger.loc[idx, "PaymentStatus"] = STATUS_PAID
    return write_ledger(ledger)


# =============================================================================
# Session state initialisation
# =============================================================================
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("session_date", dt.date.today())
    ss.setdefault("shuttles_used", 0)
    ss.setdefault("court_fee", 0.0)
    ss.setdefault("shuttle_price", 70.0)  # typical THB price per shuttle
    ss.setdefault("attendance", {})        # {player_name: bool}
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
            "No players found. Add players (Name, PromptPayID) to the "
            f"'{PLAYERS_WS}' worksheet."
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

    # ---- Fixed court cost -------------------------------------------------
    st.subheader("🏟️ Court rental fee")
    st.session_state.court_fee = st.number_input(
        "Total court rental fee for the day (THB)",
        min_value=0.0,
        value=float(st.session_state.court_fee),
        step=10.0,
    )

    # ---- Running cost preview --------------------------------------------
    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price
    grand_total = total_shuttle_cost + st.session_state.court_fee
    st.success(
        f"**Running total:** {grand_total:,.2f} THB  "
        f"(Court {st.session_state.court_fee:,.2f} + "
        f"Shuttles {total_shuttle_cost:,.2f})"
    )


# =============================================================================
# VIEW 2 — End-of-Day Ledger & PromptPay QR
# =============================================================================
def compute_split(players: pd.DataFrame) -> pd.DataFrame:
    """Build the per-player split DataFrame for the active session date."""
    present_names = [n for n, v in st.session_state.attendance.items() if v]
    count = len(present_names)
    if count == 0:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price
    grand_total = total_shuttle_cost + st.session_state.court_fee
    individual_due = round(grand_total / count, 2)

    pp_map = dict(zip(players["Name"], players.get("PromptPayID", pd.Series(dtype=str))))

    rows = []
    for name in present_names:
        rows.append(
            {
                "Date": str(st.session_state.session_date),
                "Player": name,
                "Present": True,
                "ShuttlesUsed": st.session_state.shuttles_used,
                "ShuttlePrice": st.session_state.shuttle_price,
                "CourtFee": st.session_state.court_fee,
                "AmountDue": individual_due,
                "PaymentStatus": STATUS_PENDING,
            }
        )
    df = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    # Attach PromptPay IDs for QR rendering (not persisted to ledger).
    df["_PromptPayID"] = df["Player"].map(pp_map).fillna("")
    return df


def view_ledger(players: pd.DataFrame) -> None:
    st.header("🧾 End-of-Day Ledger")

    present_names = [n for n, v in st.session_state.attendance.items() if v]
    if not present_names:
        st.info("No players are checked in yet. Use the **Live Tracker** first.")
        return

    total_shuttle_cost = st.session_state.shuttles_used * st.session_state.shuttle_price
    grand_total = total_shuttle_cost + st.session_state.court_fee
    individual_due = round(grand_total / len(present_names), 2)

    m1, m2, m3 = st.columns(3)
    m1.metric("Court fee", f"{st.session_state.court_fee:,.0f}")
    m2.metric("Shuttles", f"{st.session_state.shuttles_used}")
    m3.metric("Per player", f"{individual_due:,.2f}")

    st.caption(
        f"Formula: (Court {st.session_state.court_fee:,.2f} + "
        f"{st.session_state.shuttles_used} × {st.session_state.shuttle_price:,.2f}) "
        f"÷ {len(present_names)} players = **{individual_due:,.2f} THB each**"
    )

    split_df = compute_split(players)

    st.subheader("Split summary")
    st.dataframe(
        split_df.drop(columns=["_PromptPayID"]),
        use_container_width=True,
        hide_index=True,
    )

    # ---- Lock & write back to the sheet ----------------------------------
    if st.button("🔒 Lock totals & write to Google Sheet", type="primary"):
        with st.spinner("Writing ledger to Google Sheet…"):
            persist_df = split_df.drop(columns=["_PromptPayID"])
            if upsert_session_rows(persist_df):
                st.session_state.locked_split = split_df
                st.success("Ledger saved. ✅")
                st.balloons()

    st.divider()

    # ---- PromptPay QR per player -----------------------------------------
    st.subheader("📱 PromptPay QR codes")
    st.caption("Each player scans their own QR to pay the exact amount.")
    for _, row in split_df.iterrows():
        with st.container(border=True):
            top = st.columns([2, 1])
            top[0].markdown(f"**{row['Player']}**")
            top[1].markdown(f"**{row['AmountDue']:,.2f} THB**")
            if st.button(f"Show QR — {row['Player']}", key=f"qr_{row['Player']}"):
                png = generate_promptpay_qr(row["_PromptPayID"], row["AmountDue"])
                if png:
                    st.image(
                        png,
                        caption=f"{row['Player']} · {row['AmountDue']:,.2f} THB "
                        f"· {row['_PromptPayID']}",
                        width=260,
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

    ledger = read_ledger()

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
# VIEW 4 — Roster Manager
# =============================================================================
def view_roster(players: pd.DataFrame) -> None:
    st.header("👥 Roster Manager")
    st.caption(
        "Add, rename or remove players and edit their PromptPay IDs, then save "
        f"back to the '{PLAYERS_WS}' worksheet."
    )

    base = players.copy()
    if base.empty:
        base = pd.DataFrame(columns=["Name", "PromptPayID"])

    edited = st.data_editor(
        base[["Name", "PromptPayID"]],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", required=True),
            "PromptPayID": st.column_config.TextColumn(
                "PromptPay ID",
                help="Thai mobile number (0812345678) or 13-digit national/tax ID",
            ),
        },
        key="roster_editor",
    )

    # Basic validation feedback before the user commits.
    names = edited["Name"].astype(str).str.strip()
    dupes = names[names.duplicated() & (names != "")].unique().tolist()
    if dupes:
        st.warning(f"Duplicate player names will be merged on save: {', '.join(dupes)}")

    if st.button("💾 Save roster to Google Sheet", type="primary"):
        with st.spinner("Saving roster…"):
            # Drop duplicate names (keep first) to keep attendance keys unique.
            to_save = edited.copy()
            to_save["Name"] = to_save["Name"].astype(str).str.strip()
            to_save = to_save[to_save["Name"] != ""].drop_duplicates(
                subset=["Name"], keep="first"
            )
            if write_players(to_save):
                st.success(f"Saved {len(to_save)} players. ✅")
                st.rerun()


# =============================================================================
# VIEW 5 — Season History
# =============================================================================
def view_history() -> None:
    st.header("📊 Season History")
    ledger = read_ledger()
    if ledger.empty:
        st.info("No sessions recorded yet. Lock a ledger to start building history.")
        return

    led = ledger.copy()
    led["AmountDue"] = pd.to_numeric(led["AmountDue"], errors="coerce").fillna(0.0)
    led["ShuttlesUsed"] = pd.to_numeric(led["ShuttlesUsed"], errors="coerce").fillna(0)
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
            Shuttles=("ShuttlesUsed", "max"),
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
            "🧾 Ledger & QR",
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

    st.caption("Backed live by Google Sheets · PromptPay · OCR slip reading")


if __name__ == "__main__":
    main()
