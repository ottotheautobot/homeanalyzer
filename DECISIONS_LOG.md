# Decisions Log

Append-only record of meaningful decisions and the reasoning behind them. Entries are not deleted when superseded — instead, a new entry is appended that explicitly references and overrides the old one. This file is the canonical answer to "why did we do X" questions.

**Entry shape:**

- **Decision** — one sentence, what we decided
- **Context** — what was happening when the decision was made
- **Rationale** — why this option won over the alternatives
- **Status** — `Active` (still in force), `Under Review` (being reconsidered), or `Deferred` (no longer in force; superseded — link forward)

---

## 1. v1 architecture: Zoom + Meeting BaaS + Deepgram + chunked extraction

_Date: ____ (fill in)_

- **Decision:** Build the v1 product on a transport stack of Zoom (host-side capture + collaboration) + Meeting BaaS (bot relay + recording) + Deepgram nova-3 (streaming transcription) + Haiku 4.5 chunked extraction every 60s.
- **Context:** v1 launch under a hard 24-hour build window for a Florida house-tour trip. Required real-time collaboration (partner watches notes appear live), multi-party audio, and structured observation extraction. No prior product to learn from; everything was a guess.
- **Rationale:** Each piece was the lowest-effort way to hit "good enough" in the window. Zoom gave free multi-party transport. Meeting BaaS gave a bot-as-a-service primitive that handled the join/record/leave lifecycle. Deepgram streaming was the only realistic path to per-utterance transcripts (MB's bundled transcription is post-meeting only). Chunked extraction every 60s let us amortize LLM cost while keeping the perceived-live feel.
- **Status:** `Under Review`. Shipped and validated on real tours, but the capture-quality and collaboration-UX trade-offs are now under reconsideration as part of the customer-discovery phase. See entry 6.

## 2. Strategic shift to customer-discovery mode

_Date: ____ (fill in)_

- **Decision:** Pause feature work. Spend ~4 weeks on customer discovery before committing to any architectural or product direction.
- **Context:** v1 shipped and worked. The natural pull is to keep building — polishing, layering features, expanding scope. That pull is the wrong direction without information about who the customer actually is.
- **Rationale:** The wedge in `PROJECT_BRIEF.md` was a guess optimized for the builder's own use case. Real discovery (mom uses it, agents and inspectors get interviewed) costs zero engineering time and de-risks every subsequent decision. Building features pre-discovery means we're optimizing the wrong thing with high confidence and low information.
- **Status:** `Active`. Plan: polish → mom uses it → discovery calls → decide. See `CONTEXT.md` for the four-week plan.

## 3. Inspector vertical added as parallel discovery track

_Date: ____ (fill in)_

- **Decision:** Run an inspector-customer discovery track in parallel with the buyer's-agent track during the discovery phase.
- **Context:** While exploring who the v1 product naturally serves, the home-inspector use case surfaced as a structurally similar workflow: walk a property, capture audio + visuals, produce a structured report. The same pipeline applies.
- **Rationale:** The existing capture → transcription → classification → structured-output pipeline translates well. What changes is prompt taxonomy (defects per ASHI/InterNACHI standards), output shape (PDF inspection report vs. buyer brief), and accuracy bar (safety-related observations need human-in-the-loop). These are reshapings, not rebuilds. Cheap to test in discovery; high upside if a single inspector validates.
- **Status:** `Active`. See `V2_BACKLOG.md` Inspector vertical section for the candidate work.

## 4. Buyer's agent path elevated to primary discovery target

_Date: ____ (fill in)_

- **Decision:** Make buyer's agents the primary discovery target ahead of direct-to-consumer buyers.
- **Context:** During strategic-framing discussions, the warm-distribution question dominated: who can we get in front of without paid acquisition or cold outreach? The builder's mother is a working real-estate professional with a broker network, which makes the buyer's-agent path uniquely accessible.
- **Rationale:** Cold customer-discovery is the rate-limiting step at this stage. Warm intros via an existing broker network are 10x more efficient than D2C funnel-building. Even if the long-term customer is the buyer, agent-mediated distribution is a faster path to validated demand.
- **Status:** `Active`. See `V2_BACKLOG.md` Buyer's agent vertical section.

## 5. D2C path deprioritized

_Date: ____ (fill in)_

- **Decision:** Direct-to-consumer (homebuyers paying directly) is not the go-to-market path.
- **Context:** D2C was implicit in the v1 framing (the builder + his wife were the test users; the wedge was "built for the buyer making a high-stakes decision"). On harder examination of the unit economics, D2C is structurally bad.
- **Rationale:** Three problems compound: (a) brutal economics — a buyer touring 5–10 homes over 2–3 weeks generates one-time revenue with no expansion path, (b) no retention — once they've bought a house, they're done for years, (c) low willingness to pay — homebuyers don't perceive note-taking as a separable, paid problem the way professional users do. Buyer's agents and inspectors both have repeat usage and structural willingness to pay for tools that improve their deliverables.
- **Status:** `Active`. Rule it out unless something in discovery forces a re-evaluation.

## 6. Architectural exploration of capture/collaboration split

_Date: ____ (fill in)_

- **Decision:** Open a research track investigating whether capture (high-fidelity recording for analysis) should be architecturally split from collaboration (live partner experience) instead of using one transport for both.
- **Context:** Two pain points from v1 surfaced together: (a) Zoom's video compression visibly hurts capture quality, especially for the floor-plan reconstruction pipeline that wants every pixel — and (b) Zoom's active-speaker bandwidth allocation has degraded the partner's live-viewing experience in multi-party tours. Both are symptoms of conflating two jobs into one transport.
- **Rationale:** A capture-vs-collaboration split would let each be optimized independently. **Capture** = local 4K (and possibly LiDAR depth) recorded on-device, decoupled from any live link, fed to the analysis pipeline at full quality. **Collaboration** = a low-bandwidth audio stream + the live observation feed as the partner's UX, replacing video mirroring entirely. The collaboration UX may end up *richer* than passive video-watching because it gives the partner an interactive feed of what's being captured, not just a shaky mirror. Eliminates Meeting BaaS as a transport dependency. Heavy overlap with the existing "replace the Zoom-bot middleman" backlog item — this is the cleaner architectural framing.
- **Status:** `Under Review`. Not committed. Pending customer validation of whether the buyer/inspector use case rewards capture quality enough to justify the iOS-app cost it would imply (see `V2_BACKLOG.md` Research / exploration).
