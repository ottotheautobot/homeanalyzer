# V2 Backlog

Items deliberately deferred from v1 build. Revisit after Florida trip if the product proves useful.

## Vendor / infrastructure

- **Custom domain.** Currently using `*.vercel.app` subdomain. Register a real domain (e.g., `tourbrief.app`, `houserecon.io`, etc.) and migrate. Required for productization, professional look, and email deliverability.
- **Domain-based business email.** Once domain is set up, create `hello@yourdomain.com` etc. Required for #2 below.
- **Migrate from Meeting BaaS to Recall.ai.** Recall has the larger ecosystem, more mature webhooks, and Desktop Recording SDK (records meetings without a visible bot). Blocked on having a business email tied to a real domain. Migration is small thanks to `MeetingProvider` abstraction — implement `RecallProvider`, change one config value.
- **GitHub Actions CI.** Add `pytest` job for backend, `tsc --noEmit` for frontend. Block merge on failure. Skip on v1 because push-to-deploy is fine for solo dev.
- **Native iOS app.** Currently web-app + PWA. Native gives better camera/audio handling, push notifications, App Store discoverability. Blocked on Apple Developer account ($99/yr) + dev rights.

## Product / features

- **Photo capture in-app with Claude Vision analysis.** During or after tour, snap photos of specific concerns; vision model auto-tags and appends to observations. Increases data richness for comparison.
- **Auto-import listing data from Zillow/Redfin URLs.** User pastes a listing link; backend scrapes/fetches address, price, sqft, photos, amenities. Reduces manual data entry.
- **Per-tour shareable read-only "tour report" link.** Send to family, lender, or lawyer with a token-protected URL. No login required. Useful for buyer family decisions.
- **Map view of tour with house markers colored by score.** Geographic overview helps spot neighborhood patterns.
- **Voice-only observation capture (hold-to-record button).** For tours where Zoom isn't running. Falls back to async pipeline.
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
