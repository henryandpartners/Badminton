"use client";

import { useEffect, useState } from "react";
import { getPlayers, addPlayer, togglePlayerActive, Player } from "@/lib/db";

type Tab = "active" | "inactive";

export default function PlayersTab() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [isGuest, setIsGuest] = useState(false);
  const [tab, setTab] = useState<Tab>("active");

  const load = async () => {
    setLoading(true);
    setPlayers(await getPlayers(false));
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const handleAdd = async () => {
    if (!newName.trim()) return;
    await addPlayer(newName, isGuest);
    setNewName("");
    setIsGuest(false);
    load();
  };

  const handleToggle = async (p: Player) => {
    await togglePlayerActive(p.id, !p.active);
    load();
  };

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  const active = players.filter((p) => p.active);
  const inactive = players.filter((p) => !p.active);

  return (
    <div className="space-y-3">
      {/* Add form */}
      <div className="card">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="New player name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={isGuest}
              onChange={(e) => setIsGuest(e.target.checked)}
              className="w-3 h-3 accent-green-600"
            />
            Guest
          </label>
          <button onClick={handleAdd} className="btn-primary btn-sm">
            Add
          </button>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-gray-700">
        <button
          onClick={() => setTab("active")}
          className={`px-3 py-1.5 text-xs font-semibold rounded-t transition-colors ${
            tab === "active"
              ? "bg-green-700 text-white"
              : "text-gray-400 hover:text-white"
          }`}
        >
          Active ({active.length})
        </button>
        <button
          onClick={() => setTab("inactive")}
          className={`px-3 py-1.5 text-xs font-semibold rounded-t transition-colors ${
            tab === "inactive"
              ? "bg-gray-600 text-white"
              : "text-gray-400 hover:text-white"
          }`}
        >
          Inactive ({inactive.length})
        </button>
      </div>

      {/* Player list */}
      {tab === "active" ? (
        <div className="space-y-1">
          {active.length === 0 && (
            <p className="text-xs text-gray-500 text-center py-4">No active players</p>
          )}
          {active.map((p) => (
            <div key={p.id} className="card flex justify-between items-center py-2.5">
              <span className="text-sm">
                {p.name}
                {p.is_guest ? <span className="text-xs text-gray-400 ml-1">👤 guest</span> : null}
              </span>
              <button
                onClick={() => handleToggle(p)}
                className="text-xs text-gray-400 hover:text-yellow-400 transition-colors"
                title="Deactivate"
              >
                Deactivate
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-1">
          {inactive.length === 0 && (
            <p className="text-xs text-gray-500 text-center py-4">No inactive players</p>
          )}
          {inactive.map((p) => (
            <div key={p.id} className="card flex justify-between items-center py-2.5 opacity-60">
              <span className="text-sm">{p.name}</span>
              <button
                onClick={() => handleToggle(p)}
                className="text-xs text-green-500 hover:text-green-400 transition-colors"
                title="Reactivate"
              >
                Reactivate
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
