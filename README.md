# 🏸 Badminton Team Tracker

A mobile-optimised **Streamlit** web app for tracking on-court badminton
sessions. It uses a **Google Sheet as the live backend** (read/write via
`st-gsheets-connection`), generates **PromptPay QR codes** for collecting
payment, and reconciles **bank-transfer slips** by reading the amount off the
photo with **local OCR (Tesseract)** — no third-party API or keys required.

Designed thumb-first: big high-contrast buttons and toggle chips that work on a
phone browser court-side.

---

## Features

| View | What it does |
|------|--------------|
| 🏟️ **Live Tracker** | Toggle player attendance, giant ➕/➖ shuttle counter, court-fee input, live running total. |
| 🧾 **Ledger & QR** | Splits the bill `(Court Fee + Shuttles × Price) ÷ Present players`, writes each player's row back to the Sheet, and renders a per-player PromptPay QR for the exact amount. |
| 📥 **Slip Verify** | Drag-and-drop a JPG/PNG slip → OCR reads the amount → it's matched to the player who owes it → you confirm → their row flips `Pending → Paid`. Includes a manual-reconcile fallback. |

---

## Google Sheet schema

Create two worksheets (tabs) in your sheet.

**`Players`**

| Name | PromptPayID |
|------|-------------|
| Som  | 0812345678  |
| Nok  | 0898765432  |

`PromptPayID` is a Thai mobile number or a 13-digit national/tax ID.

**`Ledger`** (the app creates/overwrites rows here)

| Date | Player | Present | ShuttlesUsed | ShuttlePrice | CourtFee | AmountDue | PaymentStatus |
|------|--------|---------|--------------|--------------|----------|-----------|---------------|

> Share the Sheet with your service account's `client_email` (Editor access).

---

## Setup

```bash
pip install -r requirements.txt

# Configure secrets (copy the template and fill in real values)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#   → paste your Google service-account JSON fields (slip OCR needs no keys)

streamlit run app.py
```

On **Streamlit Community Cloud**, paste the contents of
`secrets.toml.example` (filled in) into **App → Settings → Secrets** instead of
committing a file.

The real `.streamlit/secrets.toml` is git-ignored — only the `.example`
template is tracked.

---

## How the split works

```
Individual Due = (Total Court Fee + (Shuttles Used × Shuttle Unit Price))
                 ─────────────────────────────────────────────────────────
                              Count of Checked-In Players
```

Locking the totals writes one `Ledger` row per present player for that date.
Re-locking the same date is idempotent (it replaces that date's rows).
