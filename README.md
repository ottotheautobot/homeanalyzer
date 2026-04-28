# House Tour Notes

Real-time, multi-party house-hunting notes app.

## Docs

- `CONTEXT.md` — current project posture (start here)
- `BACKLOG.md` — what's not yet shipped, by priority
- `CHANGELOG.md` — what's already shipped, by version
- `DECISIONS_LOG.md` — strategic decisions and the reasoning
- `PROJECT_BRIEF.md` — original v1 launch plan (historical record)
- `OPERATIONS.md` — credentials and config touchpoints across systems

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
