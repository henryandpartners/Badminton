"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getOrCreateSession,
  computeDailySplit,
  setPaid,
  getPlayers,
  Player,
  DailySplitRow,
} from "@/lib/db";

interface Props {
  date: string;
  onDateChange: (d: string) => void;
}

export default function DailyTab({ date, onDateChange }: Props) {
  const [split, setSplit] = useState<DailySplitRow[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);

  const nameToId = Object.fromEntries(players.map((p) => [p.name, p.id]));

  const load = useCallback(async () => {
    setLoading(true);
    const [sid, ps] = await Promise.all([getOrCreateSession(date), getPlayers(false)]);
    setPlayers(ps);
    const s = await computeDailySplit(sid);
    setSplit(s);
    setLoading(false);
  }, [date]);

  useEffect(() => {
    load();
  }, [load]);

  const togglePaid = async (row: DailySplitRow) => {
    const sid = await getOrCreateSession(date);
    const pid = nameToId[row.Player];
    if (!pid) return;
    await setPaid(sid, pid, !row.Paid);
    load();
  };

  const total = split.reduce((s, r) => s + r.Total, 0);
  const paid = split.filter((r) => r.Paid).reduce((s, r) => s + r.Total, 0);

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <input
        type="date"
        value={date}
        onChange={(e) => onDateChange(e.target.value)}
        className="input text-center font-bold"
      />

      {split.length === 0 ? (
        <div className="card text-center text-gray-400 py-8">
          <p>No check-ins for this date.</p>
          <p className="text-xs mt-1">Go to Session tab to check players in.</p>
        </div>
      ) : (
        <>
          {/* Metrics */}
          <div className="grid grid-cols-4 gap-2">
            <div className="metric-card">
              <p className="text-lg font-bold">{split.length}</p>
              <p className="text-[10px] text-gray-500">Players</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold">{total.toFixed(0)}</p>
              <p className="text-[10px] text-gray-500">Due</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold text-green-600">{paid.toFixed(0)}</p>
              <p className="text-[10px] text-gray-500">Collected</p>
            </div>
            <div className="metric-card">
              <p className="text-lg font-bold text-red-500">{(total - paid).toFixed(0)}</p>
              <p className="text-[10px] text-gray-500">Pending</p>
            </div>
          </div>

          {/* Player breakdown */}
          <div className="space-y-2">
            {split.map((row) => (
              <div key={row.Player} className="card flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{row.Player}</p>
                  <p className="text-xs text-gray-400">
                    {row.GamesPlayed} games · court {row.CourtFee.toFixed(0)} · shuttle {row.ShuttleCost.toFixed(0)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold">{row.Total.toFixed(0)} ฿</span>
                  <label className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={row.Paid}
                      onChange={() => togglePaid(row)}
                      className="w-4 h-4 accent-green-600"
                    />
                    <span className="text-xs text-gray-500">Paid</span>
                  </label>
                </div>
              </div>
            ))}
          </div>

          {/* Export */}
          <button
            onClick={() => {
              const csv =
                "Player,GamesPlayed,ShuttleCost,CourtFee,Total,Paid\n" +
                split
                  .map(
                    (r) =>
                      `${r.Player},${r.GamesPlayed},${r.ShuttleCost},${r.CourtFee},${r.Total},${r.Paid}`
                  )
                  .join("\n");
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `daily_${date}.csv`;
              a.click();
            }}
            className="btn-outline w-full text-sm"
          >
            ⬇️ Export CSV
          </button>
        </>
      )}
    </div>
  );
}
