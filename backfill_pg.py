"""One-time script: backfill local SQLite data to Supabase PostgreSQL."""
import sqlite3, psycopg2, psycopg2.extras

PG_URL = "postgresql://postgres:Badminton101!@db.wslqmenvqgqybiadnjig.supabase.co:5432/postgres"

# Read local SQLite
local = sqlite3.connect(".badminton.db")
local.row_factory = sqlite3.Row

sessions = local.execute("SELECT * FROM sessions ORDER BY date").fetchall()
players = local.execute(
    "SELECT sp.*, s.date FROM session_players sp JOIN sessions s ON sp.session_id = s.id ORDER BY s.date, sp.player_name"
).fetchall()
games = local.execute(
    "SELECT sg.*, s.date FROM session_games sg JOIN sessions s ON sg.session_id = s.id ORDER BY s.date, sg.game_number"
).fetchall()
local.close()

print(f"Local: {len(sessions)} sessions, {len(players)} players, {len(games)} games")

# Write to PG
pg = psycopg2.connect(PG_URL)
pg.autocommit = False

def exec_(sql, params=()):
    with pg.cursor() as cur:
        cur.execute(sql, params)

def fetch(sql, params=()):
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

for s in sessions:
    d = dict(s)
    exec_(
        """INSERT INTO sessions (date, day_name, court_hours_court9, court_hours_court10,
            shuttle_price, total_shuttle_cost, total_court_fees, total_amount, player_count, submitted_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (date) DO UPDATE SET
            day_name=EXCLUDED.day_name,
            court_hours_court9=EXCLUDED.court_hours_court9,
            court_hours_court10=EXCLUDED.court_hours_court10,
            shuttle_price=EXCLUDED.shuttle_price,
            total_shuttle_cost=EXCLUDED.total_shuttle_cost,
            total_court_fees=EXCLUDED.total_court_fees,
            total_amount=EXCLUDED.total_amount,
            player_count=EXCLUDED.player_count,
            submitted_at=EXCLUDED.submitted_at""",
        (d["date"], d["day_name"], d["court_hours_court9"], d["court_hours_court10"],
         d["shuttle_price"], d["total_shuttle_cost"], d["total_court_fees"], d["total_amount"],
         d["player_count"], d["submitted_at"])
    )
    print(f"Session {d['date']}: {d['total_amount']} THB")

pid_map = {r["date"]: r["id"] for r in fetch("SELECT id, date FROM sessions")}

for p in players:
    d = dict(p)
    sid = pid_map[d["date"]]
    exec_(
        """INSERT INTO session_players (session_id, player_name, player_type, attended,
            games_played, shuttle_cost, court_fee, total, payment_status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (session_id, player_name) DO UPDATE SET
            player_type=EXCLUDED.player_type, attended=EXCLUDED.attended,
            games_played=EXCLUDED.games_played, shuttle_cost=EXCLUDED.shuttle_cost,
            court_fee=EXCLUDED.court_fee, total=EXCLUDED.total,
            payment_status=EXCLUDED.payment_status""",
        (sid, d["player_name"], d["player_type"], bool(d["attended"]),
         d["games_played"], d["shuttle_cost"], d["court_fee"], d["total"], d["payment_status"])
    )

for g in games:
    d = dict(g)
    sid = pid_map[d["date"]]
    exec_(
        "INSERT INTO session_games (session_id, game_number, players, shuttles) VALUES (%s, %s, %s, %s)",
        (sid, d["game_number"], d["players"], d["shuttles"])
    )

pg.commit()
pg.close()
print("\n✅ Backfill complete!")

# Verify
pg2 = psycopg2.connect(PG_URL)
v = fetch("SELECT date, day_name, total_amount, player_count FROM sessions ORDER BY date")
for r in v:
    print(f"  > {r['date']} ({r['day_name']}): {r['player_count']} players, {r['total_amount']} THB")
print(f"\nSessions: {len(v)}")
pg2.close()
