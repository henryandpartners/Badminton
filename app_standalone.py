"""
🏸 Badminton Tracker — Standalone (No Google Sheets)

A fully self-contained version that stores everything in a local SQLite DB.
No Google Sheets API needed. All data is in .badminton.db.

Run with:  streamlit run app_standalone.py
"""
from __future__ import annotations

import datetime as dt
import io
import pandas as pd
import streamlit as st
import summary_db as sdb

# ── Roster ────────────────────────────────────────────────────────────
BASE_ROSTER = [
    "โรจน์", "น้อย", "ภูมี", "ป๊อป ภู", "คะน้า", "จืด",
    "เกียรติ", "อองรี", "ป๊อป", "น้อต", "ต้น", "ทรัมป",
]

COURTS = ["9", "10"]
COURT_HOUR_OPTIONS = [0, 1, 2, 3]
DEFAULT_SHUTTLE_PRICE = 100.0
STATUS_PENDING = "Pending"
STATUS_PAID = "Paid"

thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]


# =============================================================================
# Session state helpers
# =============================================================================
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("session_date", dt.date.today())
    ss.setdefault("shuttle_price", DEFAULT_SHUTTLE_PRICE)
    ss.setdefault("court_hours", {c: 0 for c in COURTS})
    ss.setdefault("attendance", {})
    ss.setdefault("extra_players", [])
    ss.setdefault("games", [])
    ss.setdefault("split_paid", {})


def get_roster() -> list[str]:
    """Return base roster + any extra players added today."""
    ss = st.session_state
    return BASE_ROSTER + [p for p in ss.get("extra_players", []) if p not in BASE_ROSTER]


