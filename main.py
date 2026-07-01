"""
🏸 Badminton Tracker — NiceGUI frontend
=======================================
A smooth, mobile-friendly UI over the same database layer as the Streamlit app
(`db.py`). No full-page reruns; sortable/searchable data tables everywhere.

Run locally:   python main.py       (opens http://localhost:8080)
Deploy:        any host that runs a long-lived process — Render / Railway /
               Fly.io / a VPS. Reads PORT from the environment.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
from nicegui import ui

import db

db.init_db()

# --- shared UI state ---------------------------------------------------------
state = {"date": dt.date.today()}


def current_sid() -> int:
    return db.get_or_create_session(state["date"])


def name_id_maps(active_only=True):
    ps = db.get_players(active_only=active_only)
    return dict(zip(ps["name"], ps["id"])), dict(zip(ps["id"], ps["name"])), ps


def _san(v):
    """Make a cell value JSON-serializable for ui.table."""
    import numpy as np

    if v is None:
        return None
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, np.generic):
        return v.item()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def df_to_table(df: pd.DataFrame, row_key: str | None = None):
    """Build (columns, rows) for ui.table from a DataFrame — all sortable."""
    cols = [
        {"name": c, "label": c, "field": c, "sortable": True, "align": "left"}
        for c in df.columns
    ]
    rows = [{k: _san(v) for k, v in rec.items()} for rec in df.to_dict("records")]
    return cols, rows


def download_df(df: pd.DataFrame, filename: str):
    ui.download(df.to_csv(index=False).encode("utf-8-sig"), filename)


# =============================================================================
# SESSION tab
# =============================================================================
@ui.refreshable
def session_tab():
    name_to_id, id_to_name, ps = name_id_maps(active_only=True)
    sid = current_sid()
    sess = db.get_session(sid)

    with ui.row().classes("w-full items-center"):
        ui.icon("event").classes("text-2xl")
        ui.date(value=state["date"].isoformat(), on_change=_on_date_change).props("dense")

    # ---- Courts ----
    with ui.card().classes("w-full"):
        ui.label("🏟️ Courts & hours").classes("text-lg font-bold")
        ui.label(f"{sess['court_rate']:.0f} THB / court / hour (venue cost)").classes("text-sm text-gray-500")
        court_fields = {"9": "court9_hours", "10": "court10_hours"}
        cost_label = ui.label().classes("text-sm")

        def refresh_cost():
            s = db.get_session(sid)
            h = s["court9_hours"] + s["court10_hours"]
            cost_label.text = f"Total: {h} court-hour(s) → {h * s['court_rate']:.0f} THB"

        with ui.row():
            for c in db.COURTS:
                with ui.column().classes("items-center"):
                    ui.label(f"Court {c}")
                    ui.toggle(
                        {0: "0", 1: "1", 2: "2", 3: "3"},
                        value=int(sess[court_fields[c]]),
                        on_change=lambda e, f=court_fields[c]: (
                            db.update_session(sid, **{f: int(e.value)}),
                            refresh_cost(),
                        ),
                    ).props("dense")
        refresh_cost()

    # ---- Check-in ----
    att = db.get_attendance(sid)
    checked = set(int(x) for x in att["player_id"]) if not att.empty else set()
    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("✅ Check-in").classes("text-lg font-bold")
            count_label = ui.label(f"{len(checked)} in").classes("text-sm font-bold")

        def toggle_checkin(e, pid):
            if e.value:
                db.check_in(sid, pid)
            else:
                db.check_out(sid, pid)
            att2 = db.get_attendance(sid)
            count_label.text = f"{len(att2)} in"

        with ui.grid(columns=2).classes("w-full gap-1"):
            for _, p in ps.iterrows():
                pid = int(p["id"])
                label = p["name"] + (" 👤" if p["is_guest"] else "")
                ui.switch(label, value=pid in checked,
                          on_change=lambda e, pid=pid: toggle_checkin(e, pid))

        with ui.expansion("➕ Add a player who joined today").classes("w-full"):
            new_name = ui.input("Name").classes("w-full")
            guest = ui.checkbox("Guest (one-off)", value=True)

            def add_player():
                if new_name.value.strip():
                    pid = db.add_player(new_name.value, is_guest=guest.value)
                    db.check_in(sid, pid)
                    ui.notify(f"Added {new_name.value}", type="positive")
                    session_tab.refresh()
                    daily_tab.refresh()

            ui.button("Add & check in", on_click=add_player)

    # ---- Games ----
    att = db.get_attendance(sid)
    present = list(att["name"]) if not att.empty else []
    with ui.card().classes("w-full"):
        ui.label("🎮 Games").classes("text-lg font-bold")
        if not present:
            ui.label("Check players in first, then add games.").classes("text-sm text-gray-500")
        else:
            with ui.row().classes("w-full items-end"):
                new_players = ui.select(present, multiple=True, label="Players (usually 4)").classes("grow").props("dense use-chips")
                new_shuttles = ui.number("Shuttles", value=1, min=0, format="%d").props("dense")

                def add_game():
                    picks = new_players.value or []
                    if picks:
                        db.add_game(sid, [int(name_to_id[n]) for n in picks], int(new_shuttles.value or 0))
                        ui.notify("Game added", type="positive")
                        session_tab.refresh()
                        daily_tab.refresh()
                    else:
                        ui.notify("Pick at least one player", type="warning")

                ui.button("➕ Add", on_click=add_game)

            for g in db.get_games(sid):
                cur = [id_to_name.get(pid) for pid in g["player_ids"] if pid in id_to_name]
                with ui.card().classes("w-full bg-gray-50"):
                    ui.label(f"Game {g['game_no']}").classes("font-bold")
                    with ui.row().classes("w-full items-end"):
                        sel = ui.select(present, value=[n for n in cur if n in present],
                                        multiple=True).classes("grow").props("dense use-chips")
                        shn = ui.number("Shuttles", value=int(g["shuttles"]), min=0, format="%d").props("dense")

                        def save_game(gid=g["id"], sel=sel, shn=shn):
                            db.update_game(gid, [int(name_to_id[n]) for n in (sel.value or [])], int(shn.value or 0))
                            ui.notify("Saved", type="positive")
                            daily_tab.refresh()

                        def del_game(gid=g["id"]):
                            db.delete_game(gid)
                            session_tab.refresh()
                            daily_tab.refresh()

                        ui.button(icon="save", on_click=save_game).props("flat")
                        ui.button(icon="delete", on_click=del_game).props("flat color=red")


def _on_date_change(e):
    state["date"] = dt.date.fromisoformat(e.value)
    session_tab.refresh()
    daily_tab.refresh()


# =============================================================================
# DAILY tab
# =============================================================================
@ui.refreshable
def daily_tab():
    sid = current_sid()
    df = db.compute_daily_split(sid)
    ui.label(f"💰 Daily — {state['date']}").classes("text-xl font-bold")
    if df.empty:
        ui.label("No check-ins yet for this date.").classes("text-gray-500")
        return

    total = float(df["Total"].sum())
    paid = float(df.loc[df["Paid"], "Total"].sum())
    with ui.row().classes("w-full gap-4"):
        _metric("Players", len(df))
        _metric("Total due", f"{total:,.0f}")
        _metric("Collected", f"{paid:,.0f}")
        _metric("Outstanding", f"{total - paid:,.0f}")

    name_to_id, _, _ = name_id_maps(active_only=False)
    for _, r in df.iterrows():
        pid = int(name_to_id[r["Player"]])
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label(r["Player"]).classes("font-bold")
                    ui.label(f"{int(r['GamesPlayed'])} games · court {r['CourtFee']:.0f} · shuttle {r['ShuttleCost']:.0f}").classes("text-xs text-gray-500")
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"{r['Total']:,.0f} ฿").classes("text-lg font-bold")
                    ui.checkbox("Paid", value=bool(r["Paid"]),
                                on_change=lambda e, pid=pid: (db.set_paid(sid, pid, e.value), daily_tab.refresh()))

    ui.button("⬇️ Export day (CSV)", on_click=lambda: download_df(df, f"daily_{state['date']}.csv")).props("outline")


def _metric(label, value):
    with ui.card().classes("items-center"):
        ui.label(str(value)).classes("text-2xl font-bold")
        ui.label(label).classes("text-xs text-gray-500")


# =============================================================================
# MONTHLY tab
# =============================================================================
@ui.refreshable
def monthly_tab():
    today = dt.date.today()
    with ui.row():
        year = ui.number("Year", value=today.year, format="%d").props("dense")
        month = ui.number("Month", value=today.month, min=1, max=12, format="%d").props("dense")
        ui.button("Refresh", on_click=lambda: _render_month(int(year.value), int(month.value), holder))
    holder = ui.column().classes("w-full")
    _render_month(today.year, today.month, holder)


def _render_month(year, month, holder):
    holder.clear()
    s = db.monthly_summary(year, month)
    bd = db.monthly_player_breakdown(year, month)
    with holder:
        with ui.row().classes("w-full gap-4"):
            _metric("Sessions", s["sessions"])
            _metric("Court-hours", s["total_court_hours"])
            _metric("Collected", f"{s['total_revenue']:,.0f}")
            _metric("Costs", f"{s['total_cost']:,.0f}")
            _metric("Net", f"{s['net']:,.0f}")
        ui.markdown(
            f"- **Court rental cost**: {s['court_rental_cost']:,.0f} · "
            f"**Court fees**: {s['court_revenue']:,.0f}\n"
            f"- **Shuttles bought**: {s['shuttles_bought']} → {s['shuttle_purchase_cost']:,.0f} · "
            f"**Shuttle fees**: {s['shuttle_revenue']:,.0f}"
        )
        if not bd.empty:
            cols, rows = df_to_table(bd)
            ui.table(columns=cols, rows=rows).classes("w-full").props("dense")
            ui.button("⬇️ Export (CSV)", on_click=lambda: download_df(bd, f"monthly_{year}-{month:02d}.csv")).props("outline")


# =============================================================================
# SHUTTLES tab
# =============================================================================
@ui.refreshable
def shuttles_tab():
    ui.label("🛒 Shuttle purchases").classes("text-xl font-bold")
    with ui.row().classes("items-end"):
        d = ui.date(value=dt.date.today().isoformat()).props("dense")
        q = ui.number("Qty", value=12, min=1, format="%d").props("dense")
        u = ui.number("Unit cost", value=100, min=0).props("dense")
        note = ui.input("Note").props("dense")

        def buy():
            db.add_shuttle_purchase(dt.date.fromisoformat(d.value), int(q.value), float(u.value), note.value or "")
            ui.notify("Recorded", type="positive")
            shuttles_tab.refresh()

        ui.button("Record", on_click=buy)
    purch = db.get_shuttle_purchases()
    if not purch.empty:
        purch = purch.copy()
        purch["total"] = purch["quantity"] * purch["unit_cost"]
        cols, rows = df_to_table(purch[["purchase_date", "quantity", "unit_cost", "total", "note"]])
        ui.table(columns=cols, rows=rows).classes("w-full").props("dense")


# =============================================================================
# PLAYERS tab
# =============================================================================
@ui.refreshable
def players_tab():
    ui.label("👥 Players").classes("text-xl font-bold")
    ps = db.get_players(active_only=False)
    cols, rows = df_to_table(ps[["id", "name", "is_guest", "active"]])
    ui.table(columns=cols, rows=rows).classes("w-full").props("dense")
    with ui.row().classes("items-end"):
        n = ui.input("New player").props("dense")
        g = ui.checkbox("Guest")

        def add():
            if n.value.strip():
                db.add_player(n.value, is_guest=g.value)
                ui.notify("Added", type="positive")
                players_tab.refresh()
                session_tab.refresh()

        ui.button("Add", on_click=add)


# =============================================================================
# DATA tab (audit — sortable/searchable tables)
# =============================================================================
@ui.refreshable
def data_tab():
    ui.label("🗄️ Data & audit").classes("text-xl font-bold")
    ui.label("Every table is sortable/searchable and exports to CSV.").classes("text-sm text-gray-500")
    for name in ["sessions", "attendance", "games", "game_players", "players", "shuttle_purchases"]:
        with ui.expansion(name).classes("w-full"):
            d = db.table_df(name)
            cols, rows = df_to_table(d)
            table = ui.table(columns=cols, rows=rows).classes("w-full").props("dense")
            with table.add_slot("top-right"):
                ui.input(placeholder="Search").bind_value(table, "filter").props("dense borderless")
            ui.button(f"⬇️ {name}.csv", on_click=lambda d=d, name=name: download_df(d, f"{name}.csv")).props("outline")


# =============================================================================
# Layout
# =============================================================================
@ui.page("/")
def index():
    ui.colors(primary="#16a34a")
    with ui.header().classes("items-center"):
        ui.label("🏸 Badminton Tracker").classes("text-xl font-bold")
    with ui.tabs().classes("w-full") as tabs:
        t_session = ui.tab("Session", icon="event")
        t_daily = ui.tab("Daily", icon="payments")
        t_monthly = ui.tab("Monthly", icon="calendar_month")
        t_shuttles = ui.tab("Shuttles", icon="shopping_cart")
        t_players = ui.tab("Players", icon="group")
        t_data = ui.tab("Data", icon="storage")
    with ui.tab_panels(tabs, value=t_session).classes("w-full"):
        with ui.tab_panel(t_session):
            session_tab()
        with ui.tab_panel(t_daily):
            daily_tab()
        with ui.tab_panel(t_monthly):
            monthly_tab()
        with ui.tab_panel(t_shuttles):
            shuttles_tab()
        with ui.tab_panel(t_players):
            players_tab()
        with ui.tab_panel(t_data):
            data_tab()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Badminton Tracker",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=False,
        show=False,
        storage_secret=os.environ.get("STORAGE_SECRET", "badminton-dev-secret"),
    )
