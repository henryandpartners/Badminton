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
    import requests
except Exception:  # pragma: no cover - import guard
    requests = None  # type: ignore

try:
    from promptpay import qrcode as promptpay_qrcode
except Exception:  # pragma: no cover - import guard
    promptpay_qrcode = None  # type: ignore


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
    return st.connection("gsheets", type=GSheetsConnection)


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
# Slip Matching Engine (SlipOk verification API)
# =============================================================================
def verify_slip_with_slipok(image_bytes: bytes, filename: str) -> dict:
    """POST a transfer-slip image to the SlipOk API and return a normalised dict.

    Returns a dict shaped like:
        {
            "success": bool,
            "amount": float | None,
            "sender": str | None,
            "raw": <full json payload or error text>,
            "error": str | None,
        }

    Credentials are read from st.secrets["slipok"]:
        endpoint  -> full SlipOk branch endpoint URL
        api_key   -> the x-authorization API key
    """
    result = {"success": False, "amount": None, "sender": None, "raw": None, "error": None}

    if requests is None:
        result["error"] = "`requests` library not installed."
        return result

    slip_cfg = st.secrets.get("slipok", {})
    endpoint = slip_cfg.get("endpoint")
    api_key = slip_cfg.get("api_key")
    if not endpoint or not api_key:
        result["error"] = (
            "SlipOk credentials missing. Set [slipok] endpoint and api_key "
            "in .streamlit/secrets.toml."
        )
        return result

    try:
        files = {"files": (filename, image_bytes)}
        headers = {"x-authorization": api_key}
        # `log=true` tells SlipOk to store the verification for audit.
        resp = requests.post(
            endpoint,
            headers=headers,
            files=files,
            data={"log": "true"},
            timeout=30,
        )
        payload = {}
        try:
            payload = resp.json()
        except ValueError:
            result["error"] = f"Non-JSON response (HTTP {resp.status_code})."
            result["raw"] = resp.text
            return result

        result["raw"] = payload

        # SlipOk wraps the transaction details in `data`; `success` is top-level.
        is_success = bool(payload.get("success", False))
        data = payload.get("data", {}) or {}

        # Different SlipOk plans expose sender under slightly different keys.
        sender = (
            data.get("sender", {}).get("displayName")
            if isinstance(data.get("sender"), dict)
            else data.get("sender")
        ) or data.get("senderName") or data.get("sendingBank")

        amount = data.get("amount")

        if not is_success:
            result["error"] = payload.get("message") or "Slip verification rejected."
            return result

        result["success"] = True
        result["amount"] = float(amount) if amount is not None else None
        result["sender"] = str(sender) if sender is not None else None
        return result
    except requests.exceptions.RequestException as exc:  # type: ignore[attr-defined]
        result["error"] = f"Network error calling SlipOk: {exc}"
        return result
    except Exception as exc:  # pragma: no cover - runtime guard
        result["error"] = f"Unexpected error: {exc}"
        return result


def match_slip_to_player(ledger: pd.DataFrame, amount: float, tol: float = 0.5):
    """Find the pending ledger row whose AmountDue matches `amount`.

    Returns (index, row) of the best match, or (None, None) if no pending player
    owes that amount within tolerance `tol` Baht.
    """
    if ledger.empty or amount is None:
        return None, None
    pending = ledger[ledger["PaymentStatus"].astype(str).str.lower() == STATUS_PENDING.lower()]
    if pending.empty:
        return None, None
    due = pd.to_numeric(pending["AmountDue"], errors="coerce")
    diffs = (due - float(amount)).abs()
    if diffs.empty or diffs.min() > tol:
        return None, None
    idx = diffs.idxmin()
    return idx, ledger.loc[idx]


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
def view_slip_verification() -> None:
    st.header("📥 Slip Verification")
    st.caption(
        "Drop a bank-transfer slip. We verify it with SlipOk, match the amount "
        "to a pending player, and mark them **Paid**."
    )

    uploaded = st.file_uploader(
        "Upload transfer slip (JPG / PNG)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=False,
    )

    if uploaded is None:
        # Show the current outstanding list so the user has context.
        ledger = read_ledger()
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
        return

    st.image(uploaded, caption="Uploaded slip", width=220)

    if st.button("🔍 Verify & reconcile", type="primary"):
        image_bytes = uploaded.getvalue()
        with st.spinner("Verifying slip with SlipOk…"):
            verdict = verify_slip_with_slipok(image_bytes, uploaded.name)

        if not verdict["success"]:
            st.error(f"Slip not verified: {verdict.get('error')}")
            with st.expander("Raw response"):
                st.write(verdict.get("raw"))
            return

        amount = verdict["amount"]
        sender = verdict["sender"]
        st.info(
            f"Verified transfer of **{amount:,.2f} THB**"
            + (f" from **{sender}**." if sender else ".")
        )

        ledger = read_ledger()
        idx, match = match_slip_to_player(ledger, amount)
        if idx is None:
            st.warning(
                f"No pending player owes {amount:,.2f} THB. "
                "Reconcile manually or check the ledger."
            )
            return

        # ---- Update that player's row to Paid and write back ------------
        ledger.loc[idx, "PaymentStatus"] = STATUS_PAID
        with st.spinner("Updating Google Sheet…"):
            if write_ledger(ledger):
                st.success(
                    f"✅ Matched **{amount:,.2f} THB** to "
                    f"**{match['Player']}** — marked as Paid!"
                )
                st.balloons()


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    inject_mobile_css()
    init_state()

    st.title("🏸 Badminton Team Tracker")

    players = read_players()

    tab1, tab2, tab3 = st.tabs(
        ["🏟️ Live Tracker", "🧾 Ledger & QR", "📥 Slip Verify"]
    )
    with tab1:
        view_live_tracker(players)
    with tab2:
        view_ledger(players)
    with tab3:
        view_slip_verification()

    st.caption("Backed live by Google Sheets · PromptPay · SlipOk")


if __name__ == "__main__":
    main()
