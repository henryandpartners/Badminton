"""
Database layer for the Badminton Tracker.

Supports both SQLite (local dev) and PostgreSQL (Streamlit Cloud).
Configure with the DATABASE_URL environment variable or Streamlit secret.

Examples:
  SQLite:       sqlite:///.badminton.db
  PostgreSQL:   postgresql://user:pass@host:5432/dbname

If no DATABASE_URL is set, defaults to SQLite at .badminton.db
in the app directory (local dev mode).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

try:
    import streamlit as st
    HAS_STREAMLIT = True
except Exception:
    HAS_STREAMLIT = False

# ── Database URL resolution ─────────────────────────────────────────────
def _get_database_url() -> str:
    """Resolve the database URL from, in order:
    1. DATABASE_URL environment variable
    2. Streamlit secret 'database_url'
    3. Default SQLite path
    """
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url

    if HAS_STREAMLIT:
        try:
            url = st.secrets.get("database_url", "")
            if url:
                return url
        except Exception:
            pass

    # Default: SQLite in the app directory
    app_dir = Path(__file__).parent
    db_path = app_dir / ".badminton.db"
    return f"sqlite:///{db_path}"


_DB_URL = _get_database_url()


def _get_conn():
    """Get a database connection appropriate for the URL scheme."""
    if _DB_URL.startswith("postgresql"):
        return _get_pg_conn()
    return _get_sqlite_conn()


def _get_sqlite_conn():
    """SQLite connection."""
    import sqlite3

    path = _DB_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _get_pg_conn():
    """PostgreSQL connection via psycopg2."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_DB_URL)
    conn.autocommit = False
    # Return dict-like rows
    return conn


def _fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    """Execute and return all rows as dicts, regardless of DB backend."""
    if _DB_URL.startswith("postgresql"):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    else:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _fetchone(conn, sql: str, params: tuple = ()) -> dict | None:
    """Execute and return one row as dict, or None."""
    if _DB_URL.startswith("postgresql"):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    else:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _execute(conn, sql: str, params: tuple = ()) -> None:
    """Execute a single statement."""
    if _DB_URL.startswith("postgresql"):
        with conn.cursor() as cur:
            cur.execute(sql, params)
    else:
        conn.execute(sql, params)


def _commit(conn) -> None:
    conn.commit()


def _rollback(conn) -> None:
    if _DB_URL.startswith("postgresql"):
        conn.rollback()
    else:
        conn.rollback()


def _close(conn) -> None:
    conn.close()


# ── Schema ──────────────────────────────────────────────────────────────

SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        day_name TEXT NOT NULL,
        court_hours_court9 REAL DEFAULT 0,
        court_hours_court10 REAL DEFAULT 0,
        shuttle_price REAL DEFAULT 100.0,
        total_shuttle_cost REAL DEFAULT 0,
        total_court_fees REAL DEFAULT 0,
        total_amount REAL DEFAULT 0,
        player_count INTEGER DEFAULT 0,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS session_players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        player_name TEXT NOT NULL,
        player_type TEXT NOT NULL,
        attended BOOLEAN NOT NULL DEFAULT 0,
        games_played INTEGER DEFAULT 0,
        shuttle_cost REAL DEFAULT 0,
        court_fee REAL DEFAULT 0,
        total REAL DEFAULT 0,
        payment_status TEXT DEFAULT 'Pending',
        UNIQUE(session_id, player_name)
    );

    CREATE TABLE IF NOT EXISTS session_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        game_number INTEGER NOT NULL,
        players TEXT NOT NULL,
        shuttles INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
    CREATE INDEX IF NOT EXISTS idx_sesh_players_session ON session_players(session_id);
    CREATE INDEX IF NOT EXISTS idx_sesh_players_name ON session_players(player_name);
"""

PG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        date TEXT NOT NULL UNIQUE,
        day_name TEXT NOT NULL,
        court_hours_court9 REAL DEFAULT 0,
        court_hours_court10 REAL DEFAULT 0,
        shuttle_price REAL DEFAULT 100.0,
        total_shuttle_cost REAL DEFAULT 0,
        total_court_fees REAL DEFAULT 0,
        total_amount REAL DEFAULT 0,
        player_count INTEGER DEFAULT 0,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS session_players (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        player_name TEXT NOT NULL,
        player_type TEXT NOT NULL,
        attended BOOLEAN NOT NULL DEFAULT FALSE,
        games_played INTEGER DEFAULT 0,
        shuttle_cost REAL DEFAULT 0,
        court_fee REAL DEFAULT 0,
        total REAL DEFAULT 0,
        payment_status TEXT DEFAULT 'Pending',
        UNIQUE(session_id, player_name)
    );

    CREATE TABLE IF NOT EXISTS session_games (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        game_number INTEGER NOT NULL,
        players TEXT NOT NULL,
        shuttles INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
    CREATE INDEX IF NOT EXISTS idx_sesh_players_session ON session_players(session_id);
    CREATE INDEX IF NOT EXISTS idx_sesh_players_name ON session_players(player_name);
"""

