# Option C: True Measured 2D Floor Plan from Casual Handheld Tour Video

Detailed research notes from April 2026. Companion to the "Measured 2D floor plans from tour video" item in `V2_BACKLOG.md`.

## TL;DR

Buildable in 2026, not science fiction. Recommended pipeline:
**VGGT-1B-Commercial → Mask2Former (ADE20K) → gravity alignment → RoomFormer (with iterative-RANSAC fallback)**, deployed on Modal serverless H100. Add a tiny capture-protocol nudge ("slow 360° spin in each room") and you go from "barely works" to "works ~70% of the time first try."

- **Engineering effort**: 6–10 engineer-weeks for a competent ML engineer to ship behind a feature flag.
- **Per-tour compute cost** (steady state, Modal serverless): **~$0.60** for a 20-min tour with the VGGT pipeline. **~$0.30** with MASt3R-SLAM (non-commercial license) or RunPod cheaper hardware.
- **Compare vs. API**: CubiCasa is $35–$80 per plan. In-house compute is **40–100× cheaper per tour**, but you're trading engineering cost for API cost. Crossover is around 1k tours/month.
- **Honest verdict for an MVP single-user product**: don't build it. Use CubiCasa or Polycam free tier with a separate deliberate scan, attach the PDF to the house. Spend the saved engineering on the wedge (real-time observations, partner live-watch, comparison brief). Revisit floor plans only after the wedge is proven and tour volume justifies it.

## The pipeline

End-to-end stages, with the algorithm/model that does each:

1. **Pre-process**: ffmpeg to drop variable framerate to uniform 4–8 fps, motion-blur rejection (variance-of-Laplacian), tag each frame with its room from existing tour-order data.
2. **Camera trajectory + dense 3D points**: VGGT-1B-Commercial (best 2026, commercially licensed). Alternatives: MASt3R-SLAM (CC BY-NC), DROID-SLAM (older but commercially safe), COLMAP (slowest baseline).
3. **Metric scale recovery**: VGGT's pointmaps are roughly metric out of the box. Refine with a ceiling-height prior (median floor-to-ceiling distance snaps to 8 ft) or Depth Anything V2 (metric) as a per-frame prior.
4. **Gravity alignment**: RANSAC the dominant horizontal plane (the floor) so the world's XZ plane is the floor.
5. **Semantic segmentation**: Mask2Former trained on ADE20K (has explicit `floor`, `wall`, `ceiling`, `door`, `mirror` classes). Project 2D masks back into the 3D point cloud via known per-frame extrinsics.
6. **Wall extraction & polygons**: Top-down density image of wall points → RoomFormer or PolyRoom (learned end-to-end), with iterative-RANSAC + Manhattan snapping as a debug-friendly fallback.
7. **Room labeling**: Match polygons to room names from the existing Sonnet-derived adjacency graph by frame-timestamp overlap.
8. **Render**: SVG floorplan, JSON polygon storage, room dimensions, door positions.

## Tools, scored

Best commercially-licensed stack: **VGGT-1B-Commercial → Mask2Former → RoomFormer**.
Best research-only stack (cheaper, non-commercial): **MASt3R-SLAM → Mask2Former → RANSAC-Manhattan**.

| Component | Maturity | VRAM | Runtime / 20 min input | License | Floorplan-readiness |
|---|---|---|---|---|---|
| **VGGT (Meta, CVPR 2025 Best Paper)** | High; multiple acceleration forks (FastVGGT, FlashVGGT) | 12–35 GB | 1–4 min on H100 | Code permissive; **VGGT-1B-Commercial checkpoint commercially licensed** | Best raw geometry available with commercial license |
| **MASt3R-SLAM (Murai 2025)** | High; Rerun integration | 14 GB | 10–20 min on A10G real-time | **CC BY-NC** (dealbreaker for commercial) | Excellent intermediate output |
| **SLAM3R (PKU 2025)** | New | 16 GB+ | ~Real-time | Likely inherits non-commercial from DUSt3R lineage | Same as MASt3R-SLAM |
| **DROID-SLAM (Princeton 2021)** | Mature | 11 GB | 15–25 min on A10G | **Commercially usable** | Commercial fallback if VGGT licenses change |
| **NeuralRecon (ZJU 2021)** | Mature | 8 GB | Real-time on T4 | Apache-2.0 | Cheap-tier fallback; less accurate on shaky handheld |
| **COLMAP / GLOMAP** | Reference | 8 GB | 30–90 min | BSD | Slowest baseline; reliable when learned methods fail |
| **SplaTAM / Splat-SLAM / MonoGS** | Active | 12–24 GB | 5–30× video duration | Mixed permissive | Wrong tool — Gaussian splats are for view synthesis, not floor plans |
| **Mask2Former (ADE20K)** | Production | 4–8 GB | Sub-real-time | Apache-2.0 | Direct input for stage 5 |
| **HorizonNet (single panorama)** | Mature | <4 GB | 20 ms / panorama | Permissive | Direct floor plan if you can produce panoramas (capture nudge) |
| **RoomFormer (CVPR 2023) / PolyRoom (ECCV 2024)** | Mature | 8 GB | <30 s / image | Permissive | End-to-end top-down → polygons |

