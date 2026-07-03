# 🏸 Badminton Tracker — Next.js + Supabase

Mobile-first app for tracking badminton court costs, games, and player splits.

## Tech Stack
- **Next.js 16** (App Router, TypeScript)
- **Supabase** (PostgreSQL)
- **Tailwind CSS** (mobile-first)
- **Vercel** (deploy)

## Quick Deploy

### 1. Supabase Setup
Run `supabase/schema.sql` in the Supabase SQL Editor:
1. Go to [supabase.com](https://supabase.com) → your project → SQL Editor
2. Paste and run the schema
3. Copy your **Project URL** and **anon key**

### 2. Vercel Deploy
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/henryandpartners/Badminton&branch=nextjs)

Add env vars:
```
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
```

Or deploy manually:
```bash
npm install
npm run build
```

### 3. Local Dev
```bash
cp .env.local.example .env.local
# Edit .env.local with your Supabase URL + anon key
npm install
npm run dev
# Open http://localhost:3000
```

## Features
- **Session** — Court hours, check-in, games
- **Daily** — Per-player cost split, paid tracking
- **Monthly** — Revenue/cost summary
- **Shuttles** — Purchase tracking
- **Players** — Roster management

## Branch
- `nextjs` — Next.js version (current)
- `claude/badminton-tracker-streamlit-ljgyh5` — Python/NiceGUI (legacy)
