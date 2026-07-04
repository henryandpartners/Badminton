"use client";

import { useEffect, useState } from "react";
import {
  getShuttlePurchases,
  addShuttlePurchase,
  updateShuttlePurchase,
  deleteShuttlePurchase,
  ShuttlePurchase,
} from "@/lib/db";

type PurchWithTotal = ShuttlePurchase & { total: number };
type EditingRow = {
  id: number;
  purchase_date: string;
  quantity: number;
  unit_cost: number;
  note: string;
};

export default function ShuttlesTab() {
  const [purchases, setPurchases] = useState<PurchWithTotal[]>([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [quantity, setQuantity] = useState(12);
  const [unitCost, setUnitCost] = useState(100);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<EditingRow | null>(null);

  const load = async () => {
    setLoading(true);
    const p = await getShuttlePurchases();
    setPurchases(p.map((r) => ({ ...r, total: r.quantity * r.unit_cost })));
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const handleAdd = async () => {
    await addShuttlePurchase(date, quantity, unitCost, note);
    setNote("");
    load();
  };

  const handleSaveEdit = async () => {
    if (!editing) return;
    await updateShuttlePurchase(editing.id, {
      purchase_date: editing.purchase_date,
      quantity: editing.quantity,
      unit_cost: editing.unit_cost,
      note: editing.note,
    });
    setEditing(null);
    load();
  };

  const handleCancelEdit = () => setEditing(null);

  const handleDelete = async (id: number) => {
    await deleteShuttlePurchase(id);
    load();
  };

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <div className="animate-spin w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Add form */}
      <div className="card space-y-2">
        <p className="text-sm font-bold">🛒 Record Purchase</p>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="input" />
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-[10px] text-gray-400">Qty</label>
            <input
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(Number(e.target.value))}
              className="input"
            />
          </div>
          <div className="flex-1">
            <label className="text-[10px] text-gray-400">Unit cost</label>
            <input
              type="number"
              min={0}
              value={unitCost}
              onChange={(e) => setUnitCost(Number(e.target.value))}
              className="input"
            />
          </div>
        </div>
        <input
          placeholder="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="input"
        />
        <button onClick={handleAdd} className="btn-primary w-full">
          Record
        </button>
      </div>

      {/* Purchase history */}
      <div className="space-y-2">
        <p className="text-sm font-bold">📋 Purchase History</p>
        {purchases.length === 0 ? (
          <p className="text-center text-gray-400 py-8 text-sm">No purchases yet</p>
        ) : (
          purchases.map((p) => {
            const isEditing = editing?.id === p.id;
            return (
              <div key={p.id} className="card">
                {isEditing ? (
                  <div className="space-y-2">
                    <input
                      type="date"
                      value={editing.purchase_date}
                      onChange={(e) => setEditing({ ...editing, purchase_date: e.target.value })}
                      className="input text-xs"
                    />
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label className="text-[10px] text-gray-400">Qty</label>
                        <input
                          type="number"
                          min={1}
                          value={editing.quantity}
                          onChange={(e) => setEditing({ ...editing, quantity: Number(e.target.value) })}
                          className="input text-xs"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-[10px] text-gray-400">Unit cost</label>
                        <input
                          type="number"
                          min={0}
                          value={editing.unit_cost}
                          onChange={(e) => setEditing({ ...editing, unit_cost: Number(e.target.value) })}
                          className="input text-xs"
                        />
                      </div>
                    </div>
                    <input
                      placeholder="Note"
                      value={editing.note}
                      onChange={(e) => setEditing({ ...editing, note: e.target.value })}
                      className="input text-xs"
                    />
                    <div className="flex gap-2">
                      <button onClick={handleSaveEdit} className="btn-primary btn-sm flex-1 text-xs">
                        💾 Save
                      </button>
                      <button onClick={handleCancelEdit} className="btn-outline btn-sm flex-1 text-xs">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <p className="text-sm font-medium">{p.purchase_date}</p>
                      <p className="text-xs text-gray-400">
                        {p.quantity} × {p.unit_cost}฿ {p.note ? `· ${p.note}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold">{p.total} ฿</span>
                      <div className="flex flex-col gap-0.5">
                        <button
                          onClick={() =>
                            setEditing({
                              id: p.id,
                              purchase_date: p.purchase_date,
                              quantity: p.quantity,
                              unit_cost: p.unit_cost,
                              note: p.note,
                            })
                          }
                          className="text-[10px] text-green-600 font-medium leading-none"
                        >
                          ✏️
                        </button>
                        <button
                          onClick={() => handleDelete(p.id)}
                          className="text-[10px] text-red-400 font-medium leading-none"
                        >
                          🗑️
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
