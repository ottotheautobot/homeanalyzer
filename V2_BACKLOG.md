# V2 Backlog

Items deliberately deferred from v1 build. Revisit after Florida trip if the product proves useful.

## Vendor / infrastructure

- **Custom domain.** Currently using `*.vercel.app` subdomain. Register a real domain (e.g., `tourbrief.app`, `houserecon.io`, etc.) and migrate. Required for productization, professional look, and email deliverability.
- **Domain-based business email.** Once domain is set up, create `hello@yourdomain.com` etc. Required for #2 below.
- **Migrate from Meeting BaaS to Recall.ai.** Recall has the larger ecosystem, more mature webhooks, and Desktop Recording SDK (records meetings without a visible bot). Blocked on having a business email tied to a real domain. Migration is small thanks to `MeetingProvider` abstraction — implement `RecallProvider`, change one config value.
- **GitHub Actions CI.** Add `pytest` job for backend, `tsc --noEmit` for frontend. Block merge on failure. Skip on v1 because push-to-deploy is fine for solo dev.
- **Native iOS app.** Currently web-app + PWA. Native gives better camera/audio handling, push notifications, App Store discoverability. Blocked on Apple Developer account ($99/yr) + dev rights.

## Product / features

- **Video capture, storage, and vision analysis.** Bot captures video already (mp4 archived to Supabase Storage on bot.completed). Use Claude vision on extracted frames to surface visual observations the audio misses (cabinet quality, paint condition, window views, hazards visible but not commented on). Storage pricing and frame-extraction strategy TBD.
- **Decouple measured floor plan from the schematic.** v1.5 uses the Sonnet schematic as semantic input to MASt3R: the schematic's `entered_at`/`exited_at` per room are how we attribute 3D points to rooms. So any error in the schematic's room boundaries, room order, or transition timestamps becomes a permanent error in the measured polygons (e.g. lingering at a doorway 10 s into the bedroom adds bedroom views into the entryway polygon; missing a room entirely hides it from the measured plan). Need an intrinsic room-segmentation pass on the reconstructed scene — candidates: (1) cluster camera trajectory by speed/dwell-time + label rooms via a vision model on representative frames, (2) detect doorways from the point cloud's wall-gap geometry, (3) use the ceiling/floor topology from MASt3R's depthmaps to find room dividers. Right answer probably blends a vision-model labeling step with point-cloud-driven boundary detection, and treats the schematic as a *check* rather than ground truth.
- **Floor-plan reconstruction polish (the rest that didn't make v1.5).** (a) Build the curope CUDA kernel in the Modal image so RoPE2D doesn't run pure-PyTorch — ~3–5× speedup on the pairwise pass (currently ~6 min for 36 frames on A10G; 20-min tour at 60 frames will be 10+ min). (b) Wall-point leakage through doorways — DBSCAN per room or a view-association filter on top of decoupling above. (c) Global Manhattan-axis alignment so all room polygons share wall orientation instead of each having its own PCA axes (rooms currently look "twisted" relative to each other). (d) RoomFormer or similar to snap to right angles when Manhattan prior holds. Feasibility detail in `docs/floorplan-slam-research.md`.
- **Auto-trigger measured reconstruction after tour completes.** Currently the user has to click "Measure layout (beta)" on the house page. Should fire automatically as the last step of the post-meeting pipeline (after vision analysis), same way synthesis does today — gated on `ENABLE_MEASURED_FLOORPLAN` + presence of a video ≥ N seconds. Enqueue from `webhooks.meetingbaas` on `bot.completed`. Keeps the user out of the "wait, did I forget to click the button" loop.
- **Confidence-aware UI on the measured plan.** v1.5 returns a top-level `confidence: low|medium|high` and per-room `confidence: 0..1` + `sample_count`. UI today only renders the top-level pill; per-room confidence is invisible. Need: visually mark low-confidence rooms (dashed stroke / muted fill / explicit "rough estimate" tooltip) so the user knows which dimensions to trust. Especially important when MASt3R falls back to camera-trajectory bbox for under-covered rooms.
- **VGGT-1B-Commercial as alternate / future replacement for MASt3R.** v1.5 uses MASt3R (CC-BY-NC, fine for personal use, not commercial). If/when this app goes commercial, switch to VGGT-1B-Commercial (Meta) — gated approval but free for commercial use. VGGT also runs as a single forward pass, no global alignment optimization, so could shave reconstruction time significantly. Re-evaluate after Florida trip if monetization looks viable.
- **Photo capture in-app with Claude Vision analysis.** During or after tour, snap photos of specific concerns; vision model auto-tags and appends to observations. Increases data richness for comparison.
- **Auto-import listing data from Zillow/Redfin URLs.** User pastes a listing link; backend scrapes/fetches address, price, sqft, photos, amenities. Reduces manual data entry.
- **Per-tour shareable read-only "tour report" link.** Send to family, lender, or lawyer with a token-protected URL. No login required. Useful for buyer family decisions.
- **Map view of tour with house markers colored by score.** Geographic overview helps spot neighborhood patterns.
- **Voice-only observation capture (hold-to-record button).** For tours where Zoom isn't running. Falls back to async pipeline.
- **OBF token integration so bot joins as host (no record prompt).** Today the host has to manually grant the bot recording permission each tour. With OBF tokens passed on bot create, MB's bot inherits host privileges and skips the prompt. Required infra: complete the Zoom OAuth flow once on a real domain (blocked on custom domain v2 item), store the OBF token user_id, pass it via `zoom_obf_token_user_id` on every `POST /bots/`. Also satisfies Zoom's March 2026 OBF mandate for external meetings.
- **Silent bot / mute-on-join.** MB v1 has no exposed flag for "bot doesn't open a mic channel". The bot joins Zoom with an open mic device, which causes feedback loops with the iPhone speakerphone. Workaround today: host manually mutes. Investigate MB v2 streaming config for a silence/disable_speaker flag, or an explicit per-bot mute call after join.
- **Cross-tour comparison.** Today the comparison view scope is implicit (within one tour). User wants to manually multi-select houses across tours and run the same Sonnet comparison pass. Likely UX: a "Compare" page with a checklist of all completed houses (regardless of tour), grouped visually by tour but selectable across boundaries. Backend: replace the per-tour comparison endpoint with one that takes a list of house_ids.
- **Tours-secondary UX restructure.** Today's primary action is "create tour → create house → start". Most tours are spontaneous single-house viewings. Restructure: home/landing page shows recent houses + a big "Quick tour" button that takes just an address and starts immediately (auto-creates an unnamed tour bucket if none active, or appends to a recent one). Tours list becomes a secondary screen for grouping/comparison.
- **End Zoom meeting programmatically when End Tour is tapped.** Currently End Tour stops the Meeting BaaS bot but the Zoom meeting itself stays open. Wire `PUT https://api.zoom.us/v2/meetings/{id}/status?action=end` from the backend. Requires adding Server-to-Server OAuth credentials to the existing Marketplace app + scope `meeting:write:meeting`. Not blocking for the Florida trip — user can end Zoom manually after End Tour.
- **In-app account settings page.** Currently `users.default_zoom_url` is set via SQL. Add a /settings page (or a profile menu) where users can edit their default Zoom URL, name, and any other future per-user defaults. Backend route: `GET/PATCH /me`.
- **Solo mode in-app recording with near-live transcript processing.** Today's solo path is post-tour upload of an externally-recorded file. Future: in-app recording (Web Audio / MediaRecorder), chunked upload every ~30s, same Haiku/Sonnet downstream. Unlocks Next Room markers tied to the audio timeline (currently only multi-party gets that). Locked-out by the v1 "in-app recording: out of scope" decision; revisit when the multi-party flow is proven.
- **Consent-flow UI as first-class feature.** Template scripts ("Hi, I'm recording for personal notes — okay?"), consent capture on recording, jurisdiction-aware reminders for two-party-consent states. **Real differentiator vs. just-record-everything tools.**
- **Programmatic Zoom meeting creation.** Currently using Personal Meeting Room (one persistent URL). Integrate with Zoom API to create fresh meetings per tour — better UX, cleaner separation between tours.
- **Zoom Pro upgrade.** $15.99/mo removes 40-min cap on 3+ participant meetings. Currently a non-issue (tours <30 min) but a UX wart if a tour ever runs long.
- **Recall Desktop Recording SDK path.** Records without a visible bot in the call — eliminates "weird bot named X" awkwardness with seller's agents. Ties to the Recall migration.
- **Multi-tenant team support.** Buyer's agents managing multiple clients each touring multiple homes. Different data model — tenant → users → tours → houses.

## Productization / business

- **Pricing model.** Per-tour ($30–50?) or per-decision-window subscription ($30/mo for 2 months while actively house-hunting)? Test with 5–10 friends after Florida trip.
- **B2B angle.** Relocation companies, military relocation services, corporate housing programs have sustained need. Higher LTV, less churn than direct buyers.
- **Marketing landing page.** Currently no marketing surface. Needed before first paid users.
- **Privacy posture upgrade.** Currently 90-day auto-delete + RLS. For commercial use: SOC 2 path, formal privacy policy, ToS, DPA template for B2B.
- **Analytics.** Add PostHog or Plausible to understand actual usage patterns. Helps prioritize roadmap.

## Technical debt / improvements

- **Replace in-process timer with proper job queue.** Current 60s extraction trigger uses Python timer per active tour — fragile if backend restarts mid-tour. Migrate to Celery + Redis or similar for production scale.
- **Audio/video CDN.** Currently serving from Supabase Storage. CloudFront or Bunny.net would reduce latency for partner viewing across geographies.
- **Test suite.** Pytest for backend (especially the extraction prompt — golden-file tests), Playwright for frontend critical paths.
- **Observability beyond Sentry.** Structured logging, OpenTelemetry traces for the transcript-to-observation pipeline, alerting on extraction failures.
- **Migration to Anthropic Bedrock or Vertex AI.** If commercial scale is reached, enterprise customers may require AWS-native or GCP-native LLM access. Already abstracted via Anthropic SDK; should be straightforward.

## Research / exploration

- **Compare Sonnet 4.6 vs Opus 4.7 for synthesis quality.** Opus is 1.5x more expensive but may produce noticeably better cross-house comparisons. Run blind A/B on a handful of tour transcripts.
- **Explore Claude's prompt caching with 1-hour TTL.** Currently using 5-min default. For active tours, the longer TTL might reduce cache misses on slower-paced tours. Cost is 2x cache write but 10x cache read savings.
- **Whisper local vs. cloud transcription.** Currently using OpenAI Whisper API for async path. mlx-whisper on Apple Silicon is free and fast — could be a self-hosted user option.
