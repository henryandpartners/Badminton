"use client";

import { useState, useEffect } from "react";
import { monthlySummary } from "@/lib/db";

export default function MonthlyTab() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [data, setData] = useState<Awaited<ReturnType<typeof monthlySummary>>>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const d = await monthlySummary(year, month);
      setData(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error loading monthly data");
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-3">
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

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="metric-card">
              <p className="text-xl font-bold">{data.sessions}</p>
              <p className="text-[10px] text-gray-500">Sessions</p>
            </div>
            <div className="metric-card">
              <p className="text-xl font-bold">{data.total_court_hours}</p>
              <p className="text-[10px] text-gray-500">Court-hrs</p>
            </div>
            <div className="metric-card">
              <p className="text-xl font-bold">{data.total_revenue.toFixed(0)}</p>
              <p className="text-[10px] text-gray-500">Revenue</p>
            </div>
            <div className="metric-card">
              <p className="text-xl font-bold">{data.net.toFixed(0)}</p>
              <p className="text-[10px] text-gray-500">Net</p>
            </div>
          </div>

          <div className="card">
            <p className="text-xs text-gray-500 space-y-1">
              <span className="block">🟢 Court rental: {data.court_rental_cost.toFixed(0)} · Court fees: {data.court_revenue.toFixed(0)}</span>
              <span className="block">🏸 Shuttles bought: {data.shuttles_bought} → {data.shuttle_purchase_cost.toFixed(0)} · Fees: {data.shuttle_revenue.toFixed(0)}</span>
            </p>
          </div>
        </>
      )}

      {data && data.sessions === 0 && !loading && (
        <div className="card text-center text-gray-400 py-8">
          <p>No sessions this month.</p>
        </div>
      )}
    </div>
  );
}
