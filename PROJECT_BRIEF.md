# Project Brief — House Tour Notes (v2)

> **All architectural decisions are locked. Claude Code should not propose alternatives to anything in the "Locked decisions" section without explicit user instruction. Build to spec.**

## Vision

A real-time, multi-party house-hunting notes app. During an in-person home tour, the buyer carries an iPhone (chest-mounted) on a Zoom call. A transcription bot joins silently, streams transcript to a backend, and an LLM continuously extracts structured observations (layout notes, hazards, agent quotes, partner reactions) into a shared workspace. The buyer's partner can join the Zoom from anywhere and watch notes fill in live. After all tours, the app produces per-house summaries and supports natural-language comparison across houses.

The wedge: most real estate tech is built for agents. This is built for the buyer/renter making a high-stakes decision across multiple properties — especially valuable for out-of-state moves and family relocations.

## Target user (MVP)

The builder, his wife, and his buyer's agent — touring 10 rental homes in Fort Lauderdale, FL within ~1 week. If it works, productize for relocation buyers more broadly.

## Locked decisions

| Concern | Decision |
|---|---|
| Backend hosting | Railway, $5/mo Hobby plan, GitHub-connected auto-deploy |
| Frontend hosting | Vercel, free tier, GitHub-connected auto-deploy |
| Database / Auth / Realtime / Storage | Supabase (all four) |
| Backend framework | Python + FastAPI, dependencies via `uv` |
| Frontend framework | Next.js 15 App Router, TypeScript strict mode |
| UI library | Tailwind + shadcn/ui |
| Client state | RSC for server data, Supabase Realtime for live updates, TanStack Query for client mutations |
| Mobile delivery | Responsive web app + PWA (manifest + service worker, "Add to Home Screen") |
| Auth pattern | Supabase magic-link + email-invite-to-tour |
| Meeting bot provider | **Meeting BaaS** (not Recall — Recall requires business email; deferred to v2 with custom domain) |
| Bot abstraction | Implement a `MeetingProvider` interface; Meeting BaaS is the only concrete impl in v1; Recall implementation deferred |
| Zoom plan | Free tier (40-min meeting cap acceptable; no single house tour exceeds 20 min) |
| Zoom meeting model | Personal Meeting Room (PMR), URL configured once in app, reused per tour |
| Recording capture | Zoom handles audio; bot captures audio + video via Meeting BaaS |
| Real-time transcription | Meeting BaaS bundled transcription ($0.69/hr all-in) |
| Streaming extraction LLM | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| Synthesis LLM | Claude Sonnet 4.6 (`claude-sonnet-4-6`) |
| Prompt caching | **Mandatory** on extraction prompt prefix (system + tools + few-shot examples). Use `cache_control: {"type": "ephemeral"}` on stable blocks. 5-min TTL default. |
| Extraction strategy | Real-time chunked. Process every 60s of accumulated transcript OR on user "next room" event. |
| Comparison view | Stuff all house briefs into Sonnet 4.6 context (200K window). No RAG, no vector DB. |
| Observability | Sentry on both backend and frontend, day 1 |
| Privacy | 90-day audio auto-delete; RLS on every table; simple privacy page |
| Webhook security | HMAC signature verification on every Meeting BaaS webhook |
| Idempotency | Webhook handler must dedupe on `(bot_id, start_seconds)` natural key |
| In-app recording | **Out of scope.** Zoom captures audio. App is for control + viewing observations. |
| Custom domain | Out of scope (v2 backlog) |
| GitHub Actions CI | Out of scope (v2 backlog) |
| Native iOS app | Out of scope (v2 backlog) |

## Data model

Seven tables. Resist over-modeling.

