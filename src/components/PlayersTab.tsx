"use client";

import { useEffect, useState } from "react";
import { getPlayers, addPlayer, Player } from "@/lib/db";

export default function PlayersTab() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [isGuest, setIsGuest] = useState(false);

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

      {/* Active players */}
      <div>
        <p className="text-sm font-bold text-green-600 mb-2">Active ({active.length})</p>
        <div className="space-y-1">
          {active.map((p) => (
            <div key={p.id} className="card flex justify-between items-center py-2.5">
              <span className="text-sm">
                {p.name}
                {p.is_guest ? <span className="text-xs text-gray-400 ml-1">👤 guest</span> : null}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Inactive */}
      {inactive.length > 0 && (
        <div>
          <p className="text-sm font-bold text-gray-400 mb-2">Inactive ({inactive.length})</p>
          <div className="space-y-1 opacity-50">
            {inactive.map((p) => (
              <div key={p.id} className="card flex justify-between items-center py-2.5">
                <span className="text-sm">{p.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
