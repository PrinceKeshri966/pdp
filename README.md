# PDP-DEV (OptiPDP)

AI Commerce Optimization — FastAPI backend + React UI (`frontend/index.html`), Google sign-in, Neon PostgreSQL.

**Live stack:** Render (app + frontend on one URL) · Neon (Postgres) · Google OAuth · Anthropic Claude

---

## Local run

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # fill keys locally — never commit .env
venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Open http://localhost:8000

---

## GitHub

```bash
git clone https://github.com/PrinceKeshri966/PDP-DEV.git
cd PDP-DEV
```

---

## Deploy on Render (backend + frontend together)

> **Note:** This project serves the UI from FastAPI at `/`. You do **not** need Vercel for the frontend. One Render Web Service hosts everything (like a single full-stack app).

### Before you have a Render URL

1. Push this repo to GitHub (see above).
2. In [Render](https://render.com) → **New +** → **Web Service** → connect **PrinceKeshri966/PDP-DEV**.
3. Settings:
   - **Root Directory:** (leave empty if repo root is this project)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health check path:** `/health`
4. Add **Environment Variables** (Render dashboard → Environment):

| Key | Value |
|-----|--------|
| `DATABASE_URL` | Neon URL with `postgresql+asyncpg://...?ssl=require` |
| `SECRET_KEY` | Long random string |
| `ANTHROPIC_API_KEY` | Your Anthropic key |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | `https://YOUR-SERVICE.onrender.com/api/v1/auth/google/callback` *(set after first deploy)* |
| `APP_BASE_URL` | `https://YOUR-SERVICE.onrender.com` |
| `ALLOWED_ORIGINS` | `https://YOUR-SERVICE.onrender.com` |
| `DEV_AUTH_BYPASS` | `false` |
| `APP_ENV` | `production` |
| `DEBUG` | `false` |

5. Click **Create Web Service** and wait for the first deploy.

### After you get the Render URL (e.g. `https://pdp-dev-xxxx.onrender.com`)

1. Update on Render: `APP_BASE_URL`, `GOOGLE_REDIRECT_URI`, `ALLOWED_ORIGINS` with that URL.
2. **Google Cloud Console** → OAuth client → add:
   - **Authorized redirect URI:** `https://pdp-dev-xxxx.onrender.com/api/v1/auth/google/callback`
   - **Authorized JavaScript origin:** `https://pdp-dev-xxxx.onrender.com`
3. **Redeploy** Render (or it will pick up env changes automatically).
4. Open your Render URL → **Continue with Google** → home page with your Google name.

### Tables on Neon

Tables are created automatically on startup (`init_db`). Expected tables: `tenants`, `users`, `analysis_reports`, `blueprints`.

```bash
set PYTHONPATH=.
venv\Scripts\python.exe scripts\check_tables.py
```

---

## Environment template

Copy `.env.example` to `.env` for local development. **Never commit `.env`.**

---

## API

- `GET /` — Frontend UI  
- `GET /health` — Health check  
- `GET /api/v1/config` — Auth config for UI  
- `GET /api/v1/auth/google/login` — Start Google sign-in  
- `POST /api/v1/analyze/pdp` — Mode 1 analysis  

Docs (dev only): `/docs`
