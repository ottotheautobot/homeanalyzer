# Standing Context

This is the authoritative current-state document. When `PROJECT_BRIEF.md` and this file disagree, this file wins — the brief is preserved as historical record. Read this before suggesting work.

## Current phase

**Customer discovery, not feature build.** The MVP shipped and was validated on real Florida tours. We are explicitly *not* in feature-build mode. The point of the next ~4 weeks is information, not progress.

## The 4-week plan

1. **Polish to put-it-in-someone-else's-hands quality** — fix the rough edges that would block a real homebuyer (not the builder) from completing a tour without help.
2. **Mom uses it** — first non-builder user. Observe friction. She is also the warm distribution channel into buyer's-agent discovery.
3. **Discovery calls with agents and inspectors** — parallel tracks. Listen, don't pitch.
4. **Decide** — based on what discovery surfaces, pick a path. Architecture, customer, and pricing decisions all defer to this point.

## Customer paths under consideration

- **Buyers' agents (primary discovery target)** — warm distribution available via mom; broker network is the vector. White-label briefs, multi-client dashboards, agent-to-buyer share flow are the relevant feature surface (see BACKLOG `Buyer's agent vertical`).
- **Inspectors (parallel discovery track)** — existing audio capture → transcription → classification → structured output pipeline translates well to inspection workflows. Would need a different prompt taxonomy + PDF report shape, not an architectural rebuild (see BACKLOG `Inspector vertical`).
- **Relocation services (Phase 3)** — only if the first two paths don't pan out.
- **D2C is not the path.** Brutal economics, no retention, low willingness to pay. Rule it out unless something forces a re-evaluation.

## Architectural questions on the table (uncommitted)

These are *open questions* for the discovery phase, not decisions:

- **Capture-vs-collaboration split.** Should high-fidelity capture (local 4K, possibly LiDAR) be decoupled from the live audio + observation feed that drives collaboration? Tracked in `BACKLOG.md` Research / exploration.
- **Departure from Zoom + Meeting BaaS.** Plausible if the capture/collab split is adopted; not committed.
- **Native iOS app.** Becomes a hard requirement *only* if the local-4K-capture path is committed. Otherwise stays a productization preference, not a blocker.

None of these get built before discovery answers whether they're worth building.

## Anti-patterns to push back on

If the user (or you) start drifting toward any of these, push back explicitly:

- **Premature polish.** "Let's rebuild X before showing it to anyone" is the trap. The bar is "would block a real user from completing a tour," not "looks the way a designer would want it to."
- **Architectural rebuilds without user-validated triggers.** No replacing Zoom, no swapping providers, no migrating frameworks unless discovery surfaces a problem that justifies it. The `MeetingProvider` abstraction exists; honor it.
- **Optimizing costs before optimizing customer.** Vendor spend isn't a real problem yet. Don't propose self-hosting, model swaps, or infra migrations on cost grounds at MVP scale.
- **Adding features to the discovery path.** Discovery work is observation, transcript review, and follow-up calls — not shipping more product to talk about.

## Cost discipline

- **Instrument before optimizing.** If a vendor isn't tagged in monitoring, don't have an opinion on whether it's expensive. The numbers tell the story.
- **Self-host nothing until vendor spend justifies it.** Rough threshold: ~$500/mo per vendor. Below that, the engineering trade is bad. Above it, revisit.
- Engineering time costs roughly zero (Claude Code is flat-rate); real recurring costs are infra + per-call inference. ROI calculations should weight those, not engineering hours.

## The "show ugly, then overhaul" sequence

The discipline that keeps us out of the polish trap:

1. **Ship to users at current quality.** Mom uses what we have, not what we wish we had.
2. **Observe friction.** What blocks her? What confuses her? What does she ignore? What works?
3. **Only fix what observation justified.** Resist the urge to fix things we *think* will block her. The list of pre-emptive fixes is always longer than the list of real ones.

This applies to capture quality, UI polish, error handling, copy, onboarding — everything. Until a real user hits a real wall, it doesn't need work.
