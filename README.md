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

## Quick Start (Local Development)

### 1. Setup

```bash
cd CobroF

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

Then open http://localhost:8000 in your browser.

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
cd CobroF

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
5. **Share link** - Click "Copiar Link para Participantes" to share with friends
6. **Generate payment links** - Click "Generar Links de Pago" when ready

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | API status and config |
| `/api/create-bill` | POST | Create empty bill |
| `/api/scan-bill` | POST | Upload and scan a receipt |
| `/api/bill/{id}` | GET | Get bill details |
| `/api/add-person` | POST | Add a person |
| `/api/remove-person` | POST | Remove a person |
| `/api/assign-item` | POST | Assign/unassign person to item |
| `/api/update-tip-tax` | POST | Update tip and tax |
| `/api/add-item` | POST | Manually add an item |
| `/api/update-title` | POST | Update bill title |
| `/api/calculate-splits/{id}` | GET | Calculate splits and payment links |
| `/api/bill/{id}/participant` | GET | Get bill for participant view |
| `/api/bill/{id}/join` | POST | Join a bill as participant |
| `/api/bill/{id}/self-assign` | POST | Self-assign items |

## Configuration

### Fintoc Username

Edit `FINTOC_USERNAME` in `main.py` to your Fintoc username for payment links.

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