# =============================================================================
# VIEW 1 — Live Tracker
# =============================================================================
def view_live_tracker() -> None:
    st.header("🏟️ Live Tracker")

    session_date = st.date_input(
        "Session date", value=st.session_state.session_date,
        key="live_date",
    )
    if session_date != st.session_state.session_date:
        st.session_state.session_date = session_date
        st.session_state.attendance = {}
        st.rerun()
    st.session_state.session_date = session_date

    st.subheader("✅ Attendance")
    roster = get_roster()

    cols = st.columns(2)
    for i, name in enumerate(roster):
        with cols[i % 2]:
            st.session_state.attendance[name] = st.toggle(
                name,
                value=st.session_state.attendance.get(name, False),
                key=f"att_{name}",
            )

    present_count = sum(1 for v in st.session_state.attendance.values() if v)
    st.metric("Players present", present_count)

    # Add extra player
    new_player = st.text_input("➕ Add player for today", placeholder="Enter name...")
    if new_player and st.button("Add player"):
        new_player = new_player.strip()
        if new_player and new_player not in get_roster():
            st.session_state.extra_players.append(new_player)
            st.session_state.attendance[new_player] = True
            st.rerun()
        elif new_player:
            st.warning(f"{new_player} is already in the roster.")

    st.divider()

    # ── Court hours ────────────────────────────────────────────
    st.subheader("🏟️ Court hours (80 THB/player)")
    st.caption("Court fee is a flat 80 THB per checked-in player.")
    for c in COURTS:
        st.session_state.court_hours[c] = st.radio(
            f"Court {c} — hours",
            options=COURT_HOUR_OPTIONS,
            index=COURT_HOUR_OPTIONS.index(st.session_state.court_hours.get(c, 0)),
            horizontal=True,
            key=f"court_{c}",
        )
    present_count = sum(1 for v in st.session_state.attendance.values() if v)
    st.caption(f"Court cost: {present_count} × 80 = **{present_count * 80:,} THB**")

    st.divider()

    # ── Games ──────────────────────────────────────────────────
    st.subheader("🎮 Games")
    shuttle_price = st.number_input(
        "Shuttle price (THB each)",
        min_value=0.0, value=float(st.session_state.shuttle_price), step=10.0,
        key="shuttle_price_input",
    )
    st.session_state.shuttle_price = shuttle_price

    present_names = [n for n, v in st.session_state.attendance.items() if v]

    # Show existing games with edit/delete
    if st.session_state.games:
        st.markdown(f"**{len(st.session_state.games)} game(s):**")
        for gi, g in enumerate(st.session_state.games):
            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                players_str = ", ".join(g["players"])
                fee = g["shuttles"] * shuttle_price / max(len(g["players"]), 1)
                cols[0].markdown(
                    f"**Game {gi + 1}** · {g['shuttles']} shuttle(s) · "
                    f"{players_str} — _{fee:.0f} THB/player_"
                )

                # Edit button
                if cols[1].button("✏️ Edit", key=f"edit_g_{gi}"):
                    st.session_state[f"_edit_game_{gi}"] = True

                # Delete button
                if cols[2].button("🗑️", key=f"del_g_{gi}"):
                    st.session_state.games.pop(gi)
                    st.rerun()

                # Edit form (inline, shown when edit is clicked)
                if st.session_state.get(f"_edit_game_{gi}", False):
                    edit_players = st.multiselect(
                        "Players in this game",
                        options=present_names,
                        default=g["players"],
                        key=f"edit_players_{gi}",
                    )
                    edit_shuttles = st.number_input(
                        "Shuttles", min_value=0, max_value=20,
                        value=g["shuttles"], step=1,
                        key=f"edit_shuttles_{gi}",
                    )
                    col_save, col_cancel = st.columns(2)
                    if col_save.button("💾 Save", key=f"save_g_{gi}"):
                        st.session_state.games[gi] = {
                            "players": list(edit_players),
                            "shuttles": edit_shuttles,
                        }
                        st.session_state[f"_edit_game_{gi}"] = False
                        st.rerun()
                    if col_cancel.button("Cancel", key=f"cancel_g_{gi}"):
                        st.session_state[f"_edit_game_{gi}"] = False
                        st.rerun()
    else:
        st.info("No games yet. Add the first game below!")

    # Running total preview
    if st.session_state.games:
        total_shuttle_cost = sum(g["shuttles"] for g in st.session_state.games) * shuttle_price
        court_cost = present_count * 80
        st.caption(
            f"Running: 🏸 {total_shuttle_cost:.0f} THB shuttles + "
            f"🏟️ {court_cost:.0f} THB court = **{total_shuttle_cost + court_cost:.0f} THB**"
        )

    st.divider()

    # ── Add new game ───────────────────────────────────────────
    st.subheader("➕ Add Game")
    if not present_names:
        st.caption("Check players in above first.")
    else:
        next_game = len(st.session_state.games) + 1
        st.markdown(f"**Game {next_game}** — who played?")
        selected_players = st.multiselect(
            "Select players", options=present_names,
            key="add_game_players",
        )
        shuttle_count = st.number_input(
            "Shuttles used", min_value=0, max_value=20, value=1, step=1,
            key="add_game_shuttles",
        )
        if st.button("🎯 Add game", type="primary", use_container_width=True):
            if not selected_players:
                st.warning("Select at least one player!")
            else:
                st.session_state.games.append({
                    "players": list(selected_players),
                    "shuttles": shuttle_count,
                })
                st.rerun()

    st.divider()

    # ── Submit day ─────────────────────────────────────────────
    st.subheader("📤 Submit Day")
    n_present = len(present_names)
    total_shuttle = sum(g["shuttles"] for g in st.session_state.games) * shuttle_price
    court_cost = n_present * 80
    grand_total = court_cost + total_shuttle

    m1, m2, m3 = st.columns(3)
    m1.metric("Players", n_present)
    m2.metric("Court", f"{court_cost:,.0f} THB")
    m3.metric("Shuttles", f"{total_shuttle:,.0f} THB")

    if st.button("📥 Submit day", type="primary", use_container_width=True):
        with st.spinner("Saving to local database…"):
            day_name = thai_days[st.session_state.session_date.weekday()]
            # Build player_types
            player_types = {n: "ประจำ" if n in BASE_ROSTER[:3] else "ขาจร" for n in get_roster()}

            # Game analysis
            player_game_count = {}
            player_shuttle_cost = {}
            for g in st.session_state.games:
                for p in g["players"]:
                    player_game_count[p] = player_game_count.get(p, 0) + 1
                    per = g["shuttles"] * shuttle_price / max(len(g["players"]), 1)
                    player_shuttle_cost[p] = player_shuttle_cost.get(p, 0) + per

            ok = sdb.save_session(
                session_date=st.session_state.session_date,
                day_name=day_name,
                court_hours=st.session_state.court_hours,
                attendance=st.session_state.attendance,
                player_types=player_types,
                recorded_games=st.session_state.games,
                shuttle_price=shuttle_price,
                player_game_count=player_game_count,
                player_shuttle_cost=player_shuttle_cost,
            )
            if ok:
                st.success(f"✅ Day saved to local database!")
                st.balloons()
                # Clear session games so they're ready for next time
                st.session_state.games = []
                st.session_state.attendance = {}
                st.session_state.extra_players = []
                st.session_state.split_paid = {}
                st.rerun()


