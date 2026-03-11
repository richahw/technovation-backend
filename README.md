# Scheduling Platform — FastAPI + PostgreSQL Backend

A working backend example for the Technovation × Delta Consulting scheduling project.
Demonstrates the two core FastAPI jobs for our MVP:
1. **Storing OAuth tokens** from Google into Postgres
2. **Serving coach/participant data** and booking records

---

## What's in here

```
scheduling-backend/
├── README.md
├── requirements.txt        ← install these first
├── .env.example            ← copy to .env and fill in your DB URL
└── app/
    ├── main.py             ← FastAPI app entry point (all routes)
    ├── database.py         ← Postgres connection setup (SQLAlchemy)
    ├── models.py           ← Database table definitions
    ├── schemas.py          ← Request/response shapes (Pydantic)
    └── seed.py             ← Populate DB with sample data to test
```

---

## Setup (do this once)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create a Postgres database
You can use [Railway](https://railway.app), [Supabase](https://supabase.com), or local Postgres.

If using local Postgres:
```bash
psql -U postgres
CREATE DATABASE scheduling_db;
\q
```

### 3. Set your database URL
```bash
cp .env.example .env
# Edit .env and set your DATABASE_URL
```

### 4. Run the server
```bash
uvicorn app.main:app --reload
```

### 5. Seed with sample data (optional)
```bash
python app/seed.py
```

### 6. Open the interactive API docs
Visit: **http://localhost:8000/docs**

FastAPI auto-generates interactive docs — you can test every endpoint right there in the browser.

---

## Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| GET | `/` | Health check |
| POST | `/auth/google/callback` | Receives Google OAuth token → saves to DB |
| GET | `/coaches` | List all coaches |
| POST | `/coaches` | Create a new coach |
| GET | `/coaches/{id}` | Get one coach by ID |
| GET | `/coaches/{id}/availability` | Get a coach's available slots from Cal.com (stubbed) |
| GET | `/participants` | List all participants |
| POST | `/participants` | Create a new participant |
| POST | `/bookings` | Create a booking (writes to DB + stubs Cal.com call) |
| GET | `/bookings` | List all bookings |
| GET | `/bookings/{id}` | Get one booking |

---

## Why each piece matters for our project

**FastAPI** handles every HTTP request — from the chatbot sending a booking intent,
to Google sending back an OAuth token, to Cal.com webhooks notifying us of cancellations.

**SQLAlchemy** is the ORM (Object Relational Mapper) — it lets us write Python instead
of raw SQL to talk to Postgres. E.g. `db.query(Coach).all()` instead of `SELECT * FROM coaches`.

**Pydantic schemas** validate all incoming data automatically. If the chatbot sends a
booking request missing a required field, FastAPI rejects it with a clear error before
it ever touches the database.

**Postgres** stores everything that needs to persist: coach profiles, participant records,
booking history, and — critically — OAuth tokens so users don't have to re-authenticate
every time.

---

## Deploying to Render (free tier)

### 1. Push your code to GitHub
```bash
git init
git add .
git commit -m "initial backend"
# create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/scheduling-backend.git
git push -u origin main
```

### 2. Create a Render web service
1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Runtime**: Python
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - (The Procfile handles this automatically)

### 3. Add environment variables in Render dashboard
Under your service → **Environment** → add:
- `DATABASE_URL` — your Supabase connection string
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- Leave `GOOGLE_REDIRECT_URI` blank — Render sets `RENDER_EXTERNAL_HOSTNAME` automatically

### 4. Add your live URL to Google Cloud Console
Once deployed, Render gives you a URL like `https://scheduling-backend-xxxx.onrender.com`.
Go to Google Cloud Console → Credentials → your OAuth client → add:
```
https://scheduling-backend-xxxx.onrender.com/auth/google/callback
```
as an **Authorized redirect URI**.

### 5. Done!
Your API is live at `https://scheduling-backend-xxxx.onrender.com`
Docs at `https://scheduling-backend-xxxx.onrender.com/docs`
