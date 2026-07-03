"use client";

import { useEffect, useState, useCallback } from "react";
import SessionTab from "@/components/SessionTab";
import DailyTab from "@/components/DailyTab";
import MonthlyTab from "@/components/MonthlyTab";
import ShuttlesTab from "@/components/ShuttlesTab";
import PlayersTab from "@/components/PlayersTab";
import { createClient } from "@/lib/supabase/client";

const TABS = ["Session", "Daily", "Monthly", "Shuttles", "Players"] as const;
type Tab = (typeof TABS)[number];

export default function Home() {
  const [tab, setTab] = useState<Tab>("Session");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [dbReady, setDbReady] = useState(false);
  const [dbError, setDbError] = useState("");

  const initDb = useCallback(async () => {
    try {
      const sb = createClient();
      const { error } = await sb.from("bt_players").select("count", { count: "exact", head: true });
      if (error) throw error;
      setDbReady(true);
    } catch (e: unknown) {
      setDbError(e instanceof Error ? e.message : "Cannot reach database");
    }
  }, []);

  useEffect(() => {
    initDb();
  }, [initDb]);

  if (!dbReady) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        {dbError ? (
          <>
            <span className="text-4xl">⚠️</span>
            <p className="text-lg font-bold text-red-600">Cannot reach database</p>
            <p className="text-sm text-gray-500 text-center">{dbError}</p>
            <p className="text-xs text-gray-400 text-center max-w-xs">
              Make sure the Supabase schema is set up. Run <code className="bg-gray-200 px-1 rounded">supabase/schema.sql</code> in the Supabase SQL Editor.
            </p>
            <button className="btn-primary" onClick={() => window.location.reload()}>
              Retry
            </button>
          </>
        ) : (
          <>
            <div className="animate-spin w-8 h-8 border-4 border-green-600 border-t-transparent rounded-full" />
            <p className="text-sm text-gray-500">Connecting to database...</p>
          </>
        )}
      </div>
    );
  }

  return (
    <>
      {tab === "Session" && <SessionTab date={date} onDateChange={setDate} />}
      {tab === "Daily" && <DailyTab date={date} onDateChange={setDate} />}
      {tab === "Monthly" && <MonthlyTab />}
      {tab === "Shuttles" && <ShuttlesTab />}
      {tab === "Players" && <PlayersTab />}

      {/* Bottom nav — mobile-optimized fixed tabs */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-gray-200 flex shadow-lg max-w-lg mx-auto">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`tab ${tab === t ? "tab-active" : ""}`}
          >
            {t === "Session" && "📋"}
            {t === "Daily" && "💰"}
            {t === "Monthly" && "📊"}
            {t === "Shuttles" && "🏸"}
            {t === "Players" && "👥"}
            <span className="block text-[10px]">{t}</span>
          </button>
        ))}
      </nav>
    </>
  );
}
