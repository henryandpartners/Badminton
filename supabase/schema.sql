-- Badminton Tracker schema for Supabase
-- Run this in Supabase SQL Editor: https://app.supabase.com

-- Players
CREATE TABLE IF NOT EXISTS bt_players (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    is_guest BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Sessions (one per date)
CREATE TABLE IF NOT EXISTS bt_sessions (
    id SERIAL PRIMARY KEY,
    session_date DATE NOT NULL UNIQUE,
    court9_hours INTEGER NOT NULL DEFAULT 0,
    court10_hours INTEGER NOT NULL DEFAULT 0,
    court_rate FLOAT NOT NULL DEFAULT 160.0,
    court_fee FLOAT NOT NULL DEFAULT 80.0,
    shuttle_price FLOAT NOT NULL DEFAULT 100.0,
    note VARCHAR(500) DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Attendance / check-in
CREATE TABLE IF NOT EXISTS bt_attendance (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES bt_sessions(id),
    player_id INTEGER NOT NULL REFERENCES bt_players(id),
    paid BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_attendance UNIQUE (session_id, player_id)
);

-- Games
CREATE TABLE IF NOT EXISTS bt_games (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES bt_sessions(id),
    game_no INTEGER NOT NULL,
    shuttles INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Game players (many-to-many)
CREATE TABLE IF NOT EXISTS bt_game_players (
    id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES bt_games(id),
    player_id INTEGER NOT NULL REFERENCES bt_players(id),
    CONSTRAINT uq_game_player UNIQUE (game_id, player_id)
);

-- Shuttle purchases
CREATE TABLE IF NOT EXISTS bt_shuttle_purchases (
    id SERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    quantity INTEGER NOT NULL,
    unit_cost FLOAT NOT NULL,
    note VARCHAR(300) DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed players
INSERT INTO bt_players (name, is_guest, active)
VALUES
    ('โรจน์', FALSE, TRUE),
    ('น้อย', FALSE, TRUE),
    ('ภูมี', FALSE, TRUE),
    ('ป๊อป ภู', FALSE, TRUE),
    ('คะน้า', FALSE, TRUE),
    ('จืด', FALSE, TRUE),
    ('เกียรติ', FALSE, TRUE),
    ('อองรี', FALSE, TRUE),
    ('ป๊อป', FALSE, TRUE),
    ('น้อต', FALSE, TRUE),
    ('ต้น', FALSE, TRUE),
    ('ทรัมป', FALSE, TRUE)
ON CONFLICT (name) DO NOTHING;

-- Enable RLS (optional — public app, no auth needed)
ALTER TABLE bt_players ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_games ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_game_players ENABLE ROW LEVEL SECURITY;
ALTER TABLE bt_shuttle_purchases ENABLE ROW LEVEL SECURITY;

-- Public access policies (no auth for this app)
CREATE POLICY "Enable all for anon" ON bt_players FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for anon" ON bt_sessions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for anon" ON bt_attendance FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for anon" ON bt_games FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for anon" ON bt_game_players FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for anon" ON bt_shuttle_purchases FOR ALL USING (true) WITH CHECK (true);