## Cloud-GPU options

Railway has no GPUs, so the heavy job runs on a serverless GPU service.

| Provider | Best GPU | $/hr (on-demand) | Cold start | Python ergonomics | Notes |
|---|---|---|---|---|---|
| **Modal (recommended)** | H100 $10/hr; A10G $1.10/hr; T4 $0.59/hr | sub-2s with snapshots | Best — `@app.function(gpu="H100")` decorators, `modal deploy` | $30/mo free credit covers MVP testing | Best ergonomics for a Python+FastAPI stack |
| **RunPod Serverless** | H100 $4.18/hr; A100 $2.17/hr | 6–12s | Decent (Docker image) | Cheapest serverless H100 at scale | Switch target when scaling |
| **Replicate** | A100 $5.04/hr | 30s–30 min on cold custom model | OK (`cog` framework) | Cold starts unpredictable for custom code | Better for off-the-shelf models |
| **Lambda Cloud** | A100 80GB $1.79/hr; H100 $2.49/hr | Minutes (VM boot) | SSH; you manage the box | No auto-scale to zero — wasteful for sparse jobs | |
| **Vast.ai** | A100 80GB $0.67–$3.50/hr; L40 $0.31/hr | Variable | Manual | Cheapest by far; reliability is your problem | Useful for offline batch / dev |
| **Fly.io GPU** | – | – | – | – | **Deprecated after Aug 2025** — do not use |

Self-hosting an H100 is absurd for one user.

## Per-tour cost (20-min input, end-to-end)

| Pipeline | GPU + service | Cost |
|---|---|---|
| **VGGT on Modal H100 + T4 helpers** | $10/hr (H100) + $0.59/hr (T4) | **~$0.60** |
| **MASt3R-SLAM on Modal A10G** | $1.10/hr | **~$0.30** (non-commercial license) |
| **VGGT on RunPod serverless H100** | $4.18/hr | **~$0.30–$0.40** |
| **CubiCasa API** | – | **$35–$80/plan** |

## What breaks (failure modes)

1. **Featureless walls** — biggest single failure mode. Mitigation: rely on Mask2Former wall masks rather than raw geometry.
2. **Motion blur from fast pans** — drop low-Laplacian frames, prompt user to "pan slowly."
3. **Rolling shutter** on iPhone — slow movement helps; no IMU sync makes hard fixes infeasible.
4. **Scale drift** over long trajectories — ceiling-height prior keeps it bounded.
5. **Loop closure** failing — VGGT does it implicitly via global attention; capture protocol of returning to entryway helps.
6. **Briefly-visible rooms** (closets) — capture-protocol prompt to "sweep across the closet for 5 seconds."
7. **Mirrors/glass** — mask via Mask2Former before fitting walls.
8. **No floor visible** (chest-mount points up at walls/ceiling) — wall-only geometry is fine; floor extent inferred from convex hull of wall feet.
9. **Featureless hallway transitions** — capture-protocol slow walk through doorways.

Realistic accuracy for a "12×14 master" claim with the recommended pipeline + capture protocol:
- ~80% of rooms produce a polygon within 15% of ground truth on each dimension first try.
- ~10% come out shaped weirdly (one wall missing, L-shape when room is rectangular). Catchable with a sanity rule.
- ~10% fail outright (closets, occluded bathrooms, <5s rooms). Need a manual-review or "missing room" UI state.
- For overall layout (relative room positions): ~70% correct first try.

## Capture-flow nudges that materially help

The single biggest lever:

**"Slow 360° spin in each room before you walk through it."** Buyer enters room, plants feet, slowly rotates ~360° over ~10 seconds, then proceeds. This single step:
- Gives SLAM a controlled rotation with overlapping views (huge for matching).
- Lets you stitch a panorama → run HorizonNet for a per-room layout as a sanity check.
- Naturally captures all four walls.

Build into the existing "Next Room" button: tapping it triggers a 10-second spin countdown.

Other nudges:
- Hold camera level at chest height.
- Walk slowly between rooms, especially through doorways.
- Open closet doors.
- Avoid pointing at mirrors.
- Don't whip the phone around fast.

The spin alone is worth ~20 percentage points. The rest is another ~10–15.

## Engineering effort (no padding)

| Task | Weeks |
|---|---|
| Stand up Modal account, deploy a hello-GPU function callable from FastAPI on Railway | 0.25 |
| Integrate VGGT-1B-Commercial; sanity-check pointmap output via Rerun | 0.75 |
| Frame sampling, motion-blur rejection, ffmpeg pipeline, S3 ingest | 0.5 |
| Mask2Former integration, project masks to 3D | 0.75 |
| Gravity alignment + Manhattan world detection + scale calibration | 1.0 |
| RoomFormer integration (or RANSAC fallback) for polygon extraction | 1.0 |
| Match polygons to room names via existing tour-order graph | 0.5 |
| SVG render + JSON schema + Supabase Storage | 0.5 |
| Job orchestration: BackgroundTask → Modal `.spawn()` → status webhook | 0.5 |
| Error handling, partial-success states, retry logic | 0.5 |
| Evaluate on 5+ real tours, iterate on capture protocol, fix worst failure modes | 1.5 |
| UI: floorplan tab, render SVG, error states | 0.5 |
| Sentry traces stage-by-stage, tour-quality metrics | 0.25 |
| Feature flag, gradual rollout, fallback state | 0.25 |
| **Total** | **6–10 weeks** |