# =============================================================================
# VIEW 2 — Split
# =============================================================================
def view_split() -> None:
    st.header("🧾 Split & Payments")

    present_names = [n for n, v in st.session_state.attendance.items() if v]

    # Also allow viewing past sessions
    past_sessions = sdb.get_session_summaries()
    selected_date = st.selectbox(
        "Session date",
        options=[str(st.session_state.session_date)] + [s["date"] for s in past_sessions],
        index=0,
    )

    if selected_date == str(st.session_state.session_date):
        # ── Current session (from session state) ──
        if not present_names:
            st.info("No players checked in. Go to Live Tracker first.")
            return

        n_present = len(present_names)
        total_court_cost = n_present * 80.0
        shuttle_price = float(st.session_state.shuttle_price)
        total_shuttle_cost = sum(g["shuttles"] for g in st.session_state.games) * shuttle_price

        # Per-player calculation
        player_data = {}
        for name in present_names:
            player_data[name] = {"games": 0, "shuttle_cost": 0.0, "court_fee": 80.0}

        for g in st.session_state.games:
            per = g["shuttles"] * shuttle_price / max(len(g["players"]), 1)
            for p in g.get("players", []):
                if p in player_data:
                    player_data[p]["games"] += 1
                    player_data[p]["shuttle_cost"] += per

        for p in player_data.values():
            p["total"] = p["court_fee"] + p["shuttle_cost"]

        grand_total = sum(p["total"] for p in player_data.values())

        # ── Summary metrics ──
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Players", n_present)
        m2.metric("Court", f"{total_court_cost:,.0f}")
        m3.metric("Shuttles", f"{total_shuttle_cost:,.0f}")
        m4.metric("Total", f"{grand_total:,.0f}")

        # ── Player breakdown with Paid checkbox ──
        st.subheader("Per player")
        for name in present_names:
            d = player_data[name]
            with st.container(border=True):
                cols = st.columns([2, 1, 1, 1, 1])
                cols[0].markdown(f"**{name}**")
                cols[1].markdown(f"🏸 {d['shuttle_cost']:.0f}")
                cols[2].markdown(f"🏟️ {d['court_fee']:.0f}")
                cols[3].markdown(f"💰 {d['total']:.0f}")
                paid_key = f"paid_{name}_{selected_date}"
                is_paid = st.session_state.split_paid.get(paid_key, False)
                if cols[4].checkbox("Paid", value=is_paid, key=paid_key):
                    st.session_state.split_paid[paid_key] = True
                else:
                    st.session_state.split_paid[paid_key] = False

        # Payment summary
        paid_count = sum(1 for k, v in st.session_state.split_paid.items() if v and any(n in k for n in present_names))
        st.caption(f"**{paid_count}/{n_present}** players marked as paid")

    else:
        # ── Past session (from SQLite) ──
        db_sess = sdb.get_session(selected_date)
        if not db_sess:
            st.info("Session not found in database.")
            return

        players = sdb.get_session_players(db_sess["id"])
        attended = [p for p in players if p["attended"]]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Players", db_sess["player_count"])
        m2.metric("Court", f"{db_sess['total_court_fees']:,.0f}")
        m3.metric("Shuttles", f"{db_sess['total_shuttle_cost']:,.0f}")
        m4.metric("Total", f"{db_sess['total_amount']:,.0f}")

        st.subheader("Per player")
        for p in attended:
            with st.container(border=True):
                cols = st.columns([2, 1, 1, 1, 1])
                cols[0].markdown(f"**{p['player_name']}**")
                cols[1].markdown(f"🏸 {p['shuttle_cost']:.0f}")
                cols[2].markdown(f"🏟️ {p['court_fee']:.0f}")
                cols[3].markdown(f"💰 {p['total']:.0f}")

                paid_key = f"paid_{p['player_name']}_{selected_date}"
                is_paid = st.session_state.split_paid.get(paid_key, p["payment_status"] == STATUS_PAID)
                paid = cols[4].checkbox("Paid", value=is_paid, key=paid_key)
                st.session_state.split_paid[paid_key] = paid

                # Save to DB when toggled
                if paid != (p["payment_status"] == STATUS_PAID):
                    sdb.update_payment_status(
                        db_sess["id"], p["player_name"],
                        STATUS_PAID if paid else STATUS_PENDING,
                    )
                    st.rerun()

        # Games
        games = sdb.get_session_games(db_sess["id"])
        if games:
            st.subheader("🏸 Games")
            for g in games:
                st.markdown(f"Game {g['game_number']}: {g['players']} — {g['shuttles']} shuttle(s)")


