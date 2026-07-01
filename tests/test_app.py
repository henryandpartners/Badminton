"""Tests for the database-backed badminton tracker (SQLite in a temp file)."""

import datetime as dt
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_db(tmp_path, monkeypatch):
    """Point the data layer at a throwaway SQLite file and reload it."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    import db as _db
    importlib.reload(_db)
    _db._engine = None  # ensure the new URL is picked up
    _db.init_db()
    return _db


def test_seed_and_daily_split(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert len(db.get_players()) == len(db.SEED_PLAYERS)

    sid = db.get_or_create_session(dt.date(2026, 7, 1))
    db.update_session(sid, court9_hours=3, court10_hours=3)
    ids = {r["name"]: int(r["id"]) for _, r in db.get_players().iterrows()}
    four = ["โรจน์", "น้อย", "ภูมี", "คะน้า"]
    for n in four:
        db.check_in(sid, ids[n])
    db.add_game(sid, [ids[n] for n in four], shuttles=1)  # 100/4 = 25 each

    split = db.compute_daily_split(sid)
    assert len(split) == 4
    assert set(split["CourtFee"]) == {80.0}
    assert set(split["ShuttleCost"]) == {25.0}
    assert set(split["Total"]) == {105.0}


def test_monthly_summary(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    sid = db.get_or_create_session(dt.date(2026, 7, 6))
    db.update_session(sid, court9_hours=3, court10_hours=3)  # 6h × 155 = 930
    ids = {r["name"]: int(r["id"]) for _, r in db.get_players().iterrows()}
    for n in ["โรจน์", "น้อย"]:
        db.check_in(sid, ids[n])
    db.add_shuttle_purchase(dt.date(2026, 7, 1), 12, 100.0)

    s = db.monthly_summary(2026, 7)
    assert s["total_court_hours"] == 6
    assert s["court_rental_cost"] == 930.0
    assert s["court_revenue"] == 160.0  # 2 players × 80
    assert s["shuttles_bought"] == 12
    assert s["shuttle_purchase_cost"] == 1200.0


def test_edit_and_remove_game(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    sid = db.get_or_create_session(dt.date(2026, 7, 8))
    ids = {r["name"]: int(r["id"]) for _, r in db.get_players().iterrows()}
    for n in ["โรจน์", "น้อย", "ภูมี", "คะน้า"]:
        db.check_in(sid, ids[n])
    gid = db.add_game(sid, [ids["โรจน์"], ids["น้อย"]], shuttles=1)
    # edit: change players + shuttles
    db.update_game(gid, [ids["ภูมี"], ids["คะน้า"]], shuttles=2)
    g = db.get_games(sid)[0]
    assert g["shuttles"] == 2
    assert set(g["player_ids"]) == {ids["ภูมี"], ids["คะน้า"]}
    db.delete_game(gid)
    assert db.get_games(sid) == []