## Pragmatic shipping plan (4-week minimum-viable scope)

Budget: $5k engineering (≈4 weeks of one strong contractor) + $200 cloud-GPU spend for evaluation.

```
Buyer's iPhone → Zoom → Meeting BaaS bot → mp4 in Supabase Storage
                                                ↓
                          [Existing async pipeline]
                                                ↓
                     Trigger: synthesis completed
                                                ↓
        FastAPI on Railway: enqueue Modal job with video URL + house_id
                                                ↓
        Modal CPU+T4 ─→ ffmpeg + frame sample + Mask2Former
                                                ↓ (point cloud + masks → S3)
        Modal H100 (ephemeral) ─→ VGGT reconstruction
                                                ↓ (poses + dense pointmap → S3)
        Modal CPU ─→ gravity align + RANSAC walls + RoomFormer
                                                ↓
        Webhook back to Railway → write floorplan_json + svg to houses table
                                                ↓
        Supabase Realtime → frontend updates Floor Plan tab
```

- Week 1: Modal + VGGT working on one test video; raw point cloud viewable.
- Week 2: Mask2Former + gravity alignment + RoomFormer; rough JSON polygons.
- Week 3: 5 test tours; iterate on failure modes; scale calibration; Manhattan snapping.
- Week 4: SVG rendering, frontend tab, feature flag, observability.

Cut from full 8-week version: room-name matching beyond simple tour-order alignment, automatic correction of weird shapes, comparison features, non-Manhattan handling.

## Honest recommendation

**Build in-house when:**
- Floor plans are first-class data feeding the LLM observation stream (e.g., "agent said 14×18, plan says 11×14, flag discrepancy").
- Free-form video without a separate scanning pass is a real requirement.
- Tour volume is heading to >1k/month within 12 months.
- A strong CV/ML engineer is on the team and 6–10 weeks are spendable.
- ~70% first-shot success is acceptable with a "redo" UI affordance.

**Integrate CubiCasa (or Polycam, iGUIDE) when:**
- Floor plans are nice-to-have, not the wedge.
- Tour volume <100/month for the foreseeable future.
- Predictable quality matters more than per-tour cost.

**For our specific MVP situation right now**: don't build any of this. Use CubiCasa or Polycam free tier with a separate 2-min deliberate scan per house, attach the floor plan PDF to the house. Spend the saved engineering on the things that deliver the wedge — real-time observations, partner live-watch, comparison brief. Revisit when the product has paying users and 1k+ tours/month is in sight.

## Sources

- [DUSt3R](https://arxiv.org/abs/2312.14132), [DUSt3R GitHub](https://github.com/naver/dust3r)
- [DUSt3R / MASt3R / VGGT eval (T&F 2025)](https://www.tandfonline.com/doi/full/10.1080/10095020.2025.2597491)
- [MUSt3R](https://github.com/naver/must3r), [3D Foundation Models — Naver Labs](https://europe.naverlabs.com/research/3d-foundation-models/)
- [SLAM3R paper](https://arxiv.org/abs/2412.09401), [SLAM3R GitHub](https://github.com/PKU-VCL-3DV/SLAM3R)
- [MASt3R-SLAM project](https://edexheim.github.io/mast3r-slam/), [GitHub](https://github.com/rmurai0610/MASt3R-SLAM)
- [VGGT project](https://vgg-t.github.io/), [GitHub](https://github.com/facebookresearch/vggt), [VGGT-1B-Commercial](https://huggingface.co/facebook/VGGT-1B-Commercial)
- [DROID-SLAM](https://github.com/princeton-vl/DROID-SLAM)
- [NeuralRecon](https://zju3dv.github.io/neuralrecon/)
- [Mask2Former](https://github.com/facebookresearch/Mask2Former), [HuggingFace](https://huggingface.co/docs/transformers/en/model_doc/mask2former)
- [HorizonNet](https://ar5iv.labs.arxiv.org/html/1901.03861)
- [RoomFormer](https://ywyue.github.io/RoomFormer/), [PolyRoom](https://arxiv.org/abs/2407.10439)
- [Iterative RANSAC floorplan reconstruction (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/abs/pii/S2352710224008064)
- [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2)
- [Modal pricing](https://modal.com/pricing), [Modal cold start docs](https://modal.com/docs/guide/cold-start)
- [RunPod pricing](https://www.runpod.io/pricing), [Replicate pricing](https://replicate.com/pricing)
- [CubiCasa pricing](https://www.cubi.casa/pricing/), [CubiCasa developer API](https://www.cubi.casa/developers/)
- [Polycam floor plans](https://poly.cam/floor-plans)
