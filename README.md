# House Tour Notes

Real-time, multi-party house-hunting notes app. See `PROJECT_BRIEF.md` for spec.

## Layout

- `/backend` — FastAPI + uv. Deployed to Railway.
- `/frontend` — Next.js 15 App Router + TypeScript. Deployed to Vercel.
- `/supabase/migrations` — SQL migrations. Paste into the Supabase SQL editor.

## Local dev

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
```

Both apps need env vars — see `.env.example` in each folder.
