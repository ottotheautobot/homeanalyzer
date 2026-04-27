# V2 Backlog

Items deliberately deferred from v1 build. Revisit after Florida trip if the product proves useful.

## Vendor / infrastructure

- **Custom domain.** Currently using `*.vercel.app` subdomain. Register a real domain (e.g., `tourbrief.app`, `houserecon.io`, etc.) and migrate. Required for productization, professional look, and email deliverability.
- **Domain-based business email.** Once domain is set up, create `hello@yourdomain.com` etc. Required for #2 below.
- **Migrate from Meeting BaaS to Recall.ai.** Recall has the larger ecosystem, more mature webhooks, and Desktop Recording SDK (records meetings without a visible bot). Blocked on having a business email tied to a real domain. Migration is small thanks to `MeetingProvider` abstraction — implement `RecallProvider`, change one config value.
- ~~**GitHub Actions CI.**~~ Workflow built and tested locally; lives at `docs/ci-workflow.yml.template`. Move to `.github/workflows/ci.yml` and push using a credential with `workflow` scope to activate (the autonomous PAT didn't have it).
- **Native iOS app.** Currently web-app + PWA. Native gives better camera/audio handling, push notifications, App Store discoverability. Blocked on Apple Developer account ($99/yr) + dev rights.

## Product / features

- **Video capture, storage, and vision analysis.** Bot captures video already (mp4 archived to Supabase Storage on bot.completed). Use Claude vision on extracted frames to surface visual observations the audio misses (cabinet quality, paint condition, window views, hazards visible but not commented on). Storage pricing and frame-extraction strategy TBD.
- ~~**Decouple measured floor plan from the schematic.**~~ Shipped v1.6: intrinsic camera-cluster segmentation + Claude Haiku vision labeling per cluster. Schematic now optional (tier-2 fallback only).
- ~~**Floor-plan reconstruction polish.**~~ Shipped v1.6: curope CUDA kernel built (~2× speedup), Manhattan global alignment, adaptive DBSCAN eps based on tour pace. Still open: (a) wall-point leakage through doorways needs a view-association filter, (b) RoomFormer or similar to snap to right angles when Manhattan prior holds. Feasibility detail in `docs/floorplan-slam-research.md`.
- ~~**Auto-trigger measured reconstruction after tour completes.**~~ Shipped v1.6: `webhooks._finalize_inner` spawns the Modal job in a daemon thread after synthesis writes the schematic, gated on `ENABLE_MEASURED_FLOORPLAN` + video duration ≥ 30s.
- ~~**Confidence-aware UI on the measured plan.**~~ Shipped v1.6: per-room confidence drives stroke style (dashed + lighter fill + faded label when < 0.5), detail panel shows confidence %, sample frame count, and source ("wall-points" vs "camera-path rough estimate").
- **VGGT-1B-Commercial as alternate / future replacement for MASt3R.** v1.5 uses MASt3R (CC-BY-NC, fine for personal use, not commercial). If/when this app goes commercial, switch to VGGT-1B-Commercial (Meta) — gated approval but free for commercial use. VGGT also runs as a single forward pass, no global alignment optimization, so could shave reconstruction time significantly. Re-evaluate after Florida trip if monetization looks viable.
- **Better doorway detection from point-cloud wall gaps.** Today doors come from camera-trajectory crossings between cluster ids — cheap, but misses doors the camera didn't walk through. Add a pass that, for each pair of adjacent rooms, projects wall-height points onto the shared edge and looks for gaps > 0.8 m wide; midpoint of each gap is a presumed door. Layer on top of the trajectory pass.
- ~~**Photo capture in-app with Claude Vision analysis.**~~ Shipped v1.6: PhotoNoteButton on the house page, `<input capture=environment>` opens camera on iOS, optional room-hint dropdown, Haiku runs `record_observations` tool over the single frame, observations land with `source='user_photo_analysis'`.
- **Auto-import listing data from Zillow/Redfin URLs.** User pastes a listing link; backend scrapes/fetches address, price, sqft, photos, amenities. Reduces manual data entry.
- ~~**Per-tour shareable read-only "tour report" link.**~~ Shipped v1.6: `POST /tours/{id}/share` mints a token, public `/share/[token]` page renders briefs + observations (private notes hidden) with no login required.
- ~~**Map view of tour with house markers colored by score.**~~ Shipped v1.6: `/map` page uses pigeon-maps + Nominatim (free OSM geocoding, lazy + cached). Markers colored by overall_score.
- **Voice-only observation capture (hold-to-record button).** Distinct from the in-app full-tour recording shipped in v1.6; this is a quick "press and hold to add a single voice observation" pattern for in-the-moment notes outside an active tour.
- **OBF token integration so bot joins as host (no record prompt).** Today the host has to manually grant the bot recording permission each tour. With OBF tokens passed on bot create, MB's bot inherits host privileges and skips the prompt. Required infra: complete the Zoom OAuth flow once on a real domain (blocked on custom domain v2 item), store the OBF token user_id, pass it via `zoom_obf_token_user_id` on every `POST /bots/`. Also satisfies Zoom's March 2026 OBF mandate for external meetings.
- **Silent bot / mute-on-join.** MB v1 has no exposed flag for "bot doesn't open a mic channel". The bot joins Zoom with an open mic device, which causes feedback loops with the iPhone speakerphone. Workaround today: host manually mutes. Investigate MB v2 streaming config for a silence/disable_speaker flag, or an explicit per-bot mute call after join.
- ~~**Cross-tour comparison.**~~ Shipped in v1 — `/compare` already accepts arbitrary `house_ids`, the Compare UI groups houses by tour but selects across boundaries.
- ~~**Tours-secondary UX restructure.**~~ Partial v1.6: Quick-tour button on `/tours` opens an address-only modal, reuses the most recent tour if it's < 7 days old or mints a fresh `Tour YYYY-MM-DD`, jumps straight to the new house page. Full restructure (home page = recent houses, tours list as secondary) deferred until usage data tells us whether Quick-tour gets used enough to deserve top-level placement.
- **End Zoom meeting programmatically when End Tour is tapped.** Currently End Tour stops the Meeting BaaS bot but the Zoom meeting itself stays open. Wire `PUT https://api.zoom.us/v2/meetings/{id}/status?action=end` from the backend. Requires adding Server-to-Server OAuth credentials to the existing Marketplace app + scope `meeting:write:meeting`. Not blocking for the Florida trip — user can end Zoom manually after End Tour.
- ~~**In-app account settings page.**~~ Shipped v1.6: `/settings` page edits name + default Zoom URL via PATCH /me; URL prefix validation; Settings link in the app header.
- ~~**Solo mode in-app recording.**~~ Shipped v1.6: RecordAudio component uses MediaRecorder with a Safari-compatible mime fallback ladder, plays back the take before upload, posts to the existing `/audio` endpoint. Near-live chunked-upload variant (transcribe-as-you-record) still pending — would unlock Next Room markers in solo mode.
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
