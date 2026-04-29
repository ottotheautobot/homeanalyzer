# Changelog

Backfilled 2026-04-28 from git history. Coverage is best-effort for pre-backfill releases — granular Added/Changed/Removed/Fixed splits weren't tracked at the time, so each retroactive entry is a representative-not-exhaustive list of what shipped in that window. Going forward, new entries follow [Keep a Changelog](https://keepachangelog.com/) conventions.

Version names are marketing-style for now (`v1.6`, `v2.0`, etc.) and reflect the informal naming already in commit messages. Will move to proper semver once the API surface stabilizes — likely when the post-discovery v2 architecture lands. Calendar dates follow each release for unambiguous chronology.

---

## [Unreleased]

Customer-discovery phase — see `CONTEXT.md`. No major feature work planned for ~4 weeks. Smaller items still ship as observation surfaces friction worth fixing.

## v2.7 — Drop the visual floor plan, surface room list — 2026-04-29

### Removed
- **Visual measured-floor-plan rendering** (the SVG layout that v1.6 → v2.5 attempted). The camera-cluster segmentation primitive is the structural ceiling — validated against a locally-recorded 4-min tour upload (Lakeside Terrace) that produced the same 1-2 oversized "rooms" pattern as Zoom-passed-through tours, despite materially better video quality and 46-vertex polygon detail. Until in-app capture lets us influence camera flow / direction, the visual output is net-misleading vs informative.
- `frontend/lib/floor-plan-merge.ts` — the schematic+measured union layer. No longer needed.
- `frontend/app/(app)/tours/[tourId]/houses/[houseId]/measured-floor-plan.tsx` — the "Re-measure from video" controls + pending/failed states.
- `backend/app/routes/measured_floorplan.py` — `/houses/{id}/measure-floorplan`, `/poll`, `/cancel`, `/status` endpoints.
- Auto-trigger of the Modal floor-plan job in `webhooks._finalize_inner` and `video._process_video_upload_from_path`.
- `MeasuredFloorPlan*` types from `frontend/lib/types.ts` and the `measured_floor_plan_*` fields from the `House` type.

### Changed
- **Layout card → Rooms card.** Replaces the SVG visual with a card-grid of room name + dimensions (W×D′) + sq ft + per-room features. Total square footage summed at the top with a "dimensions are LLM estimates from the tour transcript" caveat. Still driven by the schematic LLM that's been producing this data all along — we were just hiding it behind a flashier-but-broken visual.

