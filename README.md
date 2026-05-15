# Divvy 💸

A beautiful bill-splitting app that scans receipts, lets you assign items to people, and generates Fintoc payment links.

## Features

- 📸 **Smart Receipt Scanning** - Uses Google Gemini (free!) or OpenAI Vision to extract items
- 👥 **Easy Person Management** - Add people with just their names
- 🎯 **Item Assignment** - Drag & drop or click to assign who had what
- 💰 **Tax & Tip Splitting** - Proportionally divides extras among participants
- 🔗 **Fintoc Payment Links** - Generate instant payment links for each person
- 📱 **Participant View** - Share a link so friends can self-assign items
- 💾 **Persistent Storage** - Bills survive restarts (Turso DB or local file)
- **Host and participant links** - Each bill has a secret host edit URL (`/edit/...`, redirects to `/app?bill=...` and sets a host cookie) and a participant URL (`/b/...`); optional email magic-link sign-in lists bills you have claimed

## Quick Start (Local Development)

### 1. Setup

```bash
cd divvy-app

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy env.example.txt to .env
cp env.example.txt .env

# Edit .env and add your Gemini API key
# Get one free at: https://aistudio.google.com/app/apikey
```

### 3. Run

```bash
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000 for the landing page. The host dashboard is at http://localhost:8000/app (magic-link sign-in completes there too).

---

## 🚀 Deploy to Production (Free!)

Deploy to **Fly.io** with **Turso** database for $0/month.

### Prerequisites

1. [Fly.io CLI](https://fly.io/docs/hands-on/install-flyctl/) installed
2. [Turso CLI](https://docs.turso.tech/cli/installation) installed
3. A Gemini API key (free at https://aistudio.google.com/app/apikey)

### Step 1: Create Turso Database

```bash
# Login to Turso
turso auth login

# Create database
turso db create divvy-bills

# Get the database URL
turso db show divvy-bills --url
# Copy the URL (looks like: libsql://divvy-bills-yourname.turso.io)

# Create auth token
turso db tokens create divvy-bills
# Copy the token
```

### Step 2: Deploy to Fly.io

```bash
cd divvy-app

# Login to Fly.io
fly auth login

# Launch app (first time only)
fly launch --no-deploy

# Set your secrets
fly secrets set GEMINI_API_KEY=your_gemini_key_here
fly secrets set TURSO_DATABASE_URL=libsql://divvy-bills-yourname.turso.io
fly secrets set TURSO_AUTH_TOKEN=your_turso_token_here

# Deploy!
fly deploy
```

### Step 3: Open Your App

```bash
fly open
```

Your app is now live at `https://divvy-bills.fly.dev` (or your chosen name)!

---

## Usage

1. **Start a bill** - Upload a receipt photo OR add items manually
2. **Add people** - Enter names of everyone splitting the bill
3. **Assign items** - Drag people to items or click 👤 to assign
4. **Set extras** - Update tax/tip percentages if needed
5. **Share link** - Copy the participant link (`/b/...`) for friends; keep your host edit link (`/edit/...`) private (opens the app at `/app` with that bill)
6. **Generate payment links** - Click "Generar Links de Pago" when ready

## API Endpoints (selected)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | API status and config |
| `/api/me` | GET | Current session (optional account) |
| `/api/me/bills` | GET | Bills owned by signed-in user |
| `/api/auth/request-magic-link` | POST | Email magic link (JSON `{ "email" }`) |
| `/api/auth/callback` | GET | Completes magic link sign-in |
| `/api/create-bill` | POST | Create empty bill (returns `host_token`, `participant_token`, URLs) |
| `/api/scan-bill` | POST | Upload and scan a receipt |
| `/api/bill/{id}` | GET | Get bill (host: `Authorization: Bearer <host_token>` or host cookie) |
| `/api/p/t/{token}` | GET | Participant bill payload |
| `/api/p/t/{token}/join` | POST | Join as participant |
| `/api/p/t/{token}/self-assign` | POST | Self-assign items |
| `/api/add-person` | POST | Add a person (host) |
| `/api/calculate-splits/{id}` | GET | Splits (host) |

See route modules under `app/routers/` for the full set.

## Configuration

### Site URLs (local and production)

- **`/`** — Marketing-style landing (static).
- **`/app`** — Host dashboard (upload, edit bills).
- **`/login`** — Magic-link sign-in and logout.
- **`BASE_URL`** — Must be the public origin users open in the browser (for example `https://your-app.fly.dev`). It is embedded in magic-link emails; if it is wrong, the link opens the wrong host or path.

### Email sign-in (Resend)

Magic links are sent with the [Resend](https://resend.com) HTTP API (`POST https://api.resend.com/emails`). There is no other mail backend configured in this repo.

1. Create a Resend account and verify a sending domain (or use their test sender while developing).
2. Create an API key and set **`MAIL_API_KEY`** in `.env` (and in Fly secrets for production).
3. Set **`MAIL_FROM`** to an address on your verified domain (Resend shows the exact format they expect).
4. Set **`BASE_URL`** to the same scheme + host users will use when they click the link (include the port in local dev if you are not on port 80), for example `http://localhost:8000` or `https://divvy-bills.fly.dev`.
5. Include that origin in **`ALLOWED_ORIGINS`** (comma-separated) so the browser can call the API with cookies.

If `MAIL_API_KEY` or `MAIL_FROM` is missing, `POST /api/auth/request-magic-link` returns **503** with a clear error.

### Fintoc Username

Set `FINTOC_USERNAME` in `.env`, or per-bill in the UI (stored on the bill).

### OCR Engines (priority order)

1. **OpenAI Vision** - If `OPENAI_API_KEY` is set
2. **Google Gemini** - If `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set (recommended - free!)
3. **Tesseract** - Local fallback (no API key needed, less accurate)

### Storage Modes

- **Turso** - If `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are set
- **Local JSON** - Falls back to `data/bills.json` for local dev

## Tech Stack

- **Backend**: Python FastAPI
- **OCR**: Google Gemini (free) / OpenAI Vision / Tesseract
- **Database**: Turso (libsql) / Local JSON
- **Frontend**: Vanilla HTML/CSS/JS
- **Payments**: Fintoc payment links
- **Hosting**: Fly.io (free tier)

## License

MIT