```sql
users (id, email, name, role)
  -- role: 'buyer' | 'partner' | 'agent' (display only)

tours (id, owner_user_id, name, location, zoom_pmr_url,
       created_at, status)
  -- status: 'planning' | 'active' | 'completed'
  -- zoom_pmr_url stored on tour for reuse across houses

tour_participants (tour_id, user_id, role, invited_at, joined_at)
  -- many-to-many; controls visibility/edit access via RLS

tour_invites (id, tour_id, email, role, token, expires_at, accepted_at)
  -- magic-link invite flow target

houses (id, tour_id, address, list_price, sqft, beds, baths,
        listing_url, scheduled_at, status, overall_score,
        overall_notes, bot_id, audio_url, video_url, synthesis_md)
  -- status: 'upcoming' | 'touring' | 'completed'
  -- bot_id is the Meeting BaaS bot ID for active tours
  -- audio_url, video_url populated post-tour from Meeting BaaS recording
  -- synthesis_md is the final Sonnet brief in markdown

observations (id, house_id, user_id, room, category, content,
              severity, source, created_at, recall_timestamp)
  -- category: 'layout' | 'condition' | 'hazard' | 'positive'
  --         | 'concern' | 'agent_said' | 'partner_said'
  -- source:   'manual' | 'transcript' | 'photo_analysis'
  -- severity: null | 'info' | 'warn' | 'critical'
  -- recall_timestamp: seconds into the meeting
  -- (column name kept generic for v2 swap to Recall)

transcripts (id, house_id, bot_id, speaker, text,
             start_seconds, end_seconds, processed)
  -- raw chunks from Meeting BaaS
  -- processed: bool, flips when LLM extraction runs
  -- UNIQUE INDEX on (bot_id, start_seconds) for idempotency
```

The `observations` table is the unified core. Every UI view derives from it. Manual notes, transcript-derived notes, future photo-vision-derived notes all share the same shape.

## Data flow (end-to-end)

1. **Tour starts.** User taps "Start tour at [address]" in app. Backend calls `MeetingProvider.start_bot(zoom_url, webhook_url)` (Meeting BaaS impl), stores returned `bot_id` on the house row, sets `houses.status = 'touring'`, returns the Zoom PMR URL to the frontend.
2. **People join Zoom.** Buyer joins from iPhone Zoom mobile (rear camera, chest rig). Partner joins from anywhere. Bot joins silently. Buyer ignores the web app from this point.
3. **Transcript chunks arrive.** Meeting BaaS POSTs to `/webhooks/meetingbaas/transcript` per utterance. Handler verifies HMAC signature, dedupes on `(bot_id, start_seconds)`, writes chunk to `transcripts` table, enqueues a FastAPI BackgroundTask for LLM processing, returns 200 in <500ms.
4. **Milestone processing.** Extraction fires on either: (a) every 60s of accumulated unprocessed transcript, or (b) explicit "next room" event from app. Haiku 4.5 reads unprocessed chunks + last ~30 prior observations as context + room hint, calls a tool with the observations schema (forced JSON), writes new rows, marks chunks processed. **Prompt caching applied to system + tools blocks.**
5. **Real-time UI updates.** Frontend (partner's iPad, or buyer's phone if they look) subscribes via Supabase Realtime to `observations WHERE house_id = current`. New rows appear within ~100ms. No polling.
6. **Tour ends.** User taps "End Tour" in app, OR backend detects Meeting BaaS bot left meeting. Backend calls `MeetingProvider.stop_bot(bot_id)`, downloads recording (audio + video) to Supabase Storage, runs Sonnet 4.6 synthesis pass over full transcript + observations → produces house-level `synthesis_md` (executive summary, top concerns, deal-breakers, score). Sets `houses.status = 'completed'`.
7. **Post-tour comparison.** When ≥2 houses are completed, comparison view unlocks. Sonnet 4.6 receives all `synthesis_md` blobs in one prompt + user query → answers natural-language questions ("which house had the best kitchen for the kids?", "rank by hazard severity"). No vector DB.

## Build order — hour by hour (24-hour clock)

Real-time is squeezed in by ruthlessly cutting non-essentials and running an unsexy-but-correct foundation.

### Hours 0–3: Foundation

- Initialize GitHub repo, monorepo layout: `/backend` (FastAPI), `/frontend` (Next.js)
- Create Railway project, link to backend folder, set env vars stub
- Create Vercel project, link to frontend folder, set env vars stub
- Create Supabase project, run migration SQL (single file, paste into Supabase SQL editor)
- Configure Sentry: create org + two projects (backend, frontend), drop DSNs into env
- Implement Supabase magic-link auth on Next.js (login page → email → magic link → authed)
- Push to GitHub, confirm both Railway and Vercel auto-deployed, both healthy
- **Exit criterion:** Can log in via magic link on the deployed URL.

### Hours 3–8: Core async pipeline

Build the foundation that works WITHOUT Meeting BaaS first. This is the safety net — if real-time integration fails, this still ships a useful product.

