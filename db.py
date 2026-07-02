"""
Data layer for the Badminton Tracker.
=====================================
A small SQLAlchemy-Core repository. Uses **SQLite by default** (a local file,
great for development) and transparently switches to **Postgres / Supabase**
when a connection string is provided — so the deployed app can persist data.

Connection string resolution (first hit wins):
  1. st.secrets["database"]["url"]      (Streamlit Cloud → Settings → Secrets)
  2. env var  DATABASE_URL
  3. sqlite:///badminton.db             (local fallback)

All money is THB. Times are ISO dates (YYYY-MM-DD).
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Optional

import pandas as pd
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)

# --- Defaults (overridable per session in the UI) ----------------------------
DEFAULT_COURT_FEE = 80.0        # THB per person per day (what players pay)
DEFAULT_COURT_RATE = 155.0      # THB per court per hour (actual venue cost)
DEFAULT_SHUTTLE_PRICE = 100.0   # THB per shuttle (split among a game's players)
COURTS = ["9", "10"]            # courts currently in use

SEED_PLAYERS = [
    "โรจน์", "น้อย", "ภูมี", "ป๊อป ภู", "คะน้า", "จืด",
    "เกียรติ", "อองรี", "ป๊อป", "น้อต", "ต้น", "ทรัมป",
]

metadata = MetaData()

# Tables use a `bt_` prefix so this app owns its own namespace and can never
# collide with tables left behind by other apps in a shared database.
players = Table(
    "bt_players", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(120), nullable=False, unique=True),
    Column("is_guest", Boolean, nullable=False, default=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, default=dt.datetime.utcnow),
)

sessions = Table(
    "bt_sessions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_date", Date, nullable=False, unique=True),
    Column("court9_hours", Integer, nullable=False, default=0),
    Column("court10_hours", Integer, nullable=False, default=0),
    Column("court_rate", Float, nullable=False, default=DEFAULT_COURT_RATE),
    Column("court_fee", Float, nullable=False, default=DEFAULT_COURT_FEE),
    Column("shuttle_price", Float, nullable=False, default=DEFAULT_SHUTTLE_PRICE),
    Column("note", String(500), default=""),
    Column("created_at", DateTime, default=dt.datetime.utcnow),
)

attendance = Table(
    "bt_attendance", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", Integer, ForeignKey("bt_sessions.id"), nullable=False),
    Column("player_id", Integer, ForeignKey("bt_players.id"), nullable=False),
    Column("paid", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, default=dt.datetime.utcnow),
    UniqueConstraint("session_id", "player_id", name="uq_attendance"),
)

games = Table(
    "bt_games", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", Integer, ForeignKey("bt_sessions.id"), nullable=False),
    Column("game_no", Integer, nullable=False),
    Column("shuttles", Integer, nullable=False, default=1),
    Column("created_at", DateTime, default=dt.datetime.utcnow),
)

game_players = Table(
    "bt_game_players", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("game_id", Integer, ForeignKey("bt_games.id"), nullable=False),
    Column("player_id", Integer, ForeignKey("bt_players.id"), nullable=False),
    UniqueConstraint("game_id", "player_id", name="uq_game_player"),
)

shuttle_purchases = Table(
    "bt_shuttle_purchases", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("purchase_date", Date, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_cost", Float, nullable=False),
    Column("note", String(300), default=""),
    Column("created_at", DateTime, default=dt.datetime.utcnow),
)


# --- Engine ------------------------------------------------------------------
_engine = None


def _resolve_url() -> str:
    try:
        import streamlit as st

        if "database" in st.secrets and st.secrets["database"].get("url"):
            return st.secrets["database"]["url"]
    except Exception:
        pass
    return os.environ.get("DATABASE_URL", "sqlite:///badminton.db")


def get_engine():
    global _engine
    if _engine is None:
        url = _resolve_url()
        # Supabase/Postgres URLs sometimes come as postgres:// — normalise.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("sqlite"):
            _engine = create_engine(
                url, connect_args={"check_same_thread": False}, pool_pre_ping=True
            )
        else:
            # Postgres/Supabase: connect through the transaction pooler
            # (pgbouncer). Don't keep a client-side pool — let pgbouncer pool —
            # so connections can't go stale while a free-tier host sleeps.
            from sqlalchemy.pool import NullPool

            _engine = create_engine(url, poolclass=NullPool)
    return _engine


def init_db(seed: bool = True) -> None:
    """Create tables if missing and seed the starting roster once."""
    eng = get_engine()
    metadata.create_all(eng)
    if seed:
        with eng.begin() as cx:
            existing = cx.execute(select(func.count()).select_from(players)).scalar()
            if not existing:
                cx.execute(
                    insert(players),
                    [{"name": n, "is_guest": False, "active": True} for n in SEED_PLAYERS],
                )


# --- Players -----------------------------------------------------------------
def get_players(active_only: bool = True) -> pd.DataFrame:
    q = select(players).order_by(players.c.id)
    if active_only:
        q = q.where(players.c.active == True)  # noqa: E712
    with get_engine().connect() as cx:
        return pd.read_sql(q, cx)


def add_player(name: str, is_guest: bool = False) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    eng = get_engine()
    with eng.begin() as cx:
        exists = cx.execute(
            select(players.c.id).where(players.c.name == name)
        ).first()
        if exists:
            return exists[0]
        res = cx.execute(insert(players).values(name=name, is_guest=is_guest, active=True))
        return int(res.inserted_primary_key[0])


def set_player_active(player_id: int, active: bool) -> None:
    with get_engine().begin() as cx:
        cx.execute(update(players).where(players.c.id == player_id).values(active=active))


# --- Sessions ----------------------------------------------------------------
def get_or_create_session(session_date: dt.date) -> int:
    eng = get_engine()
    with eng.begin() as cx:
        row = cx.execute(
            select(sessions.c.id).where(sessions.c.session_date == session_date)
        ).first()
        if row:
            return int(row[0])
        res = cx.execute(insert(sessions).values(session_date=session_date))
        return int(res.inserted_primary_key[0])


def get_session(session_id: int) -> dict:
    with get_engine().connect() as cx:
        row = cx.execute(select(sessions).where(sessions.c.id == session_id)).mappings().first()
        return dict(row) if row else {}


def update_session(session_id: int, **fields) -> None:
    if not fields:
        return
    with get_engine().begin() as cx:
        cx.execute(update(sessions).where(sessions.c.id == session_id).values(**fields))


# --- Attendance --------------------------------------------------------------
def check_in(session_id: int, player_id: int) -> None:
    eng = get_engine()
    with eng.begin() as cx:
        exists = cx.execute(
            select(attendance.c.id).where(
                attendance.c.session_id == session_id,
                attendance.c.player_id == player_id,
            )
        ).first()
        if not exists:
            cx.execute(insert(attendance).values(session_id=session_id, player_id=player_id))


def check_out(session_id: int, player_id: int) -> None:
    """Remove a check-in (and drop the player from that session's games)."""
    with get_engine().begin() as cx:
        gids = [
            r[0] for r in cx.execute(
                select(games.c.id).where(games.c.session_id == session_id)
            ).all()
        ]
        if gids:
            cx.execute(
                delete(game_players).where(
                    game_players.c.player_id == player_id,
                    game_players.c.game_id.in_(gids),
                )
            )
        cx.execute(
            delete(attendance).where(
                attendance.c.session_id == session_id,
                attendance.c.player_id == player_id,
            )
        )


def set_paid(session_id: int, player_id: int, paid: bool) -> None:
    with get_engine().begin() as cx:
        cx.execute(
            update(attendance)
            .where(attendance.c.session_id == session_id, attendance.c.player_id == player_id)
            .values(paid=paid)
        )


def get_attendance(session_id: int) -> pd.DataFrame:
    q = (
        select(
            attendance.c.player_id,
            players.c.name,
            players.c.is_guest,
            attendance.c.paid,
        )
        .select_from(attendance.join(players, players.c.id == attendance.c.player_id))
        .where(attendance.c.session_id == session_id)
        .order_by(players.c.name)
    )
    with get_engine().connect() as cx:
        return pd.read_sql(q, cx)


# --- Games -------------------------------------------------------------------
def add_game(session_id: int, player_ids: list[int], shuttles: int = 1) -> int:
    eng = get_engine()
    with eng.begin() as cx:
        next_no = (
            cx.execute(
                select(func.coalesce(func.max(games.c.game_no), 0)).where(
                    games.c.session_id == session_id
                )
            ).scalar()
            or 0
        ) + 1
        res = cx.execute(
            insert(games).values(session_id=session_id, game_no=next_no, shuttles=shuttles)
        )
        gid = int(res.inserted_primary_key[0])
        if player_ids:
            cx.execute(
                insert(game_players),
                [{"game_id": gid, "player_id": pid} for pid in player_ids],
            )
        return gid


def update_game(game_id: int, player_ids: list[int], shuttles: int) -> None:
    with get_engine().begin() as cx:
        cx.execute(update(games).where(games.c.id == game_id).values(shuttles=shuttles))
        cx.execute(delete(game_players).where(game_players.c.game_id == game_id))
        if player_ids:
            cx.execute(
                insert(game_players),
                [{"game_id": game_id, "player_id": pid} for pid in player_ids],
            )


def delete_game(game_id: int) -> None:
    with get_engine().begin() as cx:
        cx.execute(delete(game_players).where(game_players.c.game_id == game_id))
        cx.execute(delete(games).where(games.c.id == game_id))


def get_games(session_id: int) -> list[dict]:
    """Return games with their player-id lists and shuttle counts."""
    eng = get_engine()
    with eng.connect() as cx:
        grows = cx.execute(
            select(games).where(games.c.session_id == session_id).order_by(games.c.game_no)
        ).mappings().all()
        out = []
        for g in grows:
            pids = [
                r[0] for r in cx.execute(
                    select(game_players.c.player_id).where(game_players.c.game_id == g["id"])
                ).all()
            ]
            out.append({"id": g["id"], "game_no": g["game_no"], "shuttles": g["shuttles"], "player_ids": pids})
        return out


# --- Shuttle purchases -------------------------------------------------------
def add_shuttle_purchase(purchase_date: dt.date, quantity: int, unit_cost: float, note: str = "") -> None:
    with get_engine().begin() as cx:
        cx.execute(
            insert(shuttle_purchases).values(
                purchase_date=purchase_date, quantity=quantity, unit_cost=unit_cost, note=note
            )
        )


def get_shuttle_purchases() -> pd.DataFrame:
    with get_engine().connect() as cx:
        return pd.read_sql(select(shuttle_purchases).order_by(shuttle_purchases.c.purchase_date), cx)


# --- Calculations ------------------------------------------------------------
def compute_daily_split(session_id: int) -> pd.DataFrame:
    """Per-player breakdown for a session.

    court fee (flat, per checked-in player) + shuttle share (each game's
    shuttle cost shared equally among its players). Returns columns:
    Player, GamesPlayed, ShuttleCost, CourtFee, Total, Paid.
    """
    sess = get_session(session_id)
    if not sess:
        return pd.DataFrame(
            columns=["Player", "GamesPlayed", "ShuttleCost", "CourtFee", "Total", "Paid"]
        )
    court_fee = float(sess["court_fee"])
    price = float(sess["shuttle_price"])

    att = get_attendance(session_id)  # player_id, name, is_guest, paid
    if att.empty:
        return pd.DataFrame(
            columns=["Player", "GamesPlayed", "ShuttleCost", "CourtFee", "Total", "Paid"]
        )

    shuttle_cost = {int(pid): 0.0 for pid in att["player_id"]}
    games_played = {int(pid): 0 for pid in att["player_id"]}
    for g in get_games(session_id):
        valid = [p for p in g["player_ids"] if p in shuttle_cost]
        if not valid:
            continue
        per = g["shuttles"] * price / len(valid)
        for p in valid:
            shuttle_cost[p] += per
            games_played[p] += 1

    rows = []
    for _, r in att.iterrows():
        pid = int(r["player_id"])
        sc = round(shuttle_cost[pid], 2)
        rows.append(
            {
                "Player": r["name"],
                "GamesPlayed": games_played[pid],
                "ShuttleCost": sc,
                "CourtFee": round(court_fee, 2),
                "Total": round(court_fee + sc, 2),
                "Paid": bool(r["paid"]),
            }
        )
    return pd.DataFrame(rows)


def monthly_summary(year: int, month: int) -> dict:
    """Aggregate a month: court hours/cost, shuttle purchases/cost, revenue."""
    start = dt.date(year, month, 1)
    end = dt.date(year + (month // 12), (month % 12) + 1, 1)

    with get_engine().connect() as cx:
        srows = cx.execute(
            select(sessions).where(
                sessions.c.session_date >= start, sessions.c.session_date < end
            )
        ).mappings().all()

    session_ids = [s["id"] for s in srows]
    total_court_hours = sum((s["court9_hours"] + s["court10_hours"]) for s in srows)
    court_rental_cost = sum(
        (s["court9_hours"] + s["court10_hours"]) * s["court_rate"] for s in srows
    )

    # Revenue = sum of daily splits across the month.
    court_revenue = shuttle_revenue = 0.0
    n_attendance = 0
    for sid in session_ids:
        df = compute_daily_split(sid)
        court_revenue += float(df["CourtFee"].sum()) if not df.empty else 0.0
        shuttle_revenue += float(df["ShuttleCost"].sum()) if not df.empty else 0.0
        n_attendance += len(df)

    # Shuttle purchases in the month.
    purch = get_shuttle_purchases()
    if not purch.empty:
        purch["purchase_date"] = pd.to_datetime(purch["purchase_date"])
        m = purch[(purch["purchase_date"] >= pd.Timestamp(start)) & (purch["purchase_date"] < pd.Timestamp(end))]
        shuttles_bought = int(m["quantity"].sum())
        shuttle_purchase_cost = float((m["quantity"] * m["unit_cost"]).sum())
    else:
        shuttles_bought = 0
        shuttle_purchase_cost = 0.0

    total_revenue = court_revenue + shuttle_revenue
    total_cost = court_rental_cost + shuttle_purchase_cost
    return {
        "sessions": len(srows),
        "attendances": n_attendance,
        "total_court_hours": total_court_hours,
        "court_rental_cost": round(court_rental_cost, 2),
        "shuttles_bought": shuttles_bought,
        "shuttle_purchase_cost": round(shuttle_purchase_cost, 2),
        "court_revenue": round(court_revenue, 2),
        "shuttle_revenue": round(shuttle_revenue, 2),
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "net": round(total_revenue - total_cost, 2),
    }


def monthly_player_breakdown(year: int, month: int) -> pd.DataFrame:
    """Per-player totals for the month (owed, paid, outstanding, games)."""
    start = dt.date(year, month, 1)
    end = dt.date(year + (month // 12), (month % 12) + 1, 1)
    with get_engine().connect() as cx:
        sids = [
            r[0] for r in cx.execute(
                select(sessions.c.id).where(
                    sessions.c.session_date >= start, sessions.c.session_date < end
                )
            ).all()
        ]
    frames = []
    for sid in sids:
        df = compute_daily_split(sid)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["Player", "Days", "Games", "Owed", "Paid", "Outstanding"])
    allrows = pd.concat(frames, ignore_index=True)
    grp = allrows.groupby("Player")
    out = pd.DataFrame({
        "Days": grp.size(),
        "Games": grp["GamesPlayed"].sum(),
        "Owed": grp["Total"].sum().round(2),
        "Paid": grp.apply(lambda g: g.loc[g["Paid"], "Total"].sum()).round(2),
    }).reset_index()
    out["Outstanding"] = (out["Owed"] - out["Paid"]).round(2)
    return out.sort_values("Outstanding", ascending=False)


# --- Export / audit ----------------------------------------------------------
def table_df(name: str) -> pd.DataFrame:
    tbl = {
        "players": players,
        "sessions": sessions,
        "attendance": attendance,
        "games": games,
        "game_players": game_players,
        "shuttle_purchases": shuttle_purchases,
    }[name]
    with get_engine().connect() as cx:
        return pd.read_sql(select(tbl), cx)
