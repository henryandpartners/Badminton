/**
 * Data layer — Supabase client queries.
 * All queries use the Supabase JS client so they work in Server Components,
 * Server Actions, and Route Handlers.
 */

import { createClient } from "./supabase/client";

// --- Defaults ----------------------------------------------------------------
export const DEFAULT_COURT_FEE = 80.0;
export const DEFAULT_COURT_RATE = 160.0;
export const DEFAULT_SHUTTLE_PRICE = 100.0;
export const COURTS = ["9", "10"] as const;

export const SEED_PLAYERS = [
  "โรจน์", "น้อย", "ภูมี", "ป๊อป ภู", "คะน้า", "จืด",
  "เกียรติ", "อองรี", "ป๊อป", "น้อต", "ต้น", "ทรัมป",
];

// --- Types -------------------------------------------------------------------
export interface Player {
  id: number;
  name: string;
  is_guest: boolean;
  active: boolean;
}

export interface Session {
  id: number;
  session_date: string;
  court9_hours: number;
  court10_hours: number;
  court_rate: number;
  court_fee: number;
  shuttle_price: number;
  note: string;
}

export interface AttendanceRow {
  player_id: number;
  name: string;
  is_guest: boolean;
  paid: boolean;
}

export interface GameRow {
  id: number;
  game_no: number;
  shuttles: number;
  player_ids: number[];
}

export interface ShuttlePurchase {
  id: number;
  purchase_date: string;
  quantity: number;
  unit_cost: number;
  note: string;
}

export interface DailySplitRow {
  Player: string;
  GamesPlayed: number;
  ShuttleCost: number;
  CourtFee: number;
  Total: number;
  Paid: boolean;
}

// --- Players -----------------------------------------------------------------
export async function getPlayers(activeOnly = true): Promise<Player[]> {
  const sb = createClient();
  let q = sb.from("bt_players").select("*").order("id");
  if (activeOnly) q = q.eq("active", true);
  const { data } = await q;
  return (data || []) as Player[];
}

export async function addPlayer(name: string, isGuest = false): Promise<number | null> {
  const sb = createClient();
  const trimmed = name.trim();
  if (!trimmed) return null;

  // Check existing
  const { data: existing } = await sb.from("bt_players").select("id").eq("name", trimmed).single();
  if (existing) return existing.id;

  const { data } = await sb.from("bt_players").insert({ name: trimmed, is_guest: isGuest, active: true }).select("id").single();
  return data?.id ?? null;
}

// --- Sessions ----------------------------------------------------------------
export async function getOrCreateSession(date: string): Promise<number> {
  const sb = createClient();
  const { data } = await sb.from("bt_sessions").select("id").eq("session_date", date).maybeSingle();
  if (data) return data.id;
  const { data: created } = await sb.from("bt_sessions").insert({ session_date: date }).select("id").single();
  return created!.id;
}

export async function getSession(sessionId: number): Promise<Session | null> {
  const sb = createClient();
  const { data } = await sb.from("bt_sessions").select("*").eq("id", sessionId).maybeSingle();
  return data as Session | null;
}

export async function updateSession(sessionId: number, fields: Record<string, unknown>) {
  const sb = createClient();
  await sb.from("bt_sessions").update(fields).eq("id", sessionId);
}

// --- Attendance --------------------------------------------------------------
export async function checkIn(sessionId: number, playerId: number) {
  const sb = createClient();
  const { data } = await sb.from("bt_attendance").select("id").eq("session_id", sessionId).eq("player_id", playerId).maybeSingle();
  if (!data) {
    await sb.from("bt_attendance").insert({ session_id: sessionId, player_id: playerId, paid: false });
  }
}

export async function checkOut(sessionId: number, playerId: number) {
  const sb = createClient();
  // Remove from games in this session
  const { data: games } = await sb.from("bt_games").select("id").eq("session_id", sessionId);
  if (games) {
    const gids = games.map((g: { id: number }) => g.id);
    if (gids.length) {
      await sb.from("bt_game_players").delete().eq("player_id", playerId).in("game_id", gids);
    }
  }
  await sb.from("bt_attendance").delete().eq("session_id", sessionId).eq("player_id", playerId);
}

export async function setPaid(sessionId: number, playerId: number, paid: boolean) {
  const sb = createClient();
  await sb.from("bt_attendance").update({ paid }).eq("session_id", sessionId).eq("player_id", playerId);
}

export async function getAttendance(sessionId: number): Promise<AttendanceRow[]> {
  const sb = createClient();
  const { data } = await sb
    .from("bt_attendance")
    .select("player_id, bt_players!inner(name, is_guest), paid")
    .eq("session_id", sessionId)
    .order("name", { foreignTable: "bt_players" });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (data || []).map((r: any) => ({
    player_id: r.player_id,
    name: Array.isArray(r.bt_players) ? r.bt_players[0]?.name : r.bt_players?.name,
    is_guest: Array.isArray(r.bt_players) ? r.bt_players[0]?.is_guest : r.bt_players?.is_guest,
    paid: r.paid,
  })) as AttendanceRow[];
}

// --- Games -------------------------------------------------------------------
export async function addGame(sessionId: number, playerIds: number[], shuttles = 1): Promise<number> {
  const sb = createClient();
  // Get next game_no
  const { data: last } = await sb.from("bt_games").select("game_no").eq("session_id", sessionId).order("game_no", { ascending: false }).limit(1).single();
  const nextNo = (last?.game_no ?? 0) + 1;

  const { data } = await sb.from("bt_games").insert({ session_id: sessionId, game_no: nextNo, shuttles }).select("id").single();
  const gid = data!.id;

  if (playerIds.length) {
    await sb.from("bt_game_players").insert(playerIds.map((pid) => ({ game_id: gid, player_id: pid })));
  }
  return gid;
}