- Backend: file upload endpoint (`POST /houses/{id}/audio`) → write to Supabase Storage
- Backend: Whisper API transcription wrapper (OpenAI's `whisper-1` model)
- Backend: Haiku 4.5 extraction wrapper with prompt caching, tool-use schema for observations
- Backend: Sonnet 4.6 synthesis wrapper for end-of-tour brief
- Backend: BackgroundTasks orchestrator: upload → transcribe → chunk → extract → write observations → synthesize
- Frontend: tour list, create-tour form (name, location, Zoom PMR URL field)
- Frontend: house list within tour, create-house form
- Frontend: per-house view with audio upload button, observation feed
- Frontend: Supabase Realtime subscription on observations
- **Exit criterion:** Can upload an audio file post-tour and see observations appear and a synthesis brief generate. This is a complete, shippable product.

### Hours 8–14: Real-time via Meeting BaaS

Layer real-time on top. Same downstream pipeline, different audio/transcript source.

- Define `MeetingProvider` Python interface (abstract methods: `start_bot`, `stop_bot`, `verify_webhook_signature`, `parse_transcript_webhook`, `get_recording_urls`)
- Implement `MeetingBaasProvider` against their API
- Backend: `POST /houses/{id}/start_tour` endpoint → calls provider, stores bot_id
- Backend: `/webhooks/meetingbaas/transcript` endpoint with HMAC verification + idempotency
- Backend: `/webhooks/meetingbaas/status` endpoint for bot lifecycle (joined, left, recording_ready)
- Backend: trigger extraction every 60s OR on "next room" event (use a simple in-process timer per active tour; Redis not needed for MVP)
- Backend: on bot-left event, fetch recording URL from Meeting BaaS, store in `houses.audio_url`/`video_url`, trigger synthesis
- Frontend: "Start Tour" button on house view → calls backend → shows Zoom PMR + bot status indicator
- Frontend: "Next Room" button (sends room hint to extraction context)
- Frontend: "End Tour" button → calls backend → triggers synthesis
- **Exit criterion:** Bot joins a real Zoom meeting, transcripts flow to DB, observations appear live in UI on a second device.

### Hours 14–18: Tour invites + comparison

- Backend: `POST /tours/{id}/invite` endpoint, creates `tour_invites` row, sends email via Supabase auth invite or Resend
- Frontend: invite form on tour view (email + role)
- Frontend: invite acceptance flow (magic link → joined to tour)
- Backend: `POST /tours/{id}/compare` endpoint — pulls all completed-house `synthesis_md`, sends to Sonnet 4.6 with user query, returns answer
- Frontend: comparison view with house cards (hero info, score, top concerns), free-text query box, answer rendering
- **Exit criterion:** Wife can be invited via email, log in, see live observations during a tour, and the comparison view works on at least 2 mock houses.

### Hours 18–20: Polish

- PWA manifest.json + minimal service worker (cache shell, network-first for data)
- "Add to Home Screen" prompt for first-time mobile users
- Privacy page (one route, plain copy explaining data handling)
- Supabase scheduled function for 90-day audio auto-delete
- RLS policies on every table (owner can do anything; participants can read all + write observations; nobody else can see anything)
- Sentry breadcrumbs on key user actions

### Hours 20–22: Battle-test

- Walk around current home as if it's a tour
- Test full flow: start tour, Zoom on iPhone, bot joins, observations populate, end tour, synthesis generates
- Fix whatever breaks (something will break)

### Hours 22–24: Buffer

- For the inevitable surprises
- If everything works: do a second dry run with the wife actually joining from another device
- Pack chest rig + DJI mic + iPhone charger + battery bank

### If hours 8–14 hit a wall (Meeting BaaS integration troubles)

The async path is already shipped at hour 8. Fallback plan:

- During Florida tours, record Zoom audio locally on iPhone (Voice Memos in parallel, or Zoom local recording on laptop joined as observer)
- Upload after each tour, async pipeline does its thing
- Wife loses the live-watch experience but still gets the analysis

This is acceptable. Do not sink hours 18–24 into fixing real-time at the expense of polish on the async path.

## Extraction prompt — design principles

This is the highest-leverage piece of engineering in the product. Iterate heavily.

- **Use Anthropic tool-use feature for forced JSON.** Define a `record_observations` tool with the observations schema. Claude must call this tool. Do NOT rely on JSON-mode prompting alone.
- **Two-step within one call:** First extract candidate observations verbatim from the chunk. Then classify each by room/category/severity/speaker. Better accuracy than one-shot.
- **Pass running context:** Last ~30 observations from this house, formatted as "already captured, do not duplicate."
- **Pass current room hint:** UI maintains sticky "current room" state, sent as context. Strong prior for classification, but Claude can override if transcript clearly indicates a different room.
- **Speaker-aware:** Meeting BaaS provides diarization. "Agent: water heater is 12 years old" → category=`agent_said`, severity=`warn`. "Partner: love this light" → category=`partner_said`.
- **Skip noise:** Most utterances aren't observations. Prompt should explicitly instruct Claude to return zero observations when nothing notable was said. Empty results are valid.
- **Prompt caching:** Apply `cache_control: {"type": "ephemeral"}` to the system block AND the tool definitions block. These don't change call-to-call. Cache hits cost 0.1x of base input tokens.

## Known landmines

- **Florida two-party consent.** Recording the seller's agent without explicit consent is real legal exposure. Mitigation: verbal consent at start of each tour, captured on the recording itself ("Hey, I'm using a notes app to transcribe — that okay?"). Build a one-tap "kill bot" button. Productize the consent flow eventually.
- **Zoom mobile rear camera.** UI varies between Zoom app versions; easy to accidentally broadcast face camera. Test before first real tour.
- **Bot visible name.** Bot joins as a named participant in Zoom. Name it "Tour Notes" or similar — unobjectionable. Have a script ready if someone asks.
- **Webhook reliability.** Meeting BaaS webhooks can retry. Idempotency on `(bot_id, start_seconds)` is required.
- **iPhone battery.** Zoom + rear camera + chest rig drains ~30%/hr. Pack a battery bank or MagSafe puck. Lower screen brightness, kill notifications, close other apps before tours.
- **Zoom 40-min cap.** No tour should exceed this — confirm with agent. If a house surprises you and approaches the cap, end and restart (creates a new bot session — small UX wart).
- **Meeting BaaS unfamiliarity.** First time using their API. Budget 30 min in hours 8–14 to read their docs end-to-end before writing the wrapper.
- **PWA on iOS Safari.** "Add to Home Screen" UX is clunky on iOS. The first-run experience needs a simple banner explaining the steps. Don't over-invest.

## Provider abstraction (for v2 swap to Recall)

```python
# backend/app/providers/meeting.py

from abc import ABC, abstractmethod

class MeetingProvider(ABC):
    @abstractmethod
    async def start_bot(self, meeting_url: str, webhook_url: str,
                        bot_name: str) -> str:
        """Returns bot_id."""

    @abstractmethod
    async def stop_bot(self, bot_id: str) -> None: ...

    @abstractmethod
    async def get_recording_urls(self, bot_id: str) -> dict:
        """Returns {'audio_url': str, 'video_url': str}."""

    @abstractmethod
    def verify_webhook_signature(self, headers: dict, body: bytes) -> bool: ...

    @abstractmethod
    def parse_transcript_webhook(self, payload: dict) -> list[dict]:
        """Normalizes provider payload to common transcript chunk shape:
        [{speaker, text, start_seconds, end_seconds}, ...]"""


class MeetingBaasProvider(MeetingProvider):
    # v1 implementation
    ...

# class RecallProvider(MeetingProvider):  # v2 — deferred
#     ...
```

Wire the abstraction once, never sprinkle vendor-specific logic outside `providers/meeting.py`. Swapping vendors becomes a config change + new impl class.

## Implementation hints (for Claude Code)

- Use `uv` for Python deps. `uv init`, `uv add fastapi uvicorn anthropic supabase httpx pydantic openai sentry-sdk`.
- Single SQL migration file pasted into Supabase SQL editor. Skip Alembic.
- Anthropic SDK: messages API with `tool_choice` forcing the `record_observations` tool.
- Magic-link auth only. Use `supabase.auth.signInWithOtp({ email })`.
- Make webhook handlers idempotent and fast (<500ms). Push real work to FastAPI BackgroundTasks.
- Frontend: subscribe to Realtime once at the house view level via `supabase.channel(...)`. Render reactively.
- Folder structure. Backend: `app/main.py`, `app/routes/`, `app/providers/`, `app/llm/`, `app/db/`. Frontend: standard Next.js App Router.
- Sentry init in both apps in the first deploy. Don't defer.
- Keep secrets in Railway/Vercel env vars. Provide `.env.example` files in repo.
- Use Pydantic models for all request/response shapes.

## Stretch goals

See `V2_BACKLOG.md`.