# ── Init ────────────────────────────────────────────────────────────────
def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    try:
        if _DB_URL.startswith("postgresql"):
            _execute(conn, PG_SCHEMA)
        else:
            for statement in SQLITE_SCHEMA.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    _execute(conn, stmt)
        _commit(conn)
    except Exception:
        _rollback(conn)
        raise
    finally:
        _close(conn)


# ── Save session ────────────────────────────────────────────────────────
def save_session(
    session_date: dt.date,
    day_name: str,
    court_hours: dict[str, int],
    attendance: dict[str, bool],
    player_types: dict[str, str],
    recorded_games: list[dict],
    shuttle_price: float,
    player_game_count: dict[str, int],
    player_shuttle_cost: dict[str, float],
) -> bool:
    date_str = session_date.isoformat()
    present = [n for n, v in attendance.items() if v]
    n_present = len(present)
    total_shuttle = sum(player_shuttle_cost.values())
    total_court = n_present * 80.0
    total_amount = total_shuttle + total_court

    conn = _get_conn()
    try:
        if _DB_URL.startswith("postgresql"):
            _execute(conn,
                """INSERT INTO sessions
                   (date, day_name, court_hours_court9, court_hours_court10,
                    shuttle_price, total_shuttle_cost, total_court_fees,
                    total_amount, player_count, submitted_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (date) DO UPDATE SET
                   day_name=EXCLUDED.day_name,
                   court_hours_court9=EXCLUDED.court_hours_court9,
                   court_hours_court10=EXCLUDED.court_hours_court10,
                   shuttle_price=EXCLUDED.shuttle_price,
                   total_shuttle_cost=EXCLUDED.total_shuttle_cost,
                   total_court_fees=EXCLUDED.total_court_fees,
                   total_amount=EXCLUDED.total_amount,
                   player_count=EXCLUDED.player_count,
                   submitted_at=NOW()""",
                (date_str, day_name, court_hours.get("9", 0), court_hours.get("10", 0),
                 shuttle_price, total_shuttle, total_court, total_amount, n_present),
            )
        else:
            _execute(conn,
                """INSERT INTO sessions
                   (date, day_name, court_hours_court9, court_hours_court10,
                    shuttle_price, total_shuttle_cost, total_court_fees,
                    total_amount, player_count, submitted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(date) DO UPDATE SET
                   day_name=excluded.day_name,
                   court_hours_court9=excluded.court_hours_court9,
                   court_hours_court10=excluded.court_hours_court10,
                   shuttle_price=excluded.shuttle_price,
                   total_shuttle_cost=excluded.total_shuttle_cost,
                   total_court_fees=excluded.total_court_fees,
                   total_amount=excluded.total_amount,
                   player_count=excluded.player_count,
                   submitted_at=datetime('now')""",
                (date_str, day_name, court_hours.get("9", 0), court_hours.get("10", 0),
                 shuttle_price, total_shuttle, total_court, total_amount, n_present),
            )

        # Get session id
        row = _fetchone(conn, "SELECT id FROM sessions WHERE date = %s" if _DB_URL.startswith("postgresql") else "SELECT id FROM sessions WHERE date = ?", (date_str,))
        if not row:
            _rollback(conn)
            return False
        session_id = row["id"]

        # Delete old player + game rows
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        _execute(conn, f"DELETE FROM session_players WHERE session_id = {ph}", (session_id,))
        _execute(conn, f"DELETE FROM session_games WHERE session_id = {ph}", (session_id,))

        # Insert player rows
        for player_name in sorted(player_types.keys()):
            ptype = player_types[player_name]
            attended = 1 if player_name in present else 0
            gp = player_game_count.get(player_name, 0)
            sc = player_shuttle_cost.get(player_name, 0.0)
            cf = 80.0 if player_name in present else 0.0
            total = sc + cf

            _execute(conn,
                f"""INSERT INTO session_players
                   (session_id, player_name, player_type, attended,
                    games_played, shuttle_cost, court_fee, total)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                (session_id, player_name, ptype, attended, gp, sc, cf, total),
            )

        # Insert game rows
        for gi, g in enumerate(recorded_games, start=1):
            players_str = ", ".join(g.get("players", []))
            shuttles = g.get("shuttles", 0)
            _execute(conn,
                f"INSERT INTO session_games (session_id, game_number, players, shuttles) VALUES ({ph}, {ph}, {ph}, {ph})",
                (session_id, gi, players_str, shuttles),
            )

        _commit(conn)
        return True
    except Exception as exc:
        _rollback(conn)
        return False
    finally:
        _close(conn)


# ── Queries ────────────────────────────────────────────────────────────

def get_sessions() -> list[dict]:
    conn = _get_conn()
    try:
        rows = _fetchall(conn, "SELECT * FROM sessions ORDER BY date DESC")
        return rows
    finally:
        _close(conn)


def get_session(date_str: str) -> dict | None:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        return _fetchone(conn, f"SELECT * FROM sessions WHERE date = {ph}", (date_str,))
    finally:
        _close(conn)


def get_session_players(session_id: int) -> list[dict]:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        return _fetchall(
            conn,
            f"SELECT * FROM session_players WHERE session_id = {ph} ORDER BY player_name",
            (session_id,),
        )
    finally:
        _close(conn)


def get_session_games(session_id: int) -> list[dict]:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        return _fetchall(
            conn,
            f"SELECT * FROM session_games WHERE session_id = {ph} ORDER BY game_number",
            (session_id,),
        )
    finally:
        _close(conn)


def get_player_summary() -> list[dict]:
    conn = _get_conn()
    try:
        return _fetchall(conn, """
            SELECT
                sp.player_name,
                sp.player_type,
                COUNT(DISTINCT sp.session_id) AS sessions,
                SUM(sp.games_played) AS total_games,
                SUM(sp.shuttle_cost) AS total_shuttle,
                SUM(sp.court_fee) AS total_court,
                SUM(sp.total) AS total_due
            FROM session_players sp
            WHERE sp.attended = 1
            GROUP BY sp.player_name
            ORDER BY total_due DESC
        """)
    finally:
        _close(conn)


def get_session_summaries() -> list[dict]:
    conn = _get_conn()
    try:
        return _fetchall(conn, """
            SELECT
                s.date,
                s.day_name,
                s.player_count,
                s.total_shuttle_cost,
                s.total_court_fees,
                s.total_amount,
                COALESCE(g.game_count, 0) AS game_count
            FROM sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS game_count
                FROM session_games GROUP BY session_id
            ) g ON g.session_id = s.id
            ORDER BY s.date DESC
        """)
    finally:
        _close(conn)


def get_player_history(player_name: str) -> list[dict]:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        return _fetchall(conn, f"""
            SELECT s.date, s.day_name, sp.games_played,
                   sp.shuttle_cost, sp.court_fee, sp.total, sp.payment_status
            FROM session_players sp
            JOIN sessions s ON s.id = sp.session_id
            WHERE sp.player_name = {ph} AND sp.attended = 1
            ORDER BY s.date DESC
        """, (player_name,))
    finally:
        _close(conn)


def is_empty() -> bool:
    conn = _get_conn()
    try:
        row = _fetchone(conn, "SELECT COUNT(*) AS cnt FROM sessions")
        return row["cnt"] == 0 if row else True
    finally:
        _close(conn)


def get_stats() -> dict:
    conn = _get_conn()
    try:
        row = _fetchone(conn, """
            SELECT
                COUNT(*) AS total_sessions,
                COALESCE(SUM(player_count), 0) AS total_checkins,
                COALESCE(SUM(total_shuttle_cost), 0) AS total_shuttle_cost,
                COALESCE(SUM(total_court_fees), 0) AS total_court_fees,
                COALESCE(SUM(total_amount), 0) AS total_collected
            FROM sessions
        """)
        return dict(row) if row else {
            "total_sessions": 0, "total_checkins": 0,
            "total_shuttle_cost": 0, "total_court_fees": 0, "total_collected": 0,
        }
    finally:
        _close(conn)


def update_payment_status(session_id: int, player_name: str, status: str) -> bool:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        _execute(conn,
            f"UPDATE session_players SET payment_status = {ph} WHERE session_id = {ph} AND player_name = {ph}",
            (status, session_id, player_name),
        )
        _commit(conn)
        return True
    except Exception:
        return False
    finally:
        _close(conn)


def set_player_court_fee(session_id: int, player_name: str, court_fee: float) -> bool:
    conn = _get_conn()
    try:
        ph = "%s" if _DB_URL.startswith("postgresql") else "?"
        _execute(conn,
            f"UPDATE session_players SET court_fee = {ph}, total = shuttle_cost + {ph} WHERE session_id = {ph} AND player_name = {ph}",
            (court_fee, court_fee, session_id, player_name),
        )
        _commit(conn)
        return True
    except Exception:
        return False
    finally:
        _close(conn)


def get_db_info() -> dict:
    """Return info about the current database connection."""
    return {
        "type": "PostgreSQL" if _DB_URL.startswith("postgresql") else "SQLite",
        "url": _DB_URL.split("@")[-1] if "@" in _DB_URL else _DB_URL,
    }