export async function updateGame(gameId: number, playerIds: number[], shuttles: number) {
  const sb = createClient();
  await sb.from("bt_games").update({ shuttles }).eq("id", gameId);
  await sb.from("bt_game_players").delete().eq("game_id", gameId);
  if (playerIds.length) {
    await sb.from("bt_game_players").insert(playerIds.map((pid) => ({ game_id: gameId, player_id: pid })));
  }
}

export async function deleteGame(gameId: number) {
  const sb = createClient();
  await sb.from("bt_game_players").delete().eq("game_id", gameId);
  await sb.from("bt_games").delete().eq("id", gameId);
}

export async function getGames(sessionId: number): Promise<GameRow[]> {
  const sb = createClient();
  const { data: games } = await sb.from("bt_games").select("*").eq("session_id", sessionId).order("game_no");

  if (!games) return [];

  const result: GameRow[] = [];
  for (const g of games) {
    const { data: gps } = await sb.from("bt_game_players").select("player_id").eq("game_id", g.id);
    result.push({
      id: g.id,
      game_no: g.game_no,
      shuttles: g.shuttles,
      player_ids: (gps || []).map((gp: { player_id: number }) => gp.player_id),
    });
  }
  return result;
}

// --- Shuttle purchases -------------------------------------------------------
export async function addShuttlePurchase(date: string, quantity: number, unitCost: number, note = "") {
  const sb = createClient();
  await sb.from("bt_shuttle_purchases").insert({ purchase_date: date, quantity, unit_cost: unitCost, note });
}

export async function getShuttlePurchases(): Promise<ShuttlePurchase[]> {
  const sb = createClient();
  const { data } = await sb.from("bt_shuttle_purchases").select("*").order("purchase_date");
  return (data || []) as ShuttlePurchase[];
}

// --- Calculations ------------------------------------------------------------
export async function computeDailySplit(sessionId: number): Promise<DailySplitRow[]> {
  const sess = await getSession(sessionId);
  if (!sess) return [];

  const courtFee = Number(sess.court_fee);
  const price = Number(sess.shuttle_price);
  const att = await getAttendance(sessionId);
  if (!att.length) return [];

  const shuttleCost: Record<number, number> = {};
  const gamesPlayed: Record<number, number> = {};
  for (const a of att) {
    shuttleCost[a.player_id] = 0;
    gamesPlayed[a.player_id] = 0;
  }

  const games = await getGames(sessionId);
  for (const g of games) {
    const valid = g.player_ids.filter((p) => p in shuttleCost);
    if (!valid.length) continue;
    const per = (g.shuttles * price) / valid.length;
    for (const p of valid) {
      shuttleCost[p] += per;
      gamesPlayed[p] += 1;
    }
  }

  return att.map((a) => ({
    Player: a.name,
    GamesPlayed: gamesPlayed[a.player_id],
    ShuttleCost: Math.round(shuttleCost[a.player_id] * 100) / 100,
    CourtFee: courtFee,
    Total: Math.round((courtFee + shuttleCost[a.player_id]) * 100) / 100,
    Paid: a.paid,
  }));
}

export async function monthlySummary(year: number, month: number) {
  const sb = createClient();
  const start = `${year}-${String(month).padStart(2, "0")}-01`;
  const endMonth = month === 12 ? 1 : month + 1;
  const endYear = month === 12 ? year + 1 : year;
  const end = `${endYear}-${String(endMonth).padStart(2, "0")}-01`;

  const { data: srows } = await sb.from("bt_sessions").select("*").gte("session_date", start).lt("session_date", end);
  if (!srows) return null;

  const sessions = srows as Session[];
  const sessionIds = sessions.map((s) => s.id);
  const totalCourtHours = sessions.reduce((sum, s) => sum + s.court9_hours + s.court10_hours, 0);
  const courtRentalCost = sessions.reduce((sum, s) => sum + (s.court9_hours + s.court10_hours) * s.court_rate, 0);

  let courtRevenue = 0;
  let shuttleRevenue = 0;
  let nAtt = 0;
  for (const sid of sessionIds) {
    const df = await computeDailySplit(sid);
    courtRevenue += df.reduce((s, r) => s + r.CourtFee, 0);
    shuttleRevenue += df.reduce((s, r) => s + r.ShuttleCost, 0);
    nAtt += df.length;
  }

  const purch = await getShuttlePurchases();
  let shuttlesBought = 0;
  let shuttlePurchaseCost = 0;
  for (const p of purch) {
    if (p.purchase_date >= start && p.purchase_date < end) {
      shuttlesBought += p.quantity;
      shuttlePurchaseCost += p.quantity * p.unit_cost;
    }
  }

  const totalRevenue = courtRevenue + shuttleRevenue;
  const totalCost = courtRentalCost + shuttlePurchaseCost;
  return {
    sessions: sessions.length,
    attendances: nAtt,
    total_court_hours: totalCourtHours,
    court_rental_cost: Math.round(courtRentalCost * 100) / 100,
    shuttles_bought: shuttlesBought,
    shuttle_purchase_cost: Math.round(shuttlePurchaseCost * 100) / 100,
    court_revenue: Math.round(courtRevenue * 100) / 100,
    shuttle_revenue: Math.round(shuttleRevenue * 100) / 100,
    total_revenue: Math.round(totalRevenue * 100) / 100,
    total_cost: Math.round(totalCost * 100) / 100,
    net: Math.round((totalRevenue - totalCost) * 100) / 100,
  };
}