### Inert (kept for potential future use)
- `model_apps/floor_plan.py` Modal worker code stays in the repo but is no longer deployed or invoked. Preserves the work for the day in-app capture validates revisiting visual floor plans.
- `houses.measured_floor_plan_*` columns remain on the schema for archival of pre-v2.7 runs. No migration drop.
- `ENABLE_MEASURED_FLOORPLAN`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` Railway env vars become inert; remove at your leisure.

### Added (Unreleased work that landed alongside)
- `POST /houses/{id}/video/upload-url` + `POST /houses/{id}/video/process` — two-step signed-URL upload flow for tour videos recorded outside the app (no signal / app failure recovery). Uploads bypass Railway's request-body cap by going browser → Supabase Storage directly; backend stream-downloads to a temp file on disk to avoid OOM. Pipeline runs vision over frames → Whisper transcription of extracted audio → observations → synthesis → schematic floor plan. Doubles as the empirical input for the open "does clear video materially improve analysis output" question on the post-Zoom architecture decision (validated partially: vision density and polygon fidelity improve; segmentation primitive remains the bottleneck — hence v2.7's prune).

---

## v2.6 — Customer-discovery shift — 2026-04-28

### Changed
- Strategic posture: paused feature work for ~4 weeks of customer discovery. See `CONTEXT.md` for current standing context, `DECISIONS_LOG.md` for the strategic shifts.
- Renamed `V2_BACKLOG.md` → `BACKLOG.md` (now perpetual rather than version-bound).
- Consolidated four scattered "post-Zoom architecture" entries into one canonical section in the backlog covering the in-app capture-and-distribute vision (native iOS app + LiveKit + push-to-talk).

### Added
- `CONTEXT.md` — authoritative current-state document.
- `DECISIONS_LOG.md` — append-only strategic-decisions log.
- `CHANGELOG.md` — this file.

### Closed (non-shipping cleanup)
- Several P1 items closed via investigation rather than build (silent bot, MB archive verify) where no code path existed. See entries under `BACKLOG.md`.

## v2.5 — P1 sweep + Sonnet vs Opus verdict — 2026-04-28

### Added
- `services/zoom.py` — Server-to-Server OAuth client. End-Tour now ends the Zoom meeting programmatically (gracefully no-ops when creds aren't set).
- 1-hour prompt cache TTL on `extract.py`, `vision.py` (batch path), `compare.py`. Targets the live-tour transcript-extraction site (~20s cadence) where the 5-min default was missing on slower tours.

### Changed
- `frontend/lib/api-server.ts`: `serverFetch` now redirects to `/login` on missing session token instead of throwing. Mirrors the layout's behavior; fixes Mobile Safari SSR race.
- Floor plan: dropped geometric multi-story detection (v2.2 → v2.4 thrashed on it). All measured rooms ship as floor=1; frontend infers multi-floor from schematic upstairs labels. Frontend merge logic updated so schematic upstairs label beats measured floor.

### Decided (research)
- **Synthesis model: stay on Sonnet 4.6** over Opus 4.7. Quality comparable on 3 long real tours; Opus is faster but ~5× more expensive and would re-baseline cross-house score comparability.

## v2.0–v2.4 — Floor plan: VGGT primitive + multi-story thrash — 2026-04-28

### Added
- VGGT-1B-Commercial as primary reconstruction primitive (single forward pass, commercial license). Replaced MASt3R as the default for the Modal pipeline.
- Concave hulls (shapely) replacing axis-aligned bboxes for room polygons (v2.1).
- True schematic+measured union in the frontend merge (was previously a replacement).

### Changed
- Multi-story detection iterated four times (v2.2 → v2.5) trying to balance false positives against missing real two-story houses. Eventually backed out — see v2.6 changes.

## v1.7–v1.8 — Floor plan heuristic stack — 2026-04-27

### Added
- View-association filter (camera-to-point distance threshold).
- Iterative overlap merge with centroid-distance guard.
- Per-cluster door cap.
- Dimension-based confidence downgrade with per-label caps.

These improvements helped on short tours; long multi-room tours (Cooper City 24-min, Savannah 18-min) still hit the structural ceiling of camera-cluster-of-points segmentation. Documented in `BACKLOG.md` as the "true room segmentation" P4 item.

## v1.6 — Major product polish ship — 2026-04-27

### Added
- Intrinsic camera-cluster segmentation + Manhattan alignment for floor plans.
- curope CUDA kernel built into the Modal image (~2× reconstruction speedup).
- Auto-trigger measured floor plan after tour completes (gated on video duration ≥ 30s).
- Confidence-aware UI on measured plans (per-room stroke style, fill, label fading).
- `/settings` page — edit name + default Zoom URL without SQL.
- Per-tour shareable read-only `/share/[token]` links (no login required).
- `/map` page — pigeon-maps + Nominatim, every house pinned and score-colored.
- Photo notes (`PhotoNoteButton`) — snap a photo, Haiku vision extracts observations.
- Quick Tour flow — address-only modal, reuses recent tour or mints fresh one.
- Solo mode in-browser audio recording (`MediaRecorder` with Safari mime fallback ladder).
- GitHub Actions CI workflow (`docs/ci-workflow.yml.template` first; activated as `.github/workflows/ci.yml` later).
- Adaptive DBSCAN eps for floor-plan clustering, scaled to tour pace.
- Public `/features` page in plain English.
- "Show evidence" on video-derived observations (single-frame screenshot or wider clip variants).

### Changed
- Schematic floor plan now optional (tier-2 fallback) — measured plan is canonical when ready.
- Audio: opus compression before storage upload.
- Storage uploads: bypass storage3, use httpx directly with explicit timeouts.
- Per-observation `recall_timestamp` from Haiku (was previously bucketed by extraction window).
- Observations tagged with source in synthesis + comparison prompts.

### Fixed
- `/houses/map` SSR timeout (geocoding now bounded synchronously).
- Stale-pending measured-plan rows now unstickable.
- Photo column-name fix on `/houses/map`.
- Stricter address validation pre-Nominatim.

## v1.5 — Measured floor plan first ship — 2026-04-27

### Added
- Schematic floor plan from transcript (Sonnet-extracted rooms + adjacency).
- SVG schematic rendering on the house page.
- Measured floor plan via Modal GPU worker — Depth Anything V2 first, then MASt3R sparse global alignment as the primary path.
- Floor-plan SLAM feasibility report (`docs/floorplan-slam-research.md`).
- Estimated dimensions per room with geometric layout.

## v1.0 — Florida tours validation — 2026-04-26 to 2026-04-27

The MVP that actually got used on real house tours. Validated the core flow end-to-end across roughly 10 Fort Lauderdale rentals.

### Added
- Zoom Meeting SDK credentials passed on bot create (bypass OBF for dev's own account).
- App-feel UI pass — accent color, richer tour list, prominent live state, Inter font.
- Recording playback on completed houses.
- Vision-augmented observations from the bot's mp4 (post-meeting Haiku pass over extracted frames).
- `ENABLE_VISION_ANALYSIS` feature flag.
- Add House: geolocation autofill, curb appeal photo, listing URL, sale/rent toggle.
- Refresh on tab refocus (fixes iOS Chrome background-tab silence).
- Auto-claim pending invites on every authed request.
- Send invite email via Resend with one-tap action link (replaced Supabase invite flow).

### Fixed
- Compress large WAVs before sending to Whisper.
- Webhook signature bypass flag for environments where signing fails.
- Various MB diagnostics endpoints + manual finalize for stuck pipelines.
- "Retry processing" banner for stuck post-meeting pipelines (also covers `synthesizing` status).

## v0.5 — Real-time via Meeting BaaS — 2026-04-26

### Added
- `MeetingProvider` abstraction + `MeetingBaasProvider` concrete impl.
- Bot lifecycle webhooks (`bot.status_change`, `bot.completed`, `bot.failed`) with HMAC signature verification.
- Idempotent transcript ingestion on `(bot_id, start_seconds)`.
- Live transcription via Deepgram nova-2 streaming over MB audio WebSocket. (MB's bundled transcription was post-meeting only — not what the brief had assumed.)
- Real-time observation feed via Supabase Realtime.
- Live transcript feed in UI; faster extraction triggers.
- Tour invites with magic-link signup + auto-add to tour.
- Cross-tour comparison view (Sonnet 4.6 over completed-house briefs).
- Email notifications for tour participants when a tour starts.
- Swipe-to-delete on tours and houses with full storage cleanup.
- Default Zoom URL on user record; auto-fill on new tours.

### Fixed
- Realtime publication migration made idempotent.
- Deepgram 400s on streaming connect (model name + minimal params).
- Replaced Deepgram SDK with raw websockets for the streaming bridge.
- KeepAlive frames during bot Zoom-join window.
- Various MB streaming / silence-timeout / token-burn fixes.

## v0.1 — Initial scaffold + async pipeline — 2026-04-25

### Added
- Repo scaffold: backend (FastAPI + uv), frontend (Next.js 15 App Router + TypeScript), Supabase migrations.
- Async pipeline: audio upload → Whisper → Haiku 4.5 extraction → Sonnet 4.6 synthesis. End-to-end without any real-time dependency.
- Tours / houses UI.
- Magic-link auth via Supabase.
- Sentry on backend and frontend from day 1.
- BG-task exception forwarding to Sentry.

This was the safety-net build per `PROJECT_BRIEF.md` hours 3–8 — a complete, shippable async-only product before real-time was layered on top.
