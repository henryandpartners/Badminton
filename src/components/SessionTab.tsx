"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getPlayers,
  getOrCreateSession,
  getSession,
  updateSession,
  getAttendance,
  checkIn,
  checkOut,
  getGames,
  addGame,
  updateGame,
  deleteGame,
  addPlayer,
  Player,
  Session,
  AttendanceRow,
  GameRow,
  COURTS,
} from "@/lib/db";

interface Props {
  date: string;
  onDateChange: (d: string) => void;
}

export default function SessionTab({ date, onDateChange }: Props) {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [attendance, setAttendance] = useState<AttendanceRow[]>([]);
  const [games, setGames_] = useState<GameRow[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [newName, setNewName] = useState("");
  const [newGuest, setNewGuest] = useState(true);
  const [newGamePlayerIds, setNewGamePlayerIds] = useState<number[]>([]);
  const [newGameShuttles, setNewGameShuttles] = useState(1);
  const [editGame, setEditGame] = useState<Record<number, { playerIds: number[]; shuttles: number }>>({});
  const [showAddGame, setShowAddGame] = useState(false);
  const [showAddPlayer, setShowAddPlayer] = useState(false);
  const [loading, setLoading] = useState(true);

  const idToName = Object.fromEntries(players.map((p) => [p.id, p.name]));
  const nameToId = Object.fromEntries(players.map((p) => [p.name, p.id]));

  const load = useCallback(async () => {
    // Timeout fetch after 10s
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    try {
      const sid = await getOrCreateSession(date);
      setSessionId(sid);
      const [sess, att, gms, ps] = await Promise.all([
        getSession(sid),
        getAttendance(sid),
        getGames(sid),
        getPlayers(true),
      ]);
      setSession(sess);
      setAttendance(att);
      setGames_(gms);
      setPlayers(ps);
    } catch (e) {
      console.error("Failed to load session:", e);
    } finally {
      clearTimeout(timeoutId);
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    const [sess, att, gms] = await Promise.all([
      getSession(sessionId),
      getAttendance(sessionId),
      getGames(sessionId),
    ]);
    setSession(sess);
    setAttendance(att);
    setGames_(gms);
  }, [sessionId]);

  const togglePlayer = async (pid: number, checked: boolean) => {
    if (!sessionId) return;
    if (checked) await checkIn(sessionId, pid);
    else await checkOut(sessionId, pid);
    await reload();
  };

  const handleAddGame = async () => {
    if (!sessionId || !newGamePlayerIds.length) return;
    await addGame(sessionId, newGamePlayerIds, newGameShuttles);
    setNewGamePlayerIds([]);
    setNewGameShuttles(1);
    setShowAddGame(false);
    await reload();
  };

  const handleUpdateGame = async (gid: number) => {
    if (!sessionId) return;
    const eg = editGame[gid];
    if (!eg) return;
    await updateGame(gid, eg.playerIds, eg.shuttles);
    reload();
  };

  const handleDeleteGame = async (gid: number) => {
    if (!sessionId) return;
    await deleteGame(gid);
    reload();
  };

  const handleAddPlayer = async () => {
    if (!newName.trim() || !sessionId) return;
    const pid = await addPlayer(newName, newGuest);
    if (pid) {
      await checkIn(sessionId, pid);
      setNewName("");
      setNewGuest(true);
      setShowAddPlayer(false);
      const ps = await getPlayers(true);
      setPlayers(ps);
      await reload();
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!session) return <p className="text-center text-gray-500 py-10">No session data</p>;

  const checkedIds = new Set(attendance.map((a) => a.player_id));
  const courtFields = { "9": "court9_hours", "10": "court10_hours" } as const;
  const totalCourtHours = session.court9_hours + session.court10_hours;

  return (
    <div className="space-y-3">
      {/* Date picker */}
      <input
        type="date"
        value={date}
        onChange={(e) => onDateChange(e.target.value)}
        className="input text-center font-bold"
      />

      {/* Court hours */}
      <div className="card">
        <p className="text-sm font-bold mb-2">🏟️ Courts & Hours</p>
        <p className="text-xs text-gray-500 mb-2">{session.court_rate} THB/hr (venue cost)</p>
        <div className="flex gap-3 mb-2">
          {COURTS.map((c) => (
            <div key={c} className="flex-1 text-center">
              <p className="text-xs font-medium mb-1">Court {c}</p>
              <div className="flex justify-center gap-1">
                {[0, 1, 2, 3, 4].map((h) => (
                  <button
                    key={h}
                    onClick={async () => {
                      await updateSession(sessionId!, { [courtFields[c]]: h });
                      reload();
                    }}
                    className={`btn-sm ${session[courtFields[c]] === h ? "bg-green-600 text-white" : "bg-gray-100 text-gray-600"}`}
                  >
                    {h}
                  </button>
                ))}
              </div>
              <p className="text-xs text-gray-400 mt-1">hrs</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500">
          {totalCourtHours} court-hr → {(totalCourtHours * session.court_rate).toFixed(0)} THB
        </p>
      </div>

      {/* Check-in */}
      <div className="card">
        <div className="flex justify-between items-center mb-2">
          <p className="text-sm font-bold">✅ Check-in</p>
          <span className="text-xs font-bold bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
            {checkedIds.size} in
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1">
          {players.map((p) => {
            const isChecked = checkedIds.has(p.id);
            return (
              <button
                key={p.id}
                onClick={() => togglePlayer(p.id, !isChecked)}
                className={`flex items-center gap-2 py-2.5 px-3 rounded-lg text-left w-full active:scale-[0.97] transition-transform ${
                  isChecked ? "bg-green-50 border border-green-200" : "bg-gray-50 border border-gray-100"
                }`}
              >
                <span
                  className={`w-5 h-5 rounded-full border-2 flex items-center justify-center text-xs shrink-0 ${
                    isChecked
                      ? "bg-green-600 border-green-600 text-white"
                      : "border-gray-300"
                  }`}
                >
                  {isChecked ? "✓" : ""}
                </span>
                <span className="text-sm font-medium">{p.name}{p.is_guest ? " 👤" : ""}</span>
              </button>
            );
          })}
        </div>
        <button
          onClick={() => setShowAddPlayer(!showAddPlayer)}
          className="text-green-600 text-xs font-medium mt-2"
        >
          + Add player
        </button>
        {showAddPlayer && (
          <div className="mt-2 flex gap-2">
            <input
              className="input flex-1"
              placeholder="Name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddPlayer()}
            />
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={newGuest}
                onChange={(e) => setNewGuest(e.target.checked)}
                className="w-3 h-3 accent-green-600"
              />
              Guest
            </label>
            <button onClick={handleAddPlayer} className="btn-primary btn-sm">
              Add
            </button>
          </div>
        )}
      </div>

      {/* Games */}
      <div className="card">
        <div className="flex justify-between items-center mb-2">
          <p className="text-sm font-bold">🎮 Games</p>
          {checkedIds.size > 0 && (
            <button
              onClick={() => setShowAddGame(!showAddGame)}
              className="btn-primary btn-sm text-xs"
            >
              + Game
            </button>
          )}
        </div>

        {checkedIds.size === 0 && (
          <p className="text-xs text-gray-400">Check players in first</p>
        )}

        {showAddGame && (
          <div className="bg-gray-50 rounded-lg p-3 mb-2 space-y-2">
            <p className="text-xs font-medium">New Game</p>
            <div className="flex flex-wrap gap-1">
              {attendance.map((a) => (
                <button
                  key={a.player_id}
                  onClick={() =>
                    setNewGamePlayerIds((prev) =>
                      prev.includes(a.player_id)
                        ? prev.filter((id) => id !== a.player_id)
                        : [...prev, a.player_id]
                    )
                  }
                  className={`text-xs px-2 py-1 rounded-full border ${
                    newGamePlayerIds.includes(a.player_id)
                      ? "bg-green-600 text-white border-green-600"
                      : "bg-white border-gray-300 text-gray-600"
                  }`}
                >
                  {a.name}
                </button>
              ))}
            </div>
            <div className="flex gap-2 items-end">
              <div>
                <label className="text-[10px] text-gray-400">Shuttles</label>
                <input
                  type="number"
                  min={0}
                  value={newGameShuttles}
                  onChange={(e) => setNewGameShuttles(Number(e.target.value))}
                  className="input w-16"
                />
              </div>
              <button onClick={handleAddGame} className="btn-primary btn-sm">
                Add
              </button>
            </div>
          </div>
        )}

        {games.map((g) => {
          const eg = editGame[g.id] || { playerIds: [...g.player_ids], shuttles: g.shuttles };
          const presentNames = attendance.map((a) => a.name);
          return (
            <div key={g.id} className="bg-gray-50 rounded-lg p-3 mb-2 last:mb-0">
              <div className="flex justify-between items-center mb-1">
                <p className="text-xs font-bold">Game {g.game_no}</p>
                <button
                  onClick={() => handleDeleteGame(g.id)}
                  className="text-red-500 text-xs"
                >
                  ✕
                </button>
              </div>

              {/* Display mode or edit mode? */}
              <div className="flex flex-wrap gap-1 mb-2">
                {g.player_ids.map((pid) => (
                  <span key={pid} className="text-xs bg-white border border-gray-200 px-2 py-0.5 rounded-full">
                    {idToName[pid] || pid}
                  </span>
                ))}
              </div>

              <div className="flex gap-2 items-end">
                <div>
                  <label className="text-[10px] text-gray-400">Players</label>
                  <select
                    multiple
                    value={eg.playerIds.map(String)}
                    onChange={(e) => {
                      const selected = Array.from(e.target.selectedOptions, (o) => Number(o.value));
                      setEditGame((prev) => ({
                        ...prev,
                        [g.id]: { ...eg, playerIds: selected },
                      }));
                    }}
                    className="input text-xs h-20"
                  >
                    {presentNames.map((n) => (
                      <option key={nameToId[n]} value={nameToId[n]}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-400">Shuttles</label>
                  <input
                    type="number"
                    min={0}
                    value={eg.shuttles}
                    onChange={(e) =>
                      setEditGame((prev) => ({
                        ...prev,
                        [g.id]: { ...eg, shuttles: Number(e.target.value) },
                      }))
                    }
                    className="input w-16"
                  />
                </div>
                <button
                  onClick={() => handleUpdateGame(g.id)}
                  className="btn-primary btn-sm text-xs"
                >
                  Save
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
