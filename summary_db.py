"""Local SQLite summary database for the Badminton Tracker.

Provides fast, offline-capable reads of historical session data
without hitting the Google Sheets API quota.
"""
from __future__ import annotations

import sqlite3
import datetime as dt
from pathlib import Path

DB_PATH = Path(__file__).parent / ".badminton.db"


def _get_conn() -> sqlite3.Connection:
    """Get or create the SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every app boot."""
    conn = _get_conn()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


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
    """Save or update a submitted session in the local DB.

    Returns True on success. Upserts the session row, then replaces all
    per-player rows and game rows for that session.
    """
    date_str = session_date.isoformat()
    present = [n for n, v in attendance.items() if v]
    n_present = len(present)
    total_shuttle = sum(player_shuttle_cost.values())
    total_court = n_present * 80.0
    total_amount = total_shuttle + total_court

    conn = _get_conn()
    try:
        # Upsert the session row
        conn.execute(
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
             shuttle_price, total_shuttle, total_court,
             total_amount, n_present),
        )

        # Get the session id
        row = conn.execute("SELECT id FROM sessions WHERE date = ?", (date_str,)).fetchone()
        session_id = row["id"]

        # Delete old player + game rows for this session, then re-insert
        conn.execute("DELETE FROM session_players WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM session_games WHERE session_id = ?", (session_id,))

        # Insert per-player rows
        for player_name in sorted(player_types.keys()):
            ptype = player_types[player_name]
            attended = 1 if player_name in present else 0
            gp = player_game_count.get(player_name, 0)
            sc = player_shuttle_cost.get(player_name, 0.0)
            cf = 80.0 if player_name in present else 0.0
            total = sc + cf

            conn.execute(
                """INSERT INTO session_players
                   (session_id, player_name, player_type, attended,
                    games_played, shuttle_cost, court_fee, total)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, player_name, ptype, attended, gp, sc, cf, total),
            )

        # Insert game rows
        for gi, g in enumerate(recorded_games, start=1):
            players_str = ", ".join(g.get("players", []))
            shuttles = g.get("shuttles", 0)
            conn.execute(
                "INSERT INTO session_games (session_id, game_number, players, shuttles) VALUES (?, ?, ?, ?)",
                (session_id, gi, players_str, shuttles),
            )

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ── Queries ────────────────────────────────────────────────────────────


def get_sessions() -> list[dict]:
    """Return all sessions ordered by date descending."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY date DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(date_str: str) -> dict | None:
    """Return a single session by date string (e.g. '2026-07-01')."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_session_players(session_id: int) -> list[dict]:
    """Return all player rows for a session."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM session_players WHERE session_id = ? ORDER BY player_name",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_games(session_id: int) -> list[dict]:
    """Return all game rows for a session."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM session_games WHERE session_id = ? ORDER BY game_number",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_player_summary() -> list[dict]:
    """Aggregate per-player totals across all sessions."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
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
           ORDER BY total_due DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_summaries() -> list[dict]:
    """Return per-session summaries (date, players, games, totals)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT
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
           ORDER BY s.date DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_player_history(player_name: str) -> list[dict]:
    """Return all sessions a specific player attended."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT s.date, s.day_name, sp.games_played,
                  sp.shuttle_cost, sp.court_fee, sp.total, sp.payment_status
           FROM session_players sp
           JOIN sessions s ON s.id = sp.session_id
           WHERE sp.player_name = ? AND sp.attended = 1
           ORDER BY s.date DESC""",
        (player_name,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_empty() -> bool:
    """Check if the DB has any sessions."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()
    conn.close()
    return row["cnt"] == 0


def get_stats() -> dict:
    """Return top-level season stats."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT
            COUNT(*) AS total_sessions,
            COALESCE(SUM(player_count), 0) AS total_checkins,
            COALESCE(SUM(total_shuttle_cost), 0) AS total_shuttle_cost,
            COALESCE(SUM(total_court_fees), 0) AS total_court_fees,
            COALESCE(SUM(total_amount), 0) AS total_collected
           FROM sessions"""
    ).fetchone()
    conn.close()
    return dict(row)