# =============================================================================
# VIEW 3 — History (same as before, uses SQLite)
# =============================================================================
def view_history() -> None:
    st.header("📊 Season History")

    if sdb.is_empty():
        st.info("No sessions recorded yet. Use the Live Tracker to submit a session.")
        return

    stats = sdb.get_stats()

    m1, m2, m3 = st.columns(3)
    m1.metric("Sessions", stats["total_sessions"])
    m2.metric("Collected", f"{stats['total_collected']:,.0f} THB")
    m3.metric("Check-ins", stats["total_checkins"])

    st.subheader("📋 Per-session details")
    sessions = sdb.get_session_summaries()
    for sess in sessions:
        label = (
            f"{sess['date']} ({sess['day_name']}) — "
            f"{sess['player_count']} players · {sess['game_count']} games · "
            f"{sess['total_amount']:,.0f} THB"
        )
        with st.expander(label):
            db_sess = sdb.get_session(sess["date"])
            if db_sess:
                players = sdb.get_session_players(db_sess["id"])
                games = sdb.get_session_games(db_sess["id"])

                if players:
                    cols = st.columns(4)
                    cols[0].metric("🏸 Shuttles", f"{db_sess['total_shuttle_cost']:,.0f} THB")
                    cols[1].metric("🏟️ Court", f"{db_sess['total_court_fees']:,.0f} THB")
                    cols[2].metric("💰 Total", f"{db_sess['total_amount']:,.0f} THB")
                    cols[3].metric("👤 Players", db_sess["player_count"])

                    st.dataframe(
                        [
                            {
                                "Player": p["player_name"],
                                "Type": p["player_type"],
                                "Games": p["games_played"],
                                "Shuttle": f"{p['shuttle_cost']:.0f}",
                                "Court": f"{p['court_fee']:.0f}",
                                "Total": f"{p['total']:.0f}",
                                "Status": p["payment_status"],
                            }
                            for p in players if p["attended"]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                if games:
                    st.caption(f"🏸 **{len(games)} games**")
                    for g in games:
                        st.markdown(
                            f"Game {g['game_number']}: {g['players']} — {g['shuttles']} shuttle(s)"
                        )

    st.subheader("👥 Per-player totals")
    player_summary = sdb.get_player_summary()
    if player_summary:
        st.dataframe(
            [
                {
                    "Player": p["player_name"],
                    "Type": p["player_type"],
                    "Sessions": p["sessions"],
                    "Games": p["total_games"],
                    "Shuttle Cost": f"{p['total_shuttle']:,.0f}",
                    "Court Fee": f"{p['total_court']:,.0f}",
                    "Total Due": f"{p['total_due']:,.0f}",
                }
                for p in player_summary
            ],
            use_container_width=True,
            hide_index=True,
        )

        chart_data = {p["player_name"]: p["total_due"] for p in player_summary if p["total_due"] > 0}
        if chart_data:
            st.subheader("Who owes (total)")
            st.bar_chart(chart_data)


# =============================================================================
# VIEW 4 — Export
# =============================================================================
def view_export() -> None:
    st.header("📤 Export Data")

    if sdb.is_empty():
        st.info("No data to export yet.")
        return

    # ── Export all sessions ──
    st.subheader("All sessions")
    sessions = sdb.get_session_summaries()
    if sessions:
        df_sessions = pd.DataFrame(sessions)
        df_sessions.columns = [
            "Date", "Day", "Players", "Shuttle Cost", "Court Fees",
            "Total Amount", "Games",
        ]
        csv_all = df_sessions.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 Download all sessions (CSV)",
            data=csv_all,
            file_name=f"badminton_sessions_{dt.date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ── Export per-player summary ──
    st.subheader("Per-player summary")
    player_summary = sdb.get_player_summary()
    if player_summary:
        df_players = pd.DataFrame(player_summary)
        df_players.columns = [
            "Player", "Type", "Sessions", "Total Games",
            "Shuttle Cost", "Court Fee", "Total Due",
        ]
        csv_players = df_players.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 Download per-player summary (CSV)",
            data=csv_players,
            file_name=f"badminton_players_{dt.date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ── Export full detail ──
    st.subheader("Full detail (all players, all sessions)")
    all_sessions = sdb.get_sessions()
    all_rows = []
    for sess in all_sessions:
        players = sdb.get_session_players(sess["id"])
        for p in players:
            if p["attended"]:
                all_rows.append({
                    "Date": sess["date"],
                    "Day": sess["day_name"],
                    "Player": p["player_name"],
                    "Type": p["player_type"],
                    "Games Played": p["games_played"],
                    "Shuttle Cost": p["shuttle_cost"],
                    "Court Fee": p["court_fee"],
                    "Total": p["total"],
                    "Payment Status": p["payment_status"],
                })
    if all_rows:
        df_detail = pd.DataFrame(all_rows)
        csv_detail = df_detail.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 Download full detail (CSV)",
            data=csv_detail,
            file_name=f"badminton_detail_{dt.date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # Database info
    st.divider()
    stats = sdb.get_stats()
    st.caption(
        f"Local database: **{stats['total_sessions']} sessions**, "
        f"**{stats['total_checkins']} check-ins**, "
        f"**{stats['total_collected']:,.0f} THB** total"
    )


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    st.set_page_config(
        page_title="🏸 Badminton Tracker",
        page_icon="🏸",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    sdb.init_db()
    init_state()

    st.title("🏸 Badminton Tracker")
    st.caption("Standalone — no Google Sheets needed")

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏟️ Live Tracker",
        "🧾 Split",
        "📊 History",
        "📤 Export",
    ])

    with tab1:
        view_live_tracker()
    with tab2:
        view_split()
    with tab3:
        view_history()
    with tab4:
        view_export()

    st.caption("Powered by local SQLite database · Data never leaves your machine")


if __name__ == "__main__":
    main()
