"use client";

import { useState, useCallback } from "react";
import SessionTab from "@/components/SessionTab";
import DailyTab from "@/components/DailyTab";
import MonthlyTab from "@/components/MonthlyTab";
import ShuttlesTab from "@/components/ShuttlesTab";
import PlayersTab from "@/components/PlayersTab";

const TABS = ["Session", "Daily", "Monthly", "Shuttles", "Players"] as const;
type Tab = (typeof TABS)[number];

export default function Home() {
  const [tab, setTab] = useState<Tab>("Session");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));

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
