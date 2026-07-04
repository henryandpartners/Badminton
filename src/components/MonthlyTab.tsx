"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getMonthlySessions,
  MonthlySessionDetail,
  updateSession,
  updateGame,
  deleteGame,
  getShuttlePurchases,
} from "@/lib/db";

function fmtDate(d: string) {
  return new Date(d + "T00:00:00").toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
}

function fmt(n: number) {
  return n.toFixed(0);
}

export default function MonthlyTab() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [sessions, setSessions] = useState<MonthlySessionDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [editingSession, setEditingSession] = useState<number | null>(null);
  const [editGameIds, setEditGameIds] = useState<Record<number, number[]>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await getMonthlySessions(year, month);
      setSessions(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error loading monthly data");
    }
    setLoading(false);
  }, [year, month]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setEditingSession(null);
  };

  const handleEditSession = async (sid: number, field: string, value: number) => {
    await updateSession(sid, { [field]: value });
    load();
  };

  const handleSaveGameShuttles = async (gid: number, shuttles: number) => {
    const ids = editGameIds[gid] || [];
    await updateGame(gid, ids, shuttles);
    setEditingSession(null);
    setEditGameIds({});
    load();
  };

  const handleDeleteGame = async (gid: number) => {
    await deleteGame(gid);
    load();
  };

  // Aggregate
  const totalPlayers = sessions.reduce((s, d) => s + d.attendanceCount, 0);
  const totalGames = sessions.reduce((s, d) => s + d.totalGames, 0);
  const totalShuttles = sessions.reduce((s, d) => s + d.totalShuttlesUsed, 0);
  const totalCourtHrs = sessions.reduce((s, d) => s + d.totalCourtHours, 0);
  const totalRevenue = sessions.reduce((s, d) => s + d.revenue, 0);
  const totalExpense = sessions.reduce((s, d) => s + d.expense, 0);
  const totalCourtRental = sessions.reduce((s, d) => s + d.courtRentalCost, 0);
  const totalShuttleExpense = sessions.reduce((s, d) => s + d.shuttleExpense, 0);
  const totalProfit = sessions.reduce((s, d) => s + d.netProfit, 0);
  const avgCourtRate = totalCourtHrs > 0 ? Math.round(totalCourtRental / totalCourtHrs) : 0;

  // CSV — summary with expenses
  const csvHeader =
    "Date,Sessions,Players,Games,ShuttlesUsed,CourtHours,"
    + "CourtRevenue,ShuttleRevenue,Revenue,"
    + "CourtRentalCost,ShuttleExpense,Expense,NetProfit\n";
  const csvRows = sessions
    .map(
      (d) =>
        `${d.session.session_date},1,${d.attendanceCount},${d.totalGames},${d.totalShuttlesUsed},${d.totalCourtHours},${d.courtRevenue},${d.shuttleRevenue},${d.revenue},${d.courtRentalCost},${d.shuttleExpense},${d.expense},${d.netProfit}`
    )
    .join("\n");
  const csvDetailHeader =
    "Date,Player,GamesPlayed,ShuttleCost,CourtFee,Total,Paid\n";
  const csvDetailRows = sessions
    .flatMap((d) => {
      const courtFee = Number(d.session.court_fee);
      const price = Number(d.session.shuttle_price);
      const shuttleCost: Record<number, number> = {};
      const gamesPlayed: Record<number, number> = {};
      for (const a of d.players) {
        shuttleCost[a.player_id] = 0;
        gamesPlayed[a.player_id] = 0;
      }
      for (const g of d.games) {
        const valid = g.player_ids.filter((p) => p in shuttleCost);
        if (!valid.length) continue;
        const per = (g.shuttles * price) / valid.length;
        for (const p of valid) {
          shuttleCost[p] += per;
          gamesPlayed[p] += 1;
        }
      }
      return d.players.map((a) =>
        [
          d.session.session_date,
          a.name,
          gamesPlayed[a.player_id],
          Math.round(shuttleCost[a.player_id] * 100) / 100,
          courtFee,
          Math.round((courtFee + shuttleCost[a.player_id]) * 100) / 100,
          a.paid ? "Yes" : "No",
        ].join(",")
      );
    })
    .join("\n");

  const downloadCsv = (content: string, filename: string) => {
    const blob = new Blob([content], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  };

  return (
    <div className="space-y-3">
      {/* Month picker */}
      <div className="flex gap-2">
        <input
          type="number"
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          className="input flex-1"
          placeholder="Year"
        />
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="input w-24"
        >
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(0, i).toLocaleString("default", { month: "short" })}
            </option>
          ))}
        </select>
        <button onClick={load} className="btn-primary btn-sm">
          Go
        </button>
      </div>

      {loading && (
        <div className="flex justify-center py-10">
          <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full" />
        </div>
      )}

      {error && <p className="text-red-500 text-sm">{error}</p>}

      {!loading && sessions.length === 0 && (
        <div className="card text-center text-gray-400 py-8">
          <p>No sessions this month.</p>
        </div>
      )}

      {sessions.length > 0 && (
        <>
          {/* Summary metrics — revenue & expenses */}
          <div className="grid grid-cols-2 gap-2">
            <div className="metric-card">
              <p className="text-lg font-bold">{sessions.length}</p>
              <p className="text-[10px] text-gray-500">Sessions</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold">{totalPlayers}</p>
              <p className="text-[10px] text-gray-500">Players</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold">{totalGames}</p>
              <p className="text-[10px] text-gray-500">Games</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold">{totalShuttles}</p>
              <p className="text-[10px] text-gray-500">Shuttles</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold">{totalCourtHrs}</p>
              <p className="text-[10px] text-gray-500">Court-hrs</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold text-green-600">{fmt(totalRevenue)}</p>
              <p className="text-[10px] text-gray-500">Revenue ฿</p>
            </div>
          </div>

          {/* Expenses section */}
          <div className="card">
            <p className="text-xs font-bold mb-2">💰 Expenses</p>
            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">🏟️ Court rental ({totalCourtHrs}h × {avgCourtRate}/hr)</span>
                <span className="font-medium">{fmt(totalCourtRental)} ฿</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">🏸 Shuttle ({totalShuttles} used)</span>
                <span className="font-medium">{fmt(totalShuttleExpense)} ฿</span>
              </div>
              <div className="border-t border-gray-200 pt-1 flex justify-between font-bold">
                <span>Total expense</span>
                <span className="text-red-600">{fmt(totalExpense)} ฿</span>
              </div>
              <div className="flex justify-between text-sm font-bold pt-1 border-t border-gray-200">
                <span>Net profit</span>
                <span className={totalProfit >= 0 ? "text-green-600" : "text-red-600"}>
                  {totalProfit >= 0 ? "+" : ""}{fmt(totalProfit)} ฿
                </span>
              </div>
            </div>
          </div>

          {/* Per-session P&L mini table */}
          <div className="card">
            <p className="text-[10px] text-gray-400 font-medium mb-1">Per session P&amp;L</p>
            <div className="space-y-1 text-xs">
              {sessions.map((d) => (
                <div key={d.session.id} className="flex justify-between items-center">
                  <span className="text-gray-600">{fmtDate(d.session.session_date)}</span>
                  <div className="flex gap-3">
                    <span className="text-green-600">+{fmt(d.revenue)}</span>
                    <span className="text-red-500">−{fmt(d.expense)}</span>
                    <span className={`font-bold ${d.netProfit >= 0 ? "text-green-700" : "text-red-600"}`}>
                      = {d.netProfit >= 0 ? "+" : ""}{fmt(d.netProfit)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Download buttons */}
          <div className="flex gap-2">
            <button
              onClick={() =>
                downloadCsv(csvHeader + csvRows, `monthly_${year}-${String(month).padStart(2, "0")}_summary.csv`)
              }
              className="btn-outline text-xs flex-1"
            >
              ⬇️ Summary CSV
            </button>
            <button
              onClick={() =>
                downloadCsv(csvDetailHeader + csvDetailRows, `monthly_${year}-${String(month).padStart(2, "0")}_details.csv`)
              }
              className="btn-outline text-xs flex-1"
            >
              ⬇️ Details CSV
            </button>
          </div>

          {/* Session list */}
          <div className="space-y-2">
            {sessions.map((d) => {
              const isExpanded = expanded.has(d.session.id);
              const isEditing = editingSession === d.session.id;
              const s = d.session;
              return (
                <div key={s.id} className="card">
                  {/* Session header row */}
                  <button
                    onClick={() => toggleExpand(s.id)}
                    className="w-full flex items-center justify-between text-left"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold">{fmtDate(s.session_date)}</span>
                      <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded-full">
                        {d.attendanceCount} in
                      </span>
                      {d.totalGames > 0 && (
                        <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded-full">
                          {d.totalGames} games
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-medium ${d.netProfit >= 0 ? "text-green-600" : "text-red-500"}`}>
                        {d.netProfit >= 0 ? "+" : ""}{fmt(d.netProfit)}฿
                      </span>
                      <span className="text-xs">{isExpanded ? "▲" : "▼"}</span>
                    </div>
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="mt-3 space-y-2 border-t border-gray-100 pt-2">
                      {/* Editable session fields */}
                      <div className="grid grid-cols-3 gap-1 text-xs">
                        <div>
                          <label className="text-gray-400">Court 9</label>
                          <input
                            type="number"
                            min={0}
                            max={3}
                            value={s.court9_hours}
                            onChange={(e) =>
                              handleEditSession(s.id, "court9_hours", Number(e.target.value))
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-gray-400">Court 10</label>
                          <input
                            type="number"
                            min={0}
                            max={3}
                            value={s.court10_hours}
                            onChange={(e) =>
                              handleEditSession(s.id, "court10_hours", Number(e.target.value))
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-gray-400">Court fee</label>
                          <input
                            type="number"
                            min={0}
                            value={s.court_fee}
                            onChange={(e) =>
                              handleEditSession(s.id, "court_fee", Number(e.target.value))
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-gray-400">Rate/hr</label>
                          <input
                            type="number"
                            min={0}
                            value={s.court_rate}
                            onChange={(e) =>
                              handleEditSession(s.id, "court_rate", Number(e.target.value))
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-gray-400">Shuttle price</label>
                          <input
                            type="number"
                            min={0}
                            value={s.shuttle_price}
                            onChange={(e) =>
                              handleEditSession(s.id, "shuttle_price", Number(e.target.value))
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                        <div>
                          <label className="text-gray-400">Note</label>
                          <input
                            type="text"
                            value={s.note}
                            onChange={(e) =>
                              updateSession(s.id, { note: e.target.value }).then(() => load())
                            }
                            className="input w-full text-xs"
                          />
                        </div>
                      </div>

                      {/* Session P&L stats */}
                      <div className="grid grid-cols-2 gap-1 text-xs bg-gray-50 rounded-lg p-2">
                        <div><span className="text-gray-400">Players: </span>{d.attendanceCount}</div>
                        <div><span className="text-gray-400">Games: </span>{d.totalGames}</div>
                        <div><span className="text-gray-400">Shuttles: </span>{d.totalShuttlesUsed}</div>
                        <div><span className="text-gray-400">Court hrs: </span>{d.totalCourtHours}</div>
                        <div className="text-green-600"><span className="text-gray-400">Revenue: </span>+{fmt(d.revenue)}฿</div>
                        <div className="text-red-500"><span className="text-gray-400">Expense: </span>−{fmt(d.expense)}฿</div>
                        <div className="col-span-2 font-bold">
                          <span className="text-gray-400">Net: </span>
                          <span className={d.netProfit >= 0 ? "text-green-600" : "text-red-600"}>
                            {d.netProfit >= 0 ? "+" : ""}{fmt(d.netProfit)}฿
                          </span>
                        </div>
                      </div>

                      {/* Expense breakdown */}
                      <div className="text-xs bg-red-50 rounded-lg p-2">
                        <p className="text-[10px] text-gray-500 font-medium mb-1">💰 Expense breakdown</p>
                        <div className="flex justify-between">
                          <span className="text-gray-500">Court rental ({d.totalCourtHours}h × {s.court_rate}/hr)</span>
                          <span>{fmt(d.courtRentalCost)} ฿</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-500">Shuttle ({d.totalShuttlesUsed} used)</span>
                          <span>{fmt(d.shuttleExpense)} ฿</span>
                        </div>
                      </div>

                      {/* Players list */}
                      {d.players.length > 0 && (
                        <div>
                          <p className="text-[10px] text-gray-400 font-medium mb-1">Players checked in</p>
                          <div className="flex flex-wrap gap-1">
                            {d.players.map((a) => (
                              <span
                                key={a.player_id}
                                className="text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded-full"
                              >
                                {a.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Games list */}
                      {d.games.length > 0 && (
                        <div>
                          <p className="text-[10px] text-gray-400 font-medium mb-1">Games</p>
                          <div className="space-y-1">
                            {d.games.map((g) => (
                              <div
                                key={g.id}
                                className="flex items-center justify-between bg-gray-50 rounded-lg px-2 py-1"
                              >
                                {isEditing ? (
                                  <div className="flex items-center gap-1 w-full">
                                    <span className="text-xs font-medium w-10">G{g.game_no}</span>
                                    <div className="flex flex-wrap gap-0.5 flex-1">
                                      {d.players.map((a) => {
                                        const selected = (editGameIds[g.id] || g.player_ids).includes(a.player_id);
                                        return (
                                          <button
                                            key={a.player_id}
                                            onClick={() => {
                                              setEditGameIds((prev) => {
                                                const ids = prev[g.id] || [...g.player_ids];
                                                const next = selected
                                                  ? ids.filter((id) => id !== a.player_id)
                                                  : [...ids, a.player_id];
                                                return { ...prev, [g.id]: next };
                                              });
                                            }}
                                            className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                                              selected
                                                ? "bg-green-600 text-white"
                                                : "bg-white border border-gray-200 text-gray-500"
                                            }`}
                                          >
                                            {a.name}
                                          </button>
                                        );
                                      })}
                                    </div>
                                    <input
                                      type="number"
                                      min={1}
                                      value={
                                        editGameIds[g.id]
                                          ? g.shuttles
                                          : g.shuttles
                                      }
                                      onChange={(e) => {
                                        setEditingSession(s.id);
                                        setEditGameIds((prev) => ({
                                          ...prev,
                                          [g.id]: prev[g.id] || [...g.player_ids],
                                        }));
                                        handleSaveGameShuttles(g.id, Number(e.target.value));
                                      }}
                                      className="input w-14 text-xs text-center"
                                    />
                                    <span className="text-[10px] text-gray-400">shuttles</span>
                                    <button
                                      onClick={() => handleDeleteGame(g.id)}
                                      className="text-red-400 text-xs ml-1"
                                    >
                                      ✕
                                    </button>
                                  </div>
                                ) : (
                                  <>
                                    <div className="flex items-center gap-2">
                                      <span className="text-xs font-medium">G{g.game_no}</span>
                                      <div className="flex flex-wrap gap-0.5">
                                        {g.player_ids
                                          .map((pid) => d.players.find((a) => a.player_id === pid))
                                          .filter(Boolean)
                                          .map((a) => (
                                            <span
                                              key={a!.player_id}
                                              className="text-[10px] bg-white border border-gray-200 px-1.5 py-0.5 rounded-full"
                                            >
                                              {a!.name}
                                            </span>
                                          ))}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <span className="text-xs text-gray-500">{g.shuttles} 🏸</span>
                                    </div>
                                  </>
                                )}
                              </div>
                            ))}
                          </div>
                          {/* Edit toggle */}
                          <div className="flex gap-2 mt-1">
                            <button
                              onClick={() => {
                                if (isEditing) {
                                  setEditingSession(null);
                                  setEditGameIds({});
                                } else {
                                  setEditingSession(s.id);
                                }
                              }}
                              className="text-xs text-green-600 font-medium"
                            >
                              {isEditing ? "✅ Done editing" : "✏️ Edit games"}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
