"use client";

import { useEffect, useState } from "react";
import { getShuttlePurchases, addShuttlePurchase, ShuttlePurchase } from "@/lib/db";

type PurchWithTotal = ShuttlePurchase & { total: number };

export default function ShuttlesTab() {
  const [purchases, setPurchases] = useState<PurchWithTotal[]>([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [quantity, setQuantity] = useState(12);
  const [unitCost, setUnitCost] = useState(100);
  const [note, setNote] = useState("");

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
        {purchases.length === 0 ? (
          <p className="text-center text-gray-400 py-8 text-sm">No purchases yet</p>
        ) : (
          purchases.map((p) => (
            <div key={p.id} className="card flex justify-between items-center">
              <div>
                <p className="text-sm font-medium">{p.purchase_date}</p>
                <p className="text-xs text-gray-400">
                  {p.quantity} × {p.unit_cost}฿ {p.note ? `· ${p.note}` : ""}
                </p>
              </div>
              <span className="text-sm font-bold">{p.total} ฿</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
