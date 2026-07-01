"""
🏸 Badminton Tracker
====================
A mobile-friendly Streamlit app backed by a database (SQLite locally, or
Supabase/Postgres in the cloud — see db.py). Tracks daily check-ins, per-game
players & shuttles, court hours, payments, monthly summaries, and exports.

Run:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="🏸 Badminton Tracker", page_icon="🏸", layout="centered")


# --- one-time DB init --------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _bootstrap():
    db.init_db()
    return True


_bootstrap()


def inject_css():
    st.markdown(
        """
        <style>
        .stButton > button { width:100%; min-height:3rem; font-size:1.1rem;
            font-weight:700; border-radius:12px; }
        .block-container { padding-top:1.2rem; padding-bottom:4rem; }
        div[data-testid="stMetricValue"] { font-size:1.9rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- helpers -----------------------------------------------------------------
def player_maps(active_only=True):
    ps = db.get_players(active_only=active_only)
    id_to_name = dict(zip(ps["id"], ps["name"]))
    name_to_id = dict(zip(ps["name"], ps["id"]))
    return ps, id_to_name, name_to_id


# --- callbacks (write immediately to DB) -------------------------------------
def _cb_checkin(sid, pid, key):
    if st.session_state[key]:
        db.check_in(sid, pid)
    else:
        db.check_out(sid, pid)


def _cb_paid(sid, pid, key):
    db.set_paid(sid, pid, st.session_state[key])


def _cb_court(sid, field, key):
    db.update_session(sid, **{field: int(st.session_state[key])})


# =============================================================================
# PAGE 1 — Session (check-in + games)
# =============================================================================
def page_session():
    st.header("📋 Session")
    session_date = st.date_input("Session date", value=st.session_state.get("session_date", dt.date.today()))
    st.session_state.session_date = session_date
    sid = db.get_or_create_session(session_date)
    sess = db.get_session(sid)

    # ---- Courts & hours ----
    st.subheader("🏟️ Courts & hours")
    st.caption(f"{sess['court_rate']:,.0f} THB per court per hour (venue cost).")
    cc = st.columns(len(db.COURTS))
    fields = {"9": "court9_hours", "10": "court10_hours"}
    for i, c in enumerate(db.COURTS):
        with cc[i]:
            key = f"court_{sid}_{c}"
            st.radio(
                f"Court {c} (hrs)", options=[0, 1, 2, 3],
                index=[0, 1, 2, 3].index(int(sess[fields[c]])),
                key=key, horizontal=True,
                on_change=_cb_court, args=(sid, fields[c], key),
            )
    total_hours = sess["court9_hours"] + sess["court10_hours"]
    st.caption(f"Total: **{total_hours} court-hour(s)** → cost {total_hours * sess['court_rate']:,.0f} THB")

    st.divider()

    # ---- Check-in ----
    st.subheader("✅ Check-in")
    ps, id_to_name, name_to_id = player_maps(active_only=True)
    att = db.get_attendance(sid)
    checked_ids = set(int(x) for x in att["player_id"]) if not att.empty else set()

    cols = st.columns(2)
    for i, (_, p) in enumerate(ps.iterrows()):
        pid = int(p["id"])
        with cols[i % 2]:
            key = f"ci_{sid}_{pid}"
            label = p["name"] + (" 👤" if p["is_guest"] else "")
            st.toggle(label, value=pid in checked_ids, key=key,
                      on_change=_cb_checkin, args=(sid, pid, key))
    st.metric("Checked in", len(checked_ids))

    with st.expander("➕ Add a player who joined today"):
        with st.form("add_player", clear_on_submit=True):
            new_name = st.text_input("Player name")
            is_guest = st.checkbox("Guest (one-off)", value=True)
            if st.form_submit_button("Add & check in"):
                if new_name.strip():
                    npid = db.add_player(new_name, is_guest=is_guest)
                    db.check_in(sid, npid)
                    st.success(f"Added {new_name}.")
                    st.rerun()

    st.divider()

    # ---- Games ----
    st.subheader("🎮 Games")
    att = db.get_attendance(sid)
    present = list(att["name"]) if not att.empty else []
    if not present:
        st.info("Check players in first, then add games.")
    else:
        with st.form("add_game", clear_on_submit=True):
            st.markdown("**Add a game** (usually 4 players)")
            pick = st.multiselect("Players in this game", options=present, key="newgame_players")
            sh = st.number_input("Shuttles used", min_value=0, value=1, step=1, key="newgame_shuttles")
            if st.form_submit_button("➕ Add game"):
                if pick:
                    db.add_game(sid, [int(name_to_id[n]) for n in pick], int(sh))
                    st.rerun()
                else:
                    st.warning("Pick at least one player.")

        for g in db.get_games(sid):
            with st.container(border=True):
                st.markdown(f"**Game {g['game_no']}**")
                cur_names = [id_to_name.get(pid) for pid in g["player_ids"] if pid in id_to_name]
                pick = st.multiselect(
                    "Players", options=present, default=[n for n in cur_names if n in present],
                    key=f"g_players_{g['id']}",
                )
                row = st.columns([2, 1, 1])
                with row[0]:
                    shv = st.number_input("Shuttles", min_value=0, value=int(g["shuttles"]),
                                          step=1, key=f"g_sh_{g['id']}")
                with row[1]:
                    st.write("")
                    if st.button("💾 Save", key=f"g_save_{g['id']}"):
                        db.update_game(g["id"], [int(name_to_id[n]) for n in pick], int(shv))
                        st.toast(f"Game {g['game_no']} updated")
                        st.rerun()
                with row[2]:
                    st.write("")
                    if st.button("🗑️", key=f"g_del_{g['id']}"):
                        db.delete_game(g["id"])
                        st.rerun()


# =============================================================================
# PAGE 2 — Daily summary
# =============================================================================
def page_daily():
    st.header("💰 Daily Summary")
    session_date = st.date_input("Date", value=st.session_state.get("session_date", dt.date.today()), key="daily_date")
    sid = db.get_or_create_session(session_date)
    df = db.compute_daily_split(sid)
    if df.empty:
        st.info("No check-ins for this date yet.")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Players", len(df))
    m2.metric("Total due", f"{df['Total'].sum():,.0f}")
    m3.metric("Collected", f"{df.loc[df['Paid'], 'Total'].sum():,.0f}")

    st.caption("Tick **Paid** as people pay.")
    _, id_to_name, name_to_id = player_maps(active_only=False)
    for _, r in df.iterrows():
        pid = int(name_to_id[r["Player"]])
        with st.container(border=True):
            c = st.columns([3, 2, 2])
            c[0].markdown(f"**{r['Player']}**  \n{int(r['GamesPlayed'])} games")
            c[1].markdown(f"Court {r['CourtFee']:,.0f}  \nShuttle {r['ShuttleCost']:,.0f}")
            with c[2]:
                st.markdown(f"**{r['Total']:,.0f} THB**")
                key = f"paid_{sid}_{pid}"
                st.checkbox("Paid", value=bool(r["Paid"]), key=key,
                            on_change=_cb_paid, args=(sid, pid, key))

    st.download_button(
        "⬇️ Export this day (CSV)",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"daily_{session_date}.csv", mime="text/csv",
    )


# =============================================================================
# PAGE 3 — Monthly summary
# =============================================================================
def page_monthly():
    st.header("📅 Monthly Summary")
    today = dt.date.today()
    c1, c2 = st.columns(2)
    year = c1.number_input("Year", min_value=2024, max_value=2100, value=today.year)
    month = c2.number_input("Month", min_value=1, max_value=12, value=today.month)
    s = db.monthly_summary(int(year), int(month))

    a, b, c = st.columns(3)
    a.metric("Sessions", s["sessions"])
    b.metric("Court-hours", s["total_court_hours"])
    c.metric("Attendances", s["attendances"])
    a2, b2, c2b = st.columns(3)
    a2.metric("Collected", f"{s['total_revenue']:,.0f}")
    b2.metric("Costs", f"{s['total_cost']:,.0f}")
    c2b.metric("Net", f"{s['net']:,.0f}")

    st.markdown(
        f"""
        - **Court rental cost**: {s['court_rental_cost']:,.0f} THB ({s['total_court_hours']} court-hrs × rate)
        - **Court fees collected**: {s['court_revenue']:,.0f} THB
        - **Shuttles bought**: {s['shuttles_bought']} → {s['shuttle_purchase_cost']:,.0f} THB
        - **Shuttle fees collected**: {s['shuttle_revenue']:,.0f} THB
        - **Net (collected − costs)**: **{s['net']:,.0f} THB**
        """
    )

    st.subheader("Per player")
    bd = db.monthly_player_breakdown(int(year), int(month))
    st.dataframe(bd, use_container_width=True, hide_index=True)
    if not bd.empty:
        st.download_button(
            "⬇️ Export month per-player (CSV)",
            bd.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"monthly_{int(year)}-{int(month):02d}.csv", mime="text/csv",
        )


# =============================================================================
# PAGE 4 — Shuttle purchases
# =============================================================================
def page_shuttles():
    st.header("🛒 Shuttle Purchases")
    with st.form("buy", clear_on_submit=True):
        d = st.date_input("Purchase date", value=dt.date.today())
        q = st.number_input("Quantity", min_value=1, value=12, step=1)
        u = st.number_input("Unit cost (THB)", min_value=0.0, value=100.0, step=5.0)
        note = st.text_input("Note", value="")
        if st.form_submit_button("Record purchase"):
            db.add_shuttle_purchase(d, int(q), float(u), note)
            st.success("Recorded.")
            st.rerun()
    purch = db.get_shuttle_purchases()
    if not purch.empty:
        purch["total"] = purch["quantity"] * purch["unit_cost"]
        st.dataframe(purch[["purchase_date", "quantity", "unit_cost", "total", "note"]],
                     use_container_width=True, hide_index=True)


# =============================================================================
# PAGE 5 — Players
# =============================================================================
def page_players():
    st.header("👥 Players")
    ps = db.get_players(active_only=False)
    st.dataframe(ps[["id", "name", "is_guest", "active"]], use_container_width=True, hide_index=True)
    with st.form("newp", clear_on_submit=True):
        n = st.text_input("New player name")
        g = st.checkbox("Guest", value=False)
        if st.form_submit_button("Add player") and n.strip():
            db.add_player(n, is_guest=g)
            st.rerun()
    st.caption("Deactivate a player (keeps their history, hides from check-in):")
    for _, p in ps[ps["active"]].iterrows():
        if st.button(f"Deactivate {p['name']}", key=f"deact_{p['id']}"):
            db.set_player_active(int(p["id"]), False)
            st.rerun()


# =============================================================================
# PAGE 6 — Data / audit
# =============================================================================
def page_data():
    st.header("🗄️ Data & Audit")
    st.caption("Raw records for tracing mistakes. Each table exports to CSV.")
    for name in ["sessions", "attendance", "games", "game_players", "players", "shuttle_purchases"]:
        with st.expander(name):
            d = db.table_df(name)
            st.dataframe(d, use_container_width=True, hide_index=True)
            st.download_button(f"⬇️ {name}.csv", d.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{name}.csv", mime="text/csv", key=f"dl_{name}")


# =============================================================================
def main():
    inject_css()
    st.title("🏸 Badminton Tracker")
    tabs = st.tabs(["📋 Session", "💰 Daily", "📅 Monthly", "🛒 Shuttles", "👥 Players", "🗄️ Data"])
    with tabs[0]:
        page_session()
    with tabs[1]:
        page_daily()
    with tabs[2]:
        page_monthly()
    with tabs[3]:
        page_shuttles()
    with tabs[4]:
        page_players()
    with tabs[5]:
        page_data()


if __name__ == "__main__":
    main()
