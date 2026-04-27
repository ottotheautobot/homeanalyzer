"""Modal worker: measured floor-plan reconstruction from a tour video.

Phased build:
  - Phase 1: infrastructure stub. ✓
  - Phase 2 (current): Depth Anything V2 per-frame metric depth + per-room
    geometric estimation (camera-tracking-free). Produces real polygons
    with real metric dimensions, scaled by the depth model. Quality is
    rough — accuracy ~30-50% on dimensions, but layout (which rooms exist
    and how big roughly) matches reality.
  - Phase 3: add MASt3R for inter-frame camera tracking → globally
    consistent point cloud → proper room polygons. Larger lift.

Run: `modal deploy modal_apps/floor_plan.py`
Test: `modal run modal_apps/floor_plan.py::smoke_test --house-id ... --video-storage-path ...`
"""

import io
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import modal

WEIGHTS_PATH = "/weights"
MAST3R_PATH = "/opt/mast3r"
VGGT_PATH = "/opt/vggt"
weights_vol = modal.Volume.from_name("floorplan-weights", create_if_missing=True)

# CUDA-devel base so we have nvcc available for the curope kernel build.
# `add_python` installs CPython at the requested version. PyTorch 2.4 wheels
# match CUDA 12.1, hence the matching base.
floorplan_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.0-devel-ubuntu22.04", add_python="3.11"
    )
    .apt_install(
        "git",
        "ffmpeg",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "build-essential",
        "cmake",
    )
    .pip_install(
        "torch==2.4.0",
        "torchvision==0.19.0",
        "numpy<2.0",
        "scipy",
        "scikit-image",
        "scikit-learn",
        "opencv-python-headless",
        "Pillow",
        "shapely",
        "trimesh",
        "supabase",
        "httpx",
        "transformers>=4.45",
        "accelerate",
        "huggingface_hub",
        "safetensors",
        "einops",
        # MASt3R needs these
        "roma",
        "matplotlib",
        "tqdm",
        "tensorboard",
        "pyglet<2",
        "huggingface-hub[torch]",
        # Item 1: vision-labeling clusters via Claude Haiku
        "anthropic>=0.40.0",
    )
    .run_commands(
        # MASt3R is kept as a fallback path. VGGT is the primary reconstruction
        # primitive — single forward pass, commercial-licensed checkpoint,
        # better point tracks for view-association.
        f"git clone --recursive https://github.com/naver/mast3r {MAST3R_PATH}",
        f"pip install -r {MAST3R_PATH}/requirements.txt || true",
        f"pip install -r {MAST3R_PATH}/dust3r/requirements.txt || true",
        # Build curope CUDA kernel for MASt3R's RoPE2D — cheap and prevents
        # the pure-PyTorch fallback when MASt3R fires as a fallback.
        (
            "cd " + MAST3R_PATH + "/dust3r/croco/models/curope && "
            "CC=gcc CXX=g++ "
            "TORCH_CUDA_ARCH_LIST=8.6 "
            "FORCE_CUDA=1 "
            "python setup.py build_ext --inplace"
        ),
        # VGGT — primary reconstruction primitive (commercial license).
        # Repo bundles only the package code; weights pull lazily from HF
        # using the HF_TOKEN secret, cached to /weights/vggt across runs.
        f"git clone https://github.com/facebookresearch/vggt {VGGT_PATH}",
        f"pip install -r {VGGT_PATH}/requirements.txt || true",
    )
    .env(
        {
            "PYTHONPATH": (
                f"{VGGT_PATH}:{MAST3R_PATH}:{MAST3R_PATH}/dust3r:"
                f"{MAST3R_PATH}/dust3r/croco"
            )
        }
    )
)

app = modal.App("homeanalyzer-floorplan")


@app.function(
    image=floorplan_image,
    gpu="A10G",
    timeout=1800,
    volumes={WEIGHTS_PATH: weights_vol},
    secrets=[
        modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"]),
        modal.Secret.from_name(
            "supabase-service-role",
            required_keys=["SUPABASE_URL", "SUPABASE_SECRET_KEY"],
        ),
        modal.Secret.from_name(
            "anthropic", required_keys=["ANTHROPIC_API_KEY"]
        ),
    ],
    cpu=4.0,
    memory=16384,
)
def reconstruct_floor_plan(
    house_id: str,
    video_storage_path: str,
    schematic: dict | None = None,
    max_frames: int = 36,
) -> dict:
    log = _setup_logging()
    log.info(
        "reconstruct house=%s video=%s max_frames=%d schematic_rooms=%d",
        house_id,
        video_storage_path,
        max_frames,
        len(schematic.get("rooms", [])) if schematic else 0,
    )

    video_bytes = _download_video(video_storage_path, log)
    log.info("video downloaded: %d bytes", len(video_bytes))

    duration_s = _probe_duration(video_bytes, log)
    log.info("video duration: %.2fs", duration_s)

    frames = _sample_keyframes(video_bytes, max_frames, log)
    log.info("sampled %d keyframes", len(frames))

    if not frames:
        return _placeholder_plan(
            schematic,
            confidence="low",
            notes="No usable frames extracted from video.",
            stats={"frames": 0},
        )

    # Estimate per-frame timestamps: assume uniform sampling across the video.
    n = len(frames)
    frame_timestamps = [duration_s * (i + 0.5) / n for i in range(n)]

    rooms_meta = (schematic or {}).get("rooms") or []
    doors_meta = (schematic or {}).get("doors") or []

    # v2.0: try VGGT first — single forward pass, commercial license,
    # better view-association via per-pixel depth confidence.
    scene = None
    primitive = None
    try:
        scene = _run_vggt(frames, log)
        if scene is not None:
            primitive = "vggt"
    except Exception:
        log.exception("vggt failed; falling back to mast3r")

    if scene is None:
        try:
            scene = _run_mast3r(frames, log)
            if scene is not None:
                primitive = "mast3r"
        except Exception:
            log.exception("mast3r failed; will fall back to depth-only path")

    if scene is not None:
        # Tier 1: intrinsic segmentation — cluster camera trajectory + label
        # via Claude vision. Independent of the schematic's time windows.
        try:
            plan = _build_intrinsic_plan(scene, frames, log)
            plan["stats"] = {
                "frames": len(frames),
                "duration_s": duration_s,
                "points_total": int(scene["n_points"]),
                "rooms_with_data": sum(
                    1 for r in plan["rooms"] if r.get("sample_count", 0) > 0
                ),
                "tier": "intrinsic",
                "primitive": primitive,
            }
            # Tag the model version with the primitive so we can filter rerun
            # candidates later without re-deriving from stats.
            plan["model_version"] = (
                f"{primitive}-intrinsic.v2.5"
                if primitive == "vggt"
                else plan.get("model_version", "mast3r-intrinsic.v1.8")
            )
            # Bubble up multi-story signal so the frontend can render tabs
            # without re-deriving from per-room floor tags.
            unique_floors = sorted({r.get("floor", 1) for r in plan["rooms"]})
            plan["floors_detected"] = len(unique_floors)
            plan["floor_indices"] = unique_floors
            return plan
        except Exception:
            log.exception(
                "intrinsic segmentation failed; falling back to schematic-driven"
            )

        # Tier 2: schematic-driven (the v1.5 path). Uses room time windows.
        if rooms_meta:
            try:
                plan = _build_mast3r_plan(
                    scene, frame_timestamps, rooms_meta, doors_meta, log
                )
                plan["stats"] = {
                    "frames": len(frames),
                    "duration_s": duration_s,
                    "points_total": int(scene["n_points"]),
                    "rooms_with_data": sum(
                        1 for r in plan["rooms"] if r.get("sample_count", 0) > 0
                    ),
                    "tier": "mast3r-schematic",
                    "primitive": primitive,
                }
                return plan
            except Exception:
                log.exception(
                    "mast3r schematic plan failed; falling back to depth-only"
                )

    # Phase 2 fallback: per-frame metric depth via Depth Anything V2.
    try:
        depth_results = _run_depth(frames, log)
    except Exception as e:
        log.exception("depth model failed")
        return _placeholder_plan(
            schematic,
            confidence="low",
            notes=f"Depth estimation failed: {e}",
            stats={"frames": len(frames), "error": str(e)},
        )

    if not rooms_meta:
        return _placeholder_plan(
            schematic,
            confidence="low",
            notes="No schematic rooms to anchor measurements to.",
            stats={"frames": len(frames)},
        )

    measured_rooms = _measure_rooms(
        rooms_meta, frame_timestamps, depth_results, log
    )
    placed = _place_rooms(measured_rooms, doors_meta, log)

    return {
        "rooms": placed["rooms"],
        "doors": placed["doors"],
        "scale_m_per_unit": 1.0,
        "confidence": "low",
        "notes": (
            "Reconstructed from monocular depth without camera tracking — "
            "dimensions are approximate. Layout follows the schematic "
            "adjacency graph (MASt3R reconstruction was unavailable)."
        ),
        "model_version": "depth-anything-v2.v1",
        "stats": {
            "frames": len(frames),
            "duration_s": duration_s,
            "rooms_with_data": sum(1 for r in measured_rooms if r["sample_count"] > 0),
        },
    }


# ---------------------------------------------------------------------------
# Helpers (run inside the Modal container)
# ---------------------------------------------------------------------------


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger("floorplan")


def _download_video(storage_path: str, log) -> bytes:
    from supabase import create_client

    sb = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    )
    log.info("downloading %s from tour-audio bucket", storage_path)
    return sb.storage.from_("tour-audio").download(storage_path)


def _probe_duration(video_bytes: bytes, log) -> float:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        path = f.name
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            timeout=30,
        )
        out = r.stdout.decode("utf-8", "ignore").strip()
        return float(out) if out else 0.0
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _sample_keyframes(video_bytes: bytes, max_frames: int, log) -> list[bytes]:
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.mp4")
        out_pattern = os.path.join(td, "f-%04d.jpg")
        with open(in_path, "wb") as f:
            f.write(video_bytes)

        # Try uniform sampling first — for short videos, scene-detect can
        # under-produce. Uniform gives us predictable coverage.
        cmd = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            in_path,
            "-vf",
            f"fps=fps={max_frames}/{max(1, _probe_duration_safe(in_path))},scale=512:-2",
            "-vsync",
            "vfr",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "5",
            out_pattern,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
        if r.returncode != 0:
            log.error("ffmpeg failed: %s", r.stderr.decode("utf-8", "ignore")[:500])

        files = sorted(p for p in os.listdir(td) if p.startswith("f-"))
        if len(files) < max(8, max_frames // 4):
            # Fallback: simpler uniform-N sample by select expression
            log.info("primary sample under-produced (%d), retrying with fps=2", len(files))
            cmd2 = [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                in_path,
                "-vf",
                "fps=2,scale=512:-2",
                "-vsync",
                "vfr",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "5",
                out_pattern,
            ]
            subprocess.run(cmd2, capture_output=True, timeout=600, check=False)
            files = sorted(p for p in os.listdir(td) if p.startswith("f-"))

        return [Path(td, fn).read_bytes() for fn in files]


def _probe_duration_safe(path: str) -> float:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            timeout=10,
        )
        out = r.stdout.decode("utf-8", "ignore").strip()
        return float(out) if out else 1.0
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# MASt3R reconstruction (Phase 3)
# ---------------------------------------------------------------------------


def _run_vggt(frames: list[bytes], log) -> dict | None:
    """Single-pass reconstruction via VGGT-1B-Commercial.

    Returns the same dict shape as _run_mast3r so the rest of the pipeline
    is reconstruction-primitive-agnostic:
        pts3d:    list of (N, 3) per-frame world-coord points
        confs:    list of (N,) per-point confidence
        poses:    (F, 4, 4) cam-to-world (OpenCV convention -> our convention)
        focals:   (F,) per-frame focal length in pixels
        n_points: total kept-point count

    VGGT vs MASt3R upsides for our pipeline:
      - Single forward pass on all frames at once (no pairwise + sparse_ga).
        Roughly 2-3x faster end-to-end on 36 frames.
      - Per-pixel depth confidence is well-calibrated — useful for the
        view-association tightening planned for v2.x.
      - Commercial license (vs. CC-BY-NC for the public MASt3R weights).
    """
    import os
    import sys
    import tempfile

    import numpy as np
    import torch
    from PIL import Image

    sys.path.insert(0, VGGT_PATH)
    from vggt.models.vggt import VGGT  # type: ignore
    from vggt.utils.geometry import unproject_depth_map_to_point_map  # type: ignore
    from vggt.utils.load_fn import load_and_preprocess_images  # type: ignore
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri  # type: ignore

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = (
        torch.bfloat16
        if torch.cuda.is_available()
        and torch.cuda.get_device_capability()[0] >= 8
        else torch.float16
    )

    cache_dir = f"{WEIGHTS_PATH}/vggt"
    os.makedirs(cache_dir, exist_ok=True)
    os.environ.setdefault("HF_HOME", cache_dir)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)

    log.info(
        "loading VGGT-1B-Commercial on %s (dtype=%s)", device, dtype
    )
    hf_token = os.environ.get("HF_TOKEN")
    model = VGGT.from_pretrained(
        "facebook/VGGT-1B-Commercial",
        token=hf_token,
        cache_dir=cache_dir,
    ).to(device)
    model.eval()

    with tempfile.TemporaryDirectory() as td:
        paths = []
        for i, fb in enumerate(frames):
            p = os.path.join(td, f"f-{i:04d}.jpg")
            with open(p, "wb") as f:
                f.write(fb)
            paths.append(p)
        log.info("VGGT: loading %d frames", len(paths))
        images = load_and_preprocess_images(paths).to(device)
        # Original (height, width) before preprocessing — VGGT pose decoder
        # wants the *processed* image shape, which is what `images` reports.
        img_shape = images.shape[-2:]

        with torch.no_grad():
            with torch.cuda.amp.autocast(dtype=dtype):
                images_b = images[None]  # add batch dim
                tokens, ps_idx = model.aggregator(images_b)

            pose_enc = model.camera_head(tokens)[-1]
            extrinsic, intrinsic = pose_encoding_to_extri_intri(
                pose_enc, img_shape
            )
            depth_map, depth_conf = model.depth_head(tokens, images_b, ps_idx)
            log.info(
                "VGGT: depth %s conf %s extr %s intr %s",
                tuple(depth_map.shape),
                tuple(depth_conf.shape),
                tuple(extrinsic.shape),
                tuple(intrinsic.shape),
            )
            # Unproject depth into world-coord points (recommended over
            # the model's point_head — the README calls this more accurate).
            pm_np = unproject_depth_map_to_point_map(
                depth_map.squeeze(0),
                extrinsic.squeeze(0),
                intrinsic.squeeze(0),
            )

    # Coerce everything to plain numpy + (per-frame) flat (N,3) / (N,) shapes,
    # matching _run_mast3r's contract.
    if isinstance(pm_np, torch.Tensor):
        pm_np = pm_np.detach().cpu().numpy()
    pm_np = np.asarray(pm_np)  # (F, H, W, 3)
    conf_np = depth_conf.squeeze(0).detach().to(torch.float32).cpu().numpy()
    extr_np = extrinsic.squeeze(0).detach().to(torch.float32).cpu().numpy()
    intr_np = intrinsic.squeeze(0).detach().to(torch.float32).cpu().numpy()

    # extrinsic is world->camera (OpenCV / world-from-camera flipped). Invert
    # to get cam->world poses, in the same convention _run_mast3r returned.
    F = extr_np.shape[0]
    cam2w = np.zeros((F, 4, 4), dtype=np.float32)
    cam2w[:, 3, 3] = 1.0
    for i in range(F):
        # extr is 3x4 [R|t]. Build 4x4 then invert.
        E = np.eye(4, dtype=np.float32)
        E[:3, :4] = extr_np[i]
        cam2w[i] = np.linalg.inv(E)

    pts3d = [pm_np[i].reshape(-1, 3).astype(np.float32) for i in range(F)]
    confs = [conf_np[i].reshape(-1).astype(np.float32) for i in range(F)]
    focals = intr_np[:, 0, 0].astype(np.float32)
    n_points = sum(int(p.shape[0]) for p in pts3d)

    # VGGT outputs are scale-normalized (NOT metric meters). Calibrate to
    # metric by assuming the camera was held at ~1.4m above the floor —
    # typical handheld phone height.
    #
    # For multi-story tours we have to detect bimodality BEFORE scaling,
    # otherwise the median camera height lands between the two floors
    # and the resulting scale compresses the real 2.7m floor gap below
    # our detection threshold. So:
    #   1. Detect bimodal cam-up distribution in raw space.
    #   2. If multi-story → scale using FLOOR 1's median camera height
    #      (the lower mode) so each floor lands at the correct absolute
    #      Z. Tag each frame with floor_idx.
    #   3. If single-story → scale using all cameras' median height as
    #      before.
    cam_pos = cam2w[:, :3, 3]  # (F, 3)
    all_xyz = np.concatenate(pts3d, axis=0)
    cam_var = np.var(cam_pos, axis=0)
    up_axis = int(np.argmin(cam_var))
    pt_up = all_xyz[:, up_axis]
    cam_up = cam_pos[:, up_axis]
    floor_up = float(np.percentile(pt_up, 5))

    # Geometric multi-story detection (v2.2-v2.4) was unreliable:
    # bimodality in the raw cam-up distribution can come from real floor
    # changes OR from camera tilt within a single floor (looking up at
    # ceilings, down at the floor). Without more multi-story tours to
    # tune against, we hand floor-tagging entirely to the frontend's
    # schematic-label parser, which keys on Sonnet's "upstairs",
    # "first-floor", etc. — a deterministic signal from the transcript.
    floor_assignments = None
    cam_up_med_for_scale = float(np.median(cam_up))

    rel_height = abs(cam_up_med_for_scale - floor_up)
    if rel_height < 1e-3:
        log.warning(
            "VGGT scale calibration: camera height delta near zero (%.5f); "
            "skipping rescale",
            rel_height,
        )
        scale = 1.0
    else:
        TARGET_CAM_HEIGHT_M = 1.4
        scale = TARGET_CAM_HEIGHT_M / rel_height
    log.info(
        "VGGT scale calibration: up_axis=%d floor_up=%.4f cam_up_med=%.4f "
        "delta=%.4f scale=%.4f",
        up_axis,
        floor_up,
        cam_up_med_for_scale,
        rel_height,
        scale,
    )
    if not (0.01 < scale < 100):
        log.warning("scale out of plausible range; clamping to 1.0")
        scale = 1.0

    # Apply scale to points and camera translations.
    pts3d = [p * scale for p in pts3d]
    cam2w = cam2w.copy()
    cam2w[:, :3, 3] *= scale

    log.info(
        "VGGT: %d frames, %d total points, focal=%.1fpx, scale_applied=%.3f",
        F,
        n_points,
        float(focals.mean()),
        scale,
    )

    del model
    torch.cuda.empty_cache()

    return {
        "pts3d": pts3d,
        "confs": confs,
        "poses": cam2w,
        "focals": focals,
        "n_points": n_points,
        # Pre-computed multi-story signal from raw (pre-scale) cam-up
        # distribution. None for single-story tours; a list of 1-based
        # floor indices per frame for multi-story.
        "floor_assignments": floor_assignments,
    }


def _run_mast3r(frames: list[bytes], log) -> dict | None:
    """Run MASt3R sparse global alignment on the sampled frames.

    Returns a dict with:
        pts3d:        list of (H, W, 3) float arrays in world coords (metric m)
        confs:        list of (H, W) float arrays — per-point confidence
        poses:        (N, 4, 4) camera-to-world poses
        focals:       (N,) per-frame focal length in pixels
        n_points:     total point count summed across frames
    Coordinate convention: as returned by MASt3R — Y-down typically; we infer
    the up-axis from the floor plane fit later.
    """
    import numpy as np
    import torch

    sys.path.insert(0, MAST3R_PATH)
    sys.path.insert(0, f"{MAST3R_PATH}/dust3r")
    sys.path.insert(0, f"{MAST3R_PATH}/dust3r/croco")
    from dust3r.image_pairs import make_pairs  # type: ignore
    from dust3r.utils.image import load_images  # type: ignore
    from mast3r.cloud_opt.sparse_ga import sparse_global_alignment  # type: ignore
    from mast3r.model import AsymmetricMASt3R  # type: ignore

    device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_dir = f"{WEIGHTS_PATH}/mast3r"
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["HF_HOME"] = cache_dir
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)

    log.info("loading MASt3R metric model on %s", device)
    model = AsymmetricMASt3R.from_pretrained(
        "naver/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric"
    ).to(device)
    model.eval()

    with tempfile.TemporaryDirectory() as td:
        # Write frame bytes to disk so dust3r's load_images() can find them.
        paths = []
        for i, fb in enumerate(frames):
            p = os.path.join(td, f"f-{i:04d}.jpg")
            with open(p, "wb") as f:
                f.write(fb)
            paths.append(p)

        images = load_images(paths, size=512, verbose=False)
        log.info("loaded %d images at 512px for MASt3R", len(images))

        # Sliding window: each frame paired with its 3 neighbors on each side.
        # For sequential video this is plenty — non-adjacent frames rarely
        # have enough overlap to add useful constraints.
        pairs = make_pairs(
            images, scene_graph="swin-3", prefilter=None, symmetrize=True
        )
        log.info(
            "built %d image pairs (swin-3 symmetrized) — running sparse global alignment",
            len(pairs),
        )

        ga_cache = os.path.join(td, "ga_cache")
        os.makedirs(ga_cache, exist_ok=True)
        # MASt3R's sparse_global_alignment runs the pairwise forward pass
        # internally (forward_mast3r) and then optimizes the global scene.
        scene = sparse_global_alignment(
            paths,
            pairs,
            ga_cache,
            model,
            lr1=0.07,
            niter1=300,
            lr2=0.014,
            niter2=300,
            device=device,
            opt_depth=True,
            shared_intrinsics=True,
            matching_conf_thr=5.0,
        )
        log.info("global alignment complete")

        # MASt3R returns dense per-frame pointmaps via get_dense_pts3d().
        # Each call returns (pts3d_list, depths, confs). pts3d items are
        # flat (N, 3) per frame; confs are aligned with pts3d (1D).
        dense_pts, _depths, dense_confs = scene.get_dense_pts3d()
        pts3d = [p.detach().cpu().numpy().reshape(-1, 3) for p in dense_pts]
        confs = [c.detach().cpu().numpy().reshape(-1) for c in dense_confs]
        poses = scene.cam2w.detach().cpu().numpy()
        # intrinsics is a list of (3, 3) — pull focal from each.
        focals = np.array(
            [
                float(intr[0, 0].detach().cpu().item())
                for intr in scene.intrinsics
            ]
        )

        n_points = sum(int(p.shape[0]) for p in pts3d)
        log.info(
            "scene: %d frames, %d total points, focal=%.1fpx",
            len(pts3d),
            n_points,
            float(np.mean(focals)) if focals.ndim else float(focals),
        )

        # Free GPU memory before we leave the worker.
        del scene
        del model
        torch.cuda.empty_cache()

        return {
            "pts3d": pts3d,
            "confs": confs,
            "poses": poses,
            "focals": focals,
            "n_points": n_points,
        }


# ---------------------------------------------------------------------------
# Tier 1: intrinsic segmentation (no dependence on schematic time windows)
# ---------------------------------------------------------------------------


def _build_intrinsic_plan(scene: dict, frames: list[bytes], log) -> dict:
    """Segment + label rooms purely from MASt3R's reconstruction.

    v1.7 pipeline:
      1. Floor-plane fit + rotate so floor sits at Z=0.
      2. Manhattan-axis alignment: rotate XY so dominant wall direction
         lies along X. All rooms then share orientation.
      3. Camera-trajectory clustering (DBSCAN on cam XY).
      4. Per cluster: gather wall-height points VISIBILITY-FILTERED to
         the cluster's cameras, then axis-aligned bbox.
      5. Iterative overlap merge: pairs of clusters whose bboxes overlap
         by IoU > 0.3 collapse into one room — fixes the case where MASt3R
         wall-leakage through doorways spawned a duplicate "room" for what
         is geometrically the same physical space.
      6. Vision-label each surviving cluster via Claude Haiku.
      7. Door detection from trajectory crossings, deduped + capped at
         ~1.5 × num_rooms (typical houses don't have more).
      8. Confidence recalibration: rooms with physically-implausible
         dimensions for their vision label get downgraded.
    """
    import numpy as np

    pts3d_list = scene["pts3d"]
    confs_list = scene["confs"]
    poses = scene["poses"]

    # Aggregate confident points + per-point frame attribution.
    # Use a percentile-based filter so this works regardless of which
    # reconstruction primitive produced confs (MASt3R's clean_pointcloud
    # confs are on a ~1-10 scale; VGGT's depth_conf is a different
    # distribution entirely). Keep the top 50% per frame.
    CONF_KEEP_PCT = 50.0
    all_pts = []
    all_frame_idx = []
    for i, (pts, conf) in enumerate(zip(pts3d_list, confs_list)):
        flat_pts = pts.reshape(-1, 3)
        flat_conf = conf.reshape(-1)
        if flat_conf.size == 0:
            continue
        thr = float(np.percentile(flat_conf, 100 - CONF_KEEP_PCT))
        keep = flat_conf >= thr
        if not keep.any():
            continue
        kp = flat_pts[keep]
        all_pts.append(kp)
        all_frame_idx.append(np.full(kp.shape[0], i, dtype=np.int32))
    if not all_pts:
        raise RuntimeError("reconstruction returned no usable points")
    all_pts = np.concatenate(all_pts, axis=0)
    all_frame_idx = np.concatenate(all_frame_idx, axis=0)
    log.info(
        "kept %d points across %d frames (top %.0f%% by confidence per frame)",
        all_pts.shape[0],
        len(pts3d_list),
        CONF_KEEP_PCT,
    )

    # 1. Floor plane fit + rotate to floor-up.
    floor = _find_floor(all_pts, poses, log)
    R_world = floor["R"]
    floor_z = floor["z"]
    aligned_pts = (R_world @ all_pts.T).T
    aligned_pts[:, 2] -= floor_z
    cam_centers = poses[:, :3, 3]
    aligned_cams = (R_world @ cam_centers.T).T
    aligned_cams[:, 2] -= floor_z

    # 2. Manhattan alignment from wall-height points.
    wall_mask = (aligned_pts[:, 2] > 0.3) & (aligned_pts[:, 2] < 2.4)
    wall_xy = aligned_pts[wall_mask][:, :2]
    R_man = _manhattan_rotation(wall_xy, log)
    aligned_pts[:, :2] = aligned_pts[:, :2] @ R_man.T
    aligned_cams[:, :2] = aligned_cams[:, :2] @ R_man.T
    log.info("manhattan rotation applied")

    # 2.5. Multi-story segmentation. Prefer the primitive's pre-computed
    # floor assignments when present (VGGT detects bimodality in raw,
    # pre-scale-calibration space, where the real floor gap isn't
    # compressed by our 1.4m camera-height assumption). Fall back to
    # detecting from scaled aligned_cams for primitives that don't
    # provide assignments.
    pre_assignments = scene.get("floor_assignments")
    if pre_assignments is not None and len(pre_assignments) == len(aligned_cams):
        import numpy as np  # noqa: F811

        floors = []
        for f_idx in sorted(set(pre_assignments)):
            f_frame_idxs = [
                i for i, a in enumerate(pre_assignments) if a == f_idx
            ]
            if not f_frame_idxs:
                continue
            f_z = aligned_cams[f_frame_idxs, 2]
            floors.append(
                {
                    "floor_idx": f_idx,
                    "z_min": float(f_z.min()),
                    "z_max": float(f_z.max()),
                    "frame_indices": f_frame_idxs,
                }
            )
        log.info(
            "using pre-computed floor assignments from primitive: %d floor(s)",
            len(floors),
        )
    else:
        floors = _detect_floors(aligned_cams[:, 2], log)
    log.info(
        "detected %d floor(s): %s",
        len(floors),
        [
            (f["floor_idx"], f["z_min"], f["z_max"], len(f["frame_indices"]))
            for f in floors
        ],
    )

    # 3-5. Per-floor: cluster cameras, build cluster rooms, merge overlaps.
    # Each room gets a `floor` tag so the frontend can render multi-story
    # tours as tabs / per-floor sections instead of stacking them in one
    # plane (which was producing nonsense for two-story houses where the
    # camera traversed both floors).
    rooms_raw = []
    for floor in floors:
        floor_idx = floor["floor_idx"]
        floor_frame_idxs = floor["frame_indices"]
        if not floor_frame_idxs:
            continue
        floor_z_offset = floor["z_min"]
        floor_cam_xy = aligned_cams[floor_frame_idxs, :2]
        # Cluster within this floor only.
        sub_clusters = _cluster_cameras(floor_cam_xy, log)
        if not sub_clusters:
            log.info("floor %d: no clusters", floor_idx)
            continue
        log.info(
            "floor %d: %d clusters from %d frames",
            floor_idx,
            len(sub_clusters),
            len(floor_frame_idxs),
        )
        floor_rooms = []
        for sub_cid, sub_idxs in sorted(sub_clusters.items()):
            # Indexes are into floor_frame_idxs — remap to global frame indices.
            global_idxs = [int(floor_frame_idxs[i]) for i in sub_idxs]
            cid = f"f{floor_idx}.c{sub_cid}"
            room = _compute_cluster_room(
                cid,
                global_idxs,
                aligned_pts,
                all_frame_idx,
                aligned_cams,
                log,
                floor_z_offset=floor_z_offset,
            )
            if room is not None:
                room["floor"] = floor_idx
                floor_rooms.append(room)
        # Merge overlaps within this floor.
        floor_rooms = _merge_overlapping_clusters(
            floor_rooms, aligned_pts, all_frame_idx, aligned_cams, log
        )
        rooms_raw.extend(floor_rooms)

    if not rooms_raw:
        raise RuntimeError("no rooms produced after clustering")

    # 6. Vision-label each cluster.
    labels = _label_clusters_via_vision(rooms_raw, frames, log)
    rooms_out = []
    for r, label in zip(rooms_raw, labels):
        rooms_out.append(
            {
                "id": f"r{r['cluster_id']}",
                "label": label,
                "polygon_m": r["polygon_m"],
                "width_m": r["width_m"],
                "depth_m": r["depth_m"],
                "confidence": r["confidence"],
                "sample_count": r["sample_count"],
                "source": r["source"],
                "floor": r.get("floor", 1),
            }
        )

    # 7. Detect + dedupe + cap doors.
    final_clusters = {r["cluster_id"]: r["frame_indices"] for r in rooms_raw}
    doors_out = _detect_doors_from_trajectory(
        aligned_cams[:, :2], final_clusters, rooms_out, log
    )
    doors_out = _cap_doors(doors_out, len(rooms_out), log)

    # Normalize: shift rooms + doors so global min is at origin.
    rooms_out, offset = _normalize_origin_with_offset(rooms_out)
    for d in doors_out:
        d["x_m"] = float(d["x_m"] - offset[0])
        d["z_m"] = float(d["z_m"] - offset[1])

    # 8. Confidence recalibration based on label-vs-dimension sanity.
    rooms_out, any_downgraded = _recalibrate_confidence(rooms_out, log)

    if any_downgraded or all(r.get("confidence", 0) < 0.5 for r in rooms_out):
        confidence_label = "low"
    elif sum(1 for r in rooms_out if r.get("confidence", 0) >= 0.7) >= max(
        1, len(rooms_out) // 2
    ):
        confidence_label = "high"
    else:
        confidence_label = "medium"

    return {
        "rooms": rooms_out,
        "doors": doors_out,
        "scale_m_per_unit": 1.0,
        "confidence": confidence_label,
        "notes": (
            "Reconstructed from tour video via MASt3R + intrinsic camera-cluster "
            "segmentation + vision labeling. v1.7 adds visibility filtering, "
            "overlap merging, door capping, and dimension-based confidence "
            "downgrades. Polygons are axis-aligned in a Manhattan-rotated world."
        ),
        "model_version": "mast3r-intrinsic.v1.8",
    }


# ---------------------------------------------------------------------------
# v2.2 multi-story detection
# ---------------------------------------------------------------------------


# Floors are considered distinct if the K-means cluster centers on camera Z
# are at least this far apart (in scaled meters). Real floor-to-floor in a
# typical house is ~2.7m; VGGT scale compression on multi-story tours makes
# it land around 1.5-2.5m. 1.0m turned out to fire on single-story tours
# where the user just looked up at ceilings and down at floors (creating
# bimodal Z distribution within one floor). 1.8m is the v2.3 threshold.
_MULTI_STORY_MIN_GAP_M = 1.8
# Don't even try multi-story detection if the camera Z span is below this —
# people don't walk up/down 2m on one floor.
_MULTI_STORY_MIN_SPAN_M = 2.0
# Each floor must have at least this many frames for the split to count.
# Catches the case where the camera lifted briefly (e.g. looking up at a
# vaulted ceiling) and a few stray frames pull a "second floor" out of a
# single-story tour.
_MULTI_STORY_MIN_FRAMES_PER_FLOOR = 5


def _detect_floors(cam_z, log) -> list[dict]:
    """Detect distinct floors from the camera Z distribution.

    Returns a list of dicts, oldest-floor (lowest Z) first:
        {
            "floor_idx": 1, 2, ...,
            "z_min": float,
            "z_max": float,
            "frame_indices": [int, ...],  # indexes into cam_z / aligned_cams
        }

    Single-story tours return a one-element list.
    """
    import numpy as np

    n = len(cam_z)
    if n == 0:
        return []
    z = np.asarray(cam_z, dtype=float)
    span = float(z.max() - z.min())
    if span < _MULTI_STORY_MIN_SPAN_M:
        return [
            {
                "floor_idx": 1,
                "z_min": float(z.min()),
                "z_max": float(z.max()),
                "frame_indices": list(range(n)),
            }
        ]

    # 1D K-means with k=2 to test for bimodality.
    try:
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=2, n_init=10, random_state=42).fit(z.reshape(-1, 1))
    except Exception:
        log.exception("KMeans for multi-story detection failed; assuming single-story")
        return [
            {
                "floor_idx": 1,
                "z_min": float(z.min()),
                "z_max": float(z.max()),
                "frame_indices": list(range(n)),
            }
        ]

    centers = km.cluster_centers_.flatten()
    gap = abs(float(centers[0] - centers[1]))
    if gap < _MULTI_STORY_MIN_GAP_M:
        log.info(
            "multi-story rejected: cluster gap %.2fm < %.2fm threshold",
            gap,
            _MULTI_STORY_MIN_GAP_M,
        )
        return [
            {
                "floor_idx": 1,
                "z_min": float(z.min()),
                "z_max": float(z.max()),
                "frame_indices": list(range(n)),
            }
        ]

    # Reassign labels so floor 1 is the lower cluster.
    labels = km.labels_.copy()
    if centers[0] > centers[1]:
        labels = 1 - labels

    floor_idxs_lists = [
        [i for i in range(n) if labels[i] == f] for f in (0, 1)
    ]
    # Reject the split if either cluster has too few frames — that's the
    # signature of a single-story tour where the camera briefly lifted.
    counts = [len(idxs) for idxs in floor_idxs_lists]
    if min(counts) < _MULTI_STORY_MIN_FRAMES_PER_FLOOR:
        log.info(
            "multi-story rejected: smallest cluster has %d frames "
            "< %d threshold (gap=%.2fm)",
            min(counts),
            _MULTI_STORY_MIN_FRAMES_PER_FLOOR,
            gap,
        )
        return [
            {
                "floor_idx": 1,
                "z_min": float(z.min()),
                "z_max": float(z.max()),
                "frame_indices": list(range(n)),
            }
        ]

    floors = []
    for f, idxs in enumerate(floor_idxs_lists):
        if not idxs:
            continue
        f_z = z[idxs]
        floors.append(
            {
                "floor_idx": f + 1,
                "z_min": float(f_z.min()),
                "z_max": float(f_z.max()),
                "frame_indices": idxs,
            }
        )
    log.info(
        "MULTI-STORY DETECTED: %d floors, gap=%.2fm, span=%.2fm, "
        "frames_per_floor=%s",
        len(floors),
        gap,
        span,
        counts,
    )
    return floors


# ---------------------------------------------------------------------------
# v1.7 helpers: per-cluster geometry, overlap merge, door cap, confidence
# ---------------------------------------------------------------------------


# Hard cap on camera-to-point distance for view-association. A point further
# than this from any camera in the cluster is almost certainly seen through
# a doorway from a neighboring room. v1.7 used 5m and saw 11.9×8m "bathrooms"
# because adjacent-room walls were still in range. v1.8 tightens to 3m —
# closer to the typical interior camera-to-wall distance in a single room.
_VIEW_ASSOC_MAX_DIST_M = 3.0


def _compute_cluster_room(
    cid,
    frame_idxs,
    aligned_pts,
    all_frame_idx,
    aligned_cams,
    log,
    floor_z_offset: float = 0.0,
):
    """Build the per-cluster room dict given its frame indices.

    Applies the v1.7 view-association filter: only keep wall-height points
    within _VIEW_ASSOC_MAX_DIST_M of any camera in this cluster.

    `floor_z_offset` is the Z value of this room's floor in the aligned
    coordinate frame. Wall-height filter is applied RELATIVE to that
    offset so multi-story tours' upper floors don't get filtered away
    by a hard-coded "0.1m to 2.2m above Z=0" mask.
    """
    import numpy as np

    frame_set = np.array(frame_idxs, dtype=np.int32)
    mask = np.isin(all_frame_idx, frame_set)
    cpts = aligned_pts[mask]
    if cpts.shape[0] > 0:
        rel_z = cpts[:, 2] - floor_z_offset
        wh = (rel_z > 0.1) & (rel_z < 2.2)
        cpts = cpts[wh]

    cam_xy = aligned_cams[frame_idxs, :2]

    # View-association: each wall point must be within R of SOME camera in
    # this cluster (XY only; we already wall-height-filtered along Z).
    if cpts.shape[0] > 0 and len(cam_xy) > 0:
        # Distance from each point to its nearest cluster camera. Brute force
        # is fine — typical sizes are ~10k pts × ~30 cams = 300k pairs.
        diffs = cpts[:, None, :2] - cam_xy[None, :, :]
        dists = np.linalg.norm(diffs, axis=2)
        nearest = dists.min(axis=1)
        keep = nearest <= _VIEW_ASSOC_MAX_DIST_M
        cpts = cpts[keep]

    if cpts.shape[0] >= 200:
        polygon, w_m, d_m = _concave_room_polygon(cpts[:, :2], log)
        confidence = 0.75 if len(frame_idxs) >= 4 else 0.5
        source = "wall-points"
    else:
        polygon, w_m, d_m = _bbox_from_camera_path(cam_xy)
        confidence = 0.3
        source = "camera-path"

    centroid = cam_xy.mean(axis=0)
    rep_local_idx = int(
        np.argmin(np.linalg.norm(cam_xy - centroid, axis=1))
    )
    rep_frame_idx = frame_idxs[rep_local_idx]
    log.info(
        "cluster %s: %d frames, %d wall pts (post-VA), source=%s, %.2fx%.2fm",
        cid,
        len(frame_idxs),
        int(cpts.shape[0]),
        source,
        w_m,
        d_m,
    )
    return {
        "cluster_id": cid,
        "frame_indices": frame_idxs,
        "polygon_m": polygon,
        "width_m": round(float(w_m), 2),
        "depth_m": round(float(d_m), 2),
        "confidence": float(confidence),
        "sample_count": len(frame_idxs),
        "source": source,
        "rep_frame_idx": rep_frame_idx,
    }


def _concave_room_polygon(xy, log) -> tuple[list, float, float]:
    """Concave hull around 2D wall-height points — produces a polygon that
    actually hugs the room shape (L-shapes, alcoves, angled walls) instead
    of an axis-aligned rectangle.

    Pipeline:
      1. Voxel-downsample to a 10cm grid so we don't choke shapely on the
         hundreds of thousands of points VGGT typically produces.
      2. shapely.concave_hull(ratio=0.15) — small ratio means a tight
         concave hull. ratio=1 would give the convex hull.
      3. Douglas-Peucker simplify at 8cm so a 6-vertex L-shape doesn't
         ship as 200 jaggy edges.

    Falls back to axis-aligned bbox if shapely fails or the hull is
    degenerate (line / single point / empty).
    Returns (polygon_corners, width_m, depth_m). Width/depth are the
    bounds-of-polygon dims — used downstream for the size-based
    confidence checks (which still operate on a rectangle envelope)."""
    import numpy as np

    if len(xy) < 4:
        return _bbox_from_camera_path(xy)

    cell = 0.10
    cells = np.floor(np.asarray(xy) / cell).astype(np.int64)
    _, unique_idx = np.unique(cells, axis=0, return_index=True)
    xy_ds = np.asarray(xy)[unique_idx]
    if len(xy_ds) < 4:
        return _axis_aligned_bbox(xy)

    try:
        from shapely import concave_hull, simplify
        from shapely.geometry import MultiPoint

        mp = MultiPoint(xy_ds.tolist())
        hull = concave_hull(mp, ratio=0.15)
        if hull.is_empty or hull.geom_type != "Polygon":
            log.info(
                "concave_hull produced %s; falling back to axis-aligned bbox",
                hull.geom_type,
            )
            return _axis_aligned_bbox(xy)
        # Simplify so a typical room comes out as ~5–12 vertices, not 200.
        hull = simplify(hull, tolerance=0.08, preserve_topology=True)
        coords = list(hull.exterior.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) < 3:
            return _axis_aligned_bbox(xy)
        polygon = [[float(x), float(y)] for x, y in coords]
        minx, miny, maxx, maxy = hull.bounds
        log.info(
            "concave hull: %d vertices, bbox %.2fx%.2fm, area=%.1fm²",
            len(polygon),
            float(maxx - minx),
            float(maxy - miny),
            float(hull.area),
        )
        return polygon, float(maxx - minx), float(maxy - miny)
    except Exception as e:
        log.warning("concave hull failed (%s); falling back to bbox", e)
        return _axis_aligned_bbox(xy)


def _polygon_iou(poly_a, poly_b) -> float:
    """True polygon IoU using shapely. Used by the overlap-merge pass —
    bbox IoU under-reports for L-shaped or angled rooms because the bbox
    of an L-room is much bigger than the L itself."""
    try:
        from shapely.geometry import Polygon

        a = Polygon(poly_a)
        b = Polygon(poly_b)
        if not (a.is_valid and b.is_valid):
            a = a.buffer(0)
            b = b.buffer(0)
        if a.is_empty or b.is_empty or a.area == 0 or b.area == 0:
            return 0.0
        inter = a.intersection(b).area
        if inter <= 0:
            return 0.0
        union = a.union(b).area
        return float(inter / max(union, 1e-9))
    except Exception:
        return 0.0


def _bbox_iou(poly_a, poly_b) -> float:
    """Legacy axis-aligned IoU. Kept for callers that explicitly want the
    bbox envelope behavior (e.g. checking if two rooms' bounding rectangles
    overlap, regardless of their actual shape)."""
    import numpy as np

    a = np.array(poly_a, dtype=float)
    b = np.array(poly_b, dtype=float)
    a_min, a_max = a.min(0), a.max(0)
    b_min, b_max = b.min(0), b.max(0)
    inter_min = np.maximum(a_min, b_min)
    inter_max = np.minimum(a_max, b_max)
    inter_dims = np.clip(inter_max - inter_min, 0, None)
    inter = float(inter_dims.prod())
    if inter <= 0:
        return 0.0
    a_area = float((a_max - a_min).prod())
    b_area = float((b_max - b_min).prod())
    return inter / max(a_area + b_area - inter, 1e-9)


# v1.8 merge thresholds. Both must hold for two clusters to collapse:
#   - bbox IoU > 0.5 (was 0.3 in v1.7 → cascaded all 5 Savannah rooms to 1)
#   - camera centroids within 2m of each other (the "are we actually in the
#     same physical space" check). Adjacent rooms' bboxes can touch but
#     their cameras are clearly in separate spots.
_OVERLAP_IOU_THR = 0.5
_OVERLAP_CENTROID_DIST_M = 2.0


def _cluster_centroid(room, aligned_cams):
    """Camera-position centroid for a cluster (XY only)."""
    import numpy as np

    cam_xy = aligned_cams[room["frame_indices"], :2]
    return cam_xy.mean(axis=0)


def _merge_overlapping_clusters(
    rooms_raw, aligned_pts, all_frame_idx, aligned_cams, log
):
    """Iteratively merge cluster pairs that geometrically AND spatially are
    the same physical room.

    Geometric: bbox IoU > _OVERLAP_IOU_THR — handles MASt3R wall-leakage
    attaching the same wall points to two clusters.
    Spatial: camera centroids within _OVERLAP_CENTROID_DIST_M — guards
    against cascading merges across genuinely separate adjacent rooms
    whose bboxes happen to overlap because of leftover view-leakage."""
    import numpy as np

    if len(rooms_raw) <= 1:
        return rooms_raw
    rooms = list(rooms_raw)
    while True:
        best_score = 0.0
        best_pair = None
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                iou = _polygon_iou(rooms[i]["polygon_m"], rooms[j]["polygon_m"])
                if iou <= _OVERLAP_IOU_THR:
                    continue
                ca = _cluster_centroid(rooms[i], aligned_cams)
                cb = _cluster_centroid(rooms[j], aligned_cams)
                cdist = float(np.linalg.norm(ca - cb))
                if cdist > _OVERLAP_CENTROID_DIST_M:
                    continue
                # Score by IoU; ties broken by smaller centroid distance.
                score = iou - cdist * 0.01
                if score > best_score:
                    best_score = score
                    best_pair = (i, j, iou, cdist)
        if best_pair is None:
            break
        i, j, iou, cdist = best_pair
        a, b = rooms[i], rooms[j]
        log.info(
            "merging clusters %s + %s (IoU=%.2f, centroid_dist=%.2fm, frames %d+%d)",
            a["cluster_id"],
            b["cluster_id"],
            iou,
            cdist,
            len(a["frame_indices"]),
            len(b["frame_indices"]),
        )
        if len(a["frame_indices"]) >= len(b["frame_indices"]):
            keep_id = a["cluster_id"]
        else:
            keep_id = b["cluster_id"]
        merged_frames = sorted(set(a["frame_indices"]) | set(b["frame_indices"]))
        merged = _compute_cluster_room(
            keep_id, merged_frames, aligned_pts, all_frame_idx, aligned_cams, log
        )
        rooms.pop(j)
        rooms.pop(i)
        rooms.append(merged)
    if len(rooms) != len(rooms_raw):
        log.info(
            "overlap merge: %d clusters -> %d rooms",
            len(rooms_raw),
            len(rooms),
        )
    rooms.sort(key=lambda r: str(r["cluster_id"]))
    return rooms


def _cap_doors(doors, num_rooms, log):
    """Dedupe + cap door count at ~1.5 × num_rooms.

    Trajectory crossings can over-fire when the camera bobs back and forth
    between two clusters at a doorway. We're already deduping pairs in
    _detect_doors_from_trajectory, but if a tour visits 5 rooms in a tight
    sequence we get 4-8 pair crossings even though typical houses have 4-6
    actual doorways."""
    import math

    cap = max(1, math.ceil(num_rooms * 1.5))
    if len(doors) <= cap:
        return doors
    log.info(
        "capping doors: %d -> %d (cap = ceil(%d × 1.5))",
        len(doors),
        cap,
        num_rooms,
    )
    # Keep first N — the trajectory builder emits in time order, which is
    # a decent proxy for "actually traversed". Could weight by repeat
    # crossings later.
    return doors[:cap]


# Per-label dimension caps (meters). Rooms exceeding both width AND depth
# of these caps get confidence downgraded — they're usually wall-leakage
# blowing out the bbox into a neighboring space.
_LABEL_MAX_DIMS_M = {
    "bathroom": (4.0, 4.0),
    "closet": (3.0, 3.0),
    "laundry": (4.5, 4.5),
    "hallway": (10.0, 3.0),  # hallways can be long but should be narrow
    "entryway": (4.0, 4.0),
    "stairs": (3.0, 5.0),
}
_GLOBAL_MAX_DIM_M = 9.0
_MAX_ASPECT_RATIO = 4.0


def _recalibrate_confidence(rooms, log):
    """Downgrade confidence on rooms whose geometry is implausible for their
    vision label. Returns (rooms, any_downgraded)."""
    any_downgraded = False
    for r in rooms:
        w = float(r.get("width_m") or 0)
        d = float(r.get("depth_m") or 0)
        label = (r.get("label") or "").lower()
        reasons = []
        if max(w, d) > _GLOBAL_MAX_DIM_M:
            reasons.append(f"max-dim {max(w, d):.1f}m > {_GLOBAL_MAX_DIM_M}m")
        if min(w, d) > 0 and max(w, d) / min(w, d) > _MAX_ASPECT_RATIO:
            reasons.append(
                f"aspect {max(w, d) / min(w, d):.1f} > {_MAX_ASPECT_RATIO}"
            )
        cap = _LABEL_MAX_DIMS_M.get(label)
        if cap is not None:
            cw, cd = cap
            if w > cw and d > cd:
                reasons.append(
                    f"{label} {w:.1f}x{d:.1f} > cap {cw:.1f}x{cd:.1f}"
                )
        if reasons:
            log.info(
                "confidence DOWNGRADE r%s '%s': %s",
                r.get("id", "?"),
                label,
                "; ".join(reasons),
            )
            r["confidence"] = min(float(r.get("confidence", 0.3)), 0.3)
            any_downgraded = True
    return rooms, any_downgraded


def _manhattan_rotation(wall_xy, log):
    """Rotation matrix (2x2) that aligns dominant wall direction with the
    X axis. Uses a 1° histogram of point-to-point angles weighted by length."""
    import numpy as np

    if len(wall_xy) < 100:
        log.info("manhattan: too few wall pts, skipping rotation")
        return np.eye(2)

    # Subsample for speed.
    if len(wall_xy) > 50_000:
        idx = np.random.choice(len(wall_xy), 50_000, replace=False)
        sample = wall_xy[idx]
    else:
        sample = wall_xy

    # PCA: dominant wall direction is the *minor* axis if walls form a long
    # narrow cluster, or the *major* axis if room is elongated. Either way,
    # we want walls (the dominant linear features in the point cloud) aligned
    # with axes — and Manhattan worlds have walls along two perpendicular
    # directions, so we just need to pick *one* of them.
    centered = sample - sample.mean(axis=0)
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # eigvecs[:, 1] is the major axis. Use it as the new X axis.
    major = eigvecs[:, np.argmax(eigvals)]
    angle = float(np.arctan2(major[1], major[0]))
    # We rotate by -angle so the major axis lands on +X.
    c, s = np.cos(-angle), np.sin(-angle)
    R = np.array([[c, -s], [s, c]])
    log.info("manhattan: dominant axis at %.1f°", np.degrees(angle))
    return R


def _cluster_cameras(cam_xy, log) -> dict[int, list[int]]:
    """DBSCAN on camera XY positions. Returns cluster_id -> list of frame
    indices. cluster_id starts at 0; -1 (noise) is skipped.

    eps is adaptive: scales with the average inter-frame step. A user
    walking fast has bigger steps and needs bigger eps to keep frames in
    the same cluster; a user dwelling has small steps and benefits from
    tighter eps that splits adjacent rooms more aggressively."""
    import numpy as np
    from sklearn.cluster import DBSCAN

    n = len(cam_xy)
    if n == 0:
        return {}
    # Median per-step distance: characteristic frame-to-frame motion.
    # eps = max(1.2, 3 * median_step) bounds the floor at 1.2m so very
    # slow tours don't split single rooms, and lets eps grow naturally
    # with pace.
    if n >= 2:
        steps = np.linalg.norm(np.diff(cam_xy, axis=0), axis=1)
        median_step = float(np.median(steps[np.isfinite(steps) & (steps > 0)]) or 0.5)
    else:
        median_step = 0.5
    eps = float(np.clip(3.0 * median_step, 1.2, 3.0))
    log.info(
        "DBSCAN: median_step=%.2fm -> eps=%.2fm (n=%d)",
        median_step,
        eps,
        n,
    )
    db = DBSCAN(eps=eps, min_samples=2).fit(cam_xy)
    labels = db.labels_
    clusters: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        if lab < 0:
            continue
        clusters.setdefault(int(lab), []).append(i)

    # If everything ended up as noise (rare — happens on very fast tours),
    # fall back to time-segmented clustering: one cluster per contiguous
    # block of N frames.
    if not clusters:
        log.info("DBSCAN returned all noise; falling back to time blocks")
        block = max(3, n // 6)  # ~6 blocks
        for i in range(n):
            clusters.setdefault(i // block, []).append(i)
    return clusters


def _axis_aligned_bbox(xy):
    """Tight axis-aligned bbox in the (already-Manhattan-rotated) frame.
    Returns (polygon_4_corners, width, depth)."""
    import numpy as np

    if len(xy) < 4:
        return _bbox_from_camera_path(xy)

    lo = np.percentile(xy, 2, axis=0)
    hi = np.percentile(xy, 98, axis=0)
    pad = 0.4
    lo = lo - pad
    hi = hi + pad
    w = float(hi[0] - lo[0])
    d = float(hi[1] - lo[1])
    box = [
        [float(lo[0]), float(lo[1])],
        [float(hi[0]), float(lo[1])],
        [float(hi[0]), float(hi[1])],
        [float(lo[0]), float(hi[1])],
    ]
    return box, w, d


def _label_clusters_via_vision(rooms_raw, frames, log) -> list[str]:
    """Send each cluster's representative frame to Claude Haiku and ask
    'what room is this?'. Returns a label per cluster.

    Falls back to "room N" if Anthropic key missing or call fails."""
    import base64

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY missing; using generic labels")
        return [f"room {r['cluster_id'] + 1}" for r in rooms_raw]

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; using generic labels")
        return [f"room {r['cluster_id'] + 1}" for r in rooms_raw]

    client = anthropic.Anthropic(api_key=api_key)
    out = []
    valid_labels = {
        "living",
        "kitchen",
        "dining",
        "bedroom",
        "bathroom",
        "hallway",
        "entryway",
        "garage",
        "office",
        "laundry",
        "closet",
        "outdoor",
        "stairs",
        "other",
    }
    for r in rooms_raw:
        rep_idx = r["rep_frame_idx"]
        if rep_idx < 0 or rep_idx >= len(frames):
            out.append(f"room {r['cluster_id'] + 1}")
            continue
        img_bytes = frames[rep_idx]
        b64 = base64.standard_b64encode(img_bytes).decode("ascii")
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=20,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "This is one frame from a house tour video. "
                                    "What kind of space is this? Reply with EXACTLY ONE "
                                    "lowercase word from this list: "
                                    "living, kitchen, dining, bedroom, bathroom, "
                                    "hallway, entryway, garage, office, laundry, "
                                    "closet, outdoor, stairs, other. "
                                    "Reply with only the word, nothing else."
                                ),
                            },
                        ],
                    }
                ],
            )
            raw = resp.content[0].text.strip().lower().split()[0]
            label = raw if raw in valid_labels else f"room {r['cluster_id'] + 1}"
        except Exception:
            log.exception("vision label call failed for cluster %s", r["cluster_id"])
            label = f"room {r['cluster_id'] + 1}"
        out.append(label)
        log.info("cluster %s -> '%s'", r["cluster_id"], label)
    return out


def _detect_doors_from_trajectory(cam_xy, cluster_frames, rooms_out, log):
    """For each pair of clusters, if the camera trajectory crosses between
    them in time order, mark a door at the midpoint of the crossing."""
    import numpy as np

    if len(rooms_out) < 2:
        return []
    # Build per-frame cluster id. Cluster ids are opaque (now strings like
    # "f1.c0" with multi-story segmentation), so use None for "no cluster".
    n = len(cam_xy)
    frame_cluster: list = [None] * n
    cluster_to_idx = {}
    for cid, frames in cluster_frames.items():
        cluster_to_idx[cid] = next(
            (i for i, r in enumerate(rooms_out) if r["id"] == f"r{cid}"), None
        )
        for fi in frames:
            frame_cluster[fi] = cid

    out = []
    seen = set()
    for i in range(1, n):
        a = frame_cluster[i - 1]
        b = frame_cluster[i]
        if a is None or b is None or a == b:
            continue
        ai = cluster_to_idx.get(a)
        bi = cluster_to_idx.get(b)
        if ai is None or bi is None:
            continue
        from_id = rooms_out[ai]["id"]
        to_id = rooms_out[bi]["id"]
        key = tuple(sorted([from_id, to_id]))
        if key in seen:
            continue
        seen.add(key)
        midpoint = (cam_xy[i - 1] + cam_xy[i]) / 2
        out.append(
            {
                "from": from_id,
                "to": to_id,
                "x_m": float(midpoint[0]),
                "z_m": float(midpoint[1]),
            }
        )
    log.info("detected %d doors from trajectory crossings", len(out))
    return out


# ---------------------------------------------------------------------------
# Tier 2: schematic-driven (kept as fallback)
# ---------------------------------------------------------------------------


def _build_mast3r_plan(
    scene: dict,
    frame_timestamps: list[float],
    rooms_meta: list[dict],
    doors_meta: list[dict],
    log,
) -> dict:
    """Turn the MASt3R scene + schematic into a floor-plan dict in world
    coordinates (XZ plane, meters)."""
    import numpy as np

    pts3d_list = scene["pts3d"]
    confs_list = scene["confs"]
    poses = scene["poses"]  # (N, 4, 4) cam-to-world
    n_frames = len(pts3d_list)

    # Concatenate all confident points for floor-plane fit.
    all_pts = []
    all_frame_idx = []
    # MASt3R confidence: anything above 1.5 is reasonably reliable; demo uses 1.5
    CONF_THR = 1.5
    for i, (pts, conf) in enumerate(zip(pts3d_list, confs_list)):
        flat_pts = pts.reshape(-1, 3)
        flat_conf = conf.reshape(-1)
        keep = flat_conf > CONF_THR
        if not keep.any():
            continue
        kp = flat_pts[keep]
        all_pts.append(kp)
        all_frame_idx.append(np.full(kp.shape[0], i, dtype=np.int32))
    if not all_pts:
        raise RuntimeError("MASt3R returned no confident points")
    all_pts = np.concatenate(all_pts, axis=0)
    all_frame_idx = np.concatenate(all_frame_idx, axis=0)
    log.info("aggregated %d confident 3D points across frames", all_pts.shape[0])

    # Find floor plane + a "world rotation" that maps it to Z=0 with up=Z.
    floor = _find_floor(all_pts, poses, log)
    R_world = floor["R"]  # (3, 3) — rotation from MASt3R-world to floor-aligned-world
    floor_z = floor["z"]  # offset along the new Z axis

    # Apply rotation to all points + camera positions.
    aligned_pts = (R_world @ all_pts.T).T
    cam_centers = poses[:, :3, 3]  # (N, 3)
    aligned_cams = (R_world @ cam_centers.T).T

    # Subtract floor Z so floor sits at Z=0.
    aligned_pts[:, 2] -= floor_z
    aligned_cams[:, 2] -= floor_z

    # Per-room: gather points whose contributing frames fall in the time
    # window. Use only points 0.1m–2.2m above floor (drops floor + ceiling).
    rooms_out = []
    placement = {}
    pad_s = 8.0  # seconds of pad on each side; schematic timestamps are noisy
    for r in rooms_meta:
        entered = r.get("entered_at")
        exited = r.get("exited_at")
        if entered is None or exited is None or exited <= entered:
            log.info("room %s: no time window in schematic, skipping", r["id"])
            rooms_out.append(_room_fallback(r, "missing schematic window"))
            continue

        win_lo = max(0.0, float(entered) - pad_s)
        win_hi = float(exited) + pad_s
        room_frames = [
            i
            for i, ts in enumerate(frame_timestamps)
            if win_lo <= ts <= win_hi
        ]
        if len(room_frames) < 2:
            # Nearest 3 frames to midpoint.
            mid = (float(entered) + float(exited)) / 2
            room_frames = sorted(
                range(n_frames), key=lambda i: abs(frame_timestamps[i] - mid)
            )[:3]

        frame_set = set(room_frames)
        mask = np.isin(all_frame_idx, np.array(list(frame_set), dtype=np.int32))
        room_pts = aligned_pts[mask]

        # Wall-height filter
        if room_pts.shape[0] > 0:
            z = room_pts[:, 2]
            wall = (z > 0.1) & (z < 2.2)
            room_pts = room_pts[wall]

        # Camera positions from this window — used as a fallback / sanity anchor.
        cam_pts = aligned_cams[room_frames]

        if room_pts.shape[0] < 200:
            log.info(
                "room %s (%s): only %d wall-height points; using camera-trajectory fallback",
                r["id"],
                r["label"],
                int(room_pts.shape[0]),
            )
            polygon, w_m, d_m = _bbox_from_camera_path(cam_pts[:, :2])
            confidence = 0.3
        else:
            # Trim outliers with a coarse percentile clip then PCA-aligned bbox.
            xy = room_pts[:, :2]
            polygon, w_m, d_m = _oriented_bbox(xy)
            confidence = 0.7 if len(room_frames) >= 4 else 0.5
            log.info(
                "room %s (%s): %d wall pts from %d frames -> %.2fx%.2fm",
                r["id"],
                r["label"],
                int(room_pts.shape[0]),
                len(room_frames),
                w_m,
                d_m,
            )

        rooms_out.append(
            {
                "id": r["id"],
                "label": r["label"],
                "polygon_m": [list(map(float, p)) for p in polygon],
                "width_m": round(float(w_m), 2),
                "depth_m": round(float(d_m), 2),
                "confidence": float(confidence),
                "sample_count": len(room_frames),
            }
        )
        placement[r["id"]] = polygon

    # Normalize so the global min is at origin.
    rooms_out = _normalize_origin(rooms_out)

    # Doors: place at midpoint of nearest-edges between connected room polygons.
    doors_out = _place_doors(rooms_out, doors_meta)

    confidence_label = "medium"
    if all(r.get("confidence", 0) < 0.5 for r in rooms_out):
        confidence_label = "low"
    elif sum(1 for r in rooms_out if r.get("confidence", 0) >= 0.7) >= max(
        1, len(rooms_out) // 2
    ):
        confidence_label = "high"

    return {
        "rooms": rooms_out,
        "doors": doors_out,
        "scale_m_per_unit": 1.0,
        "confidence": confidence_label,
        "notes": (
            "Reconstructed from tour video via MASt3R sparse global alignment. "
            "Per-room polygons are oriented bounding boxes of wall-height "
            "points (0.1–2.2 m above floor). Dimensions in meters."
        ),
        "model_version": "mast3r-metric.v1",
    }


def _find_floor(all_pts, poses, log) -> dict:
    """RANSAC plane fit on the lower portion of the point cloud, then build a
    rotation matrix that maps the plane normal to +Z."""
    import numpy as np
    from sklearn.linear_model import RANSACRegressor

    cam_centers = poses[:, :3, 3]
    # MASt3R coordinate convention varies; assume cameras are above the floor.
    # Find which axis has the largest signed-mean offset from the point cloud
    # mean along the principal axes — the gravity axis. Heuristic: use the
    # axis with the smallest variance in cam centers (since we walk laterally,
    # not vertically). That's the "up" axis, and the floor is below cameras.
    cam_var = np.var(cam_centers, axis=0)
    up_axis = int(np.argmin(cam_var))
    log.info("inferred up-axis = %d (cam variance %s)", up_axis, cam_var.tolist())

    cam_up_med = float(np.median(cam_centers[:, up_axis]))
    pt_up = all_pts[:, up_axis]

    # Determine sign: floor should be on the side away from ceiling. Sample
    # both directions and pick the one with denser points.
    below = all_pts[pt_up < cam_up_med - 0.4]
    above = all_pts[pt_up > cam_up_med + 0.4]
    if len(below) > len(above):
        floor_side = "below"
        floor_candidates = below
    else:
        floor_side = "above"
        floor_candidates = above
    log.info(
        "floor candidates: side=%s, n=%d (cam med up=%.2f)",
        floor_side,
        len(floor_candidates),
        cam_up_med,
    )

    if len(floor_candidates) < 200:
        # Degenerate — assume up = world up_axis, floor at min along up.
        floor_z = float(np.percentile(pt_up, 5 if floor_side == "below" else 95))
        n = np.zeros(3)
        n[up_axis] = -1.0 if floor_side == "below" else 1.0
        return {"R": _rotation_aligning(n, np.array([0, 0, 1.0])), "z": floor_z}

    # Fit a plane: in the two non-up axes, predict the up coordinate.
    other = [a for a in range(3) if a != up_axis]
    X = floor_candidates[:, other]
    y = floor_candidates[:, up_axis]
    rs = RANSACRegressor(residual_threshold=0.15, max_trials=200)
    rs.fit(X, y)
    a, b = rs.estimator_.coef_
    c = rs.estimator_.intercept_

    # Plane: y = a*X[0] + b*X[1] + c, i.e. (a, b, -1) dot something + c = 0.
    # Build the plane normal in 3D.
    normal = np.zeros(3)
    normal[other[0]] = a
    normal[other[1]] = b
    normal[up_axis] = -1.0
    if floor_side == "above":
        normal = -normal
    normal /= np.linalg.norm(normal)

    target_up = np.array([0, 0, 1.0])
    R = _rotation_aligning(normal, target_up)

    # Compute floor offset along new Z axis: take a representative inlier and
    # rotate it.
    rep = floor_candidates[rs.inlier_mask_][:1000].mean(axis=0)
    floor_z = float((R @ rep)[2])

    log.info(
        "floor plane fit: normal=%s, z=%.3f, inliers=%d/%d",
        normal.tolist(),
        floor_z,
        int(rs.inlier_mask_.sum()),
        len(floor_candidates),
    )
    return {"R": R, "z": floor_z}


def _rotation_aligning(src, dst):
    """Rotation matrix that maps unit vector src to unit vector dst."""
    import numpy as np

    src = src / max(np.linalg.norm(src), 1e-9)
    dst = dst / max(np.linalg.norm(dst), 1e-9)
    v = np.cross(src, dst)
    s = np.linalg.norm(v)
    c = np.dot(src, dst)
    if s < 1e-6:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))


def _oriented_bbox(xy):
    """PCA-aligned bbox using 5/95 percentiles for outlier robustness.
    Returns (polygon_world, width, depth)."""
    import numpy as np

    if len(xy) < 4:
        return _bbox_from_camera_path(xy)

    centroid = xy.mean(axis=0)
    centered = xy - centroid
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Order so first axis is dominant.
    order = np.argsort(eigvals)[::-1]
    R2 = eigvecs[:, order]  # (2, 2)

    rotated = centered @ R2  # (N, 2)
    # Use looser percentiles (2/98) — confident MASt3R points are already
    # outlier-cleaned; clipping at 5/95 was throwing away legit walls.
    lo = np.percentile(rotated, 2, axis=0)
    hi = np.percentile(rotated, 98, axis=0)
    span = hi - lo
    # Inflate the bbox by 0.5 m on each side to account for the fact that
    # cameras can't reach the actual wall surfaces — they capture detail near
    # the wall plane but the bbox tends to underestimate the room.
    pad = 0.5
    lo = lo - pad
    hi = hi + pad
    span = hi - lo
    box = np.array(
        [
            [lo[0], lo[1]],
            [hi[0], lo[1]],
            [hi[0], hi[1]],
            [lo[0], hi[1]],
        ]
    )
    box_world = box @ R2.T + centroid
    return box_world.tolist(), float(span[0]), float(span[1])


def _bbox_from_camera_path(cam_xy):
    """Fallback: use camera-trajectory points + 1.5m inflation."""
    import numpy as np

    if len(cam_xy) == 0:
        # Truly nothing — return a 3x3m placeholder
        box = [[0, 0], [3, 0], [3, 3], [0, 3]]
        return box, 3.0, 3.0
    cam_xy = np.asarray(cam_xy)
    if cam_xy.ndim == 1:
        cam_xy = cam_xy.reshape(1, -1)
    minXY = cam_xy.min(axis=0) - 1.5
    maxXY = cam_xy.max(axis=0) + 1.5
    w = float(maxXY[0] - minXY[0])
    d = float(maxXY[1] - minXY[1])
    w = max(2.5, w)
    d = max(2.5, d)
    cx = (minXY[0] + maxXY[0]) / 2
    cy = (minXY[1] + maxXY[1]) / 2
    box = [
        [cx - w / 2, cy - d / 2],
        [cx + w / 2, cy - d / 2],
        [cx + w / 2, cy + d / 2],
        [cx - w / 2, cy + d / 2],
    ]
    return box, w, d


def _normalize_origin(rooms):
    """Translate polygons so the global min is at (0, 0)."""
    rooms_shifted, _ = _normalize_origin_with_offset(rooms)
    return rooms_shifted


def _normalize_origin_with_offset(rooms):
    """Like _normalize_origin but also returns (offset_x, offset_y) for
    callers that need to apply the same shift to other geometry."""
    if not rooms:
        return rooms, (0.0, 0.0)
    all_xs = [float(p[0]) for r in rooms for p in r["polygon_m"]]
    all_ys = [float(p[1]) for r in rooms for p in r["polygon_m"]]
    mx, my = min(all_xs), min(all_ys)
    out = []
    for r in rooms:
        new_poly = [
            [float(p[0]) - mx, float(p[1]) - my] for p in r["polygon_m"]
        ]
        nr = dict(r)
        nr["polygon_m"] = new_poly
        out.append(nr)
    return out, (mx, my)


def _place_doors(rooms, doors_meta):
    """For each schematic door, find the midpoint of the closest edge between
    the two room polygons."""
    import numpy as np

    by_id = {r["id"]: np.array(r["polygon_m"]) for r in rooms}
    out = []
    seen = set()
    for d in doors_meta:
        a = by_id.get(d["from"])
        b = by_id.get(d["to"])
        if a is None or b is None:
            continue
        key = tuple(sorted([d["from"], d["to"]]))
        if key in seen:
            continue
        seen.add(key)
        # Closest pair of vertices
        diffs = a[:, None, :] - b[None, :, :]
        dists = np.linalg.norm(diffs, axis=2)
        ai, bi = np.unravel_index(int(np.argmin(dists)), dists.shape)
        mid = (a[ai] + b[bi]) / 2
        out.append(
            {
                "from": d["from"],
                "to": d["to"],
                "x_m": float(mid[0]),
                "z_m": float(mid[1]),
            }
        )
    return out


def _room_fallback(r, reason):
    M_PER_FT = 0.3048
    w = float(r.get("width_ft") or 12) * M_PER_FT
    d = float(r.get("depth_ft") or 12) * M_PER_FT
    return {
        "id": r["id"],
        "label": r["label"],
        "polygon_m": [[0, 0], [w, 0], [w, d], [0, d]],
        "width_m": round(w, 2),
        "depth_m": round(d, 2),
        "confidence": 0.1,
        "sample_count": 0,
        "fallback_reason": reason,
    }


# ---------------------------------------------------------------------------
# Phase 2 (Depth Anything V2) — kept as a fallback path
# ---------------------------------------------------------------------------


def _run_depth(frames: list[bytes], log) -> list[dict]:
    """Run Depth Anything V2 on each frame.

    Returns per-frame: {
        "depth": np.ndarray HxW float32 (metric meters, approximate),
        "width_px": int,
        "height_px": int,
        "max_depth_m": float,
        "median_depth_m": float,
        "horizontal_extent_m": float,  # how wide the floor extends
    }
    """
    import numpy as np
    import torch
    from PIL import Image
    from transformers import pipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("loading depth model on %s", device)

    # Use Depth Anything V2 small-metric variant (indoor) — fast, ~30M params.
    # The "metric" variant is trained with metric supervision so output is in
    # meters (rough — calibrated for typical indoor scenes).
    model_id = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
    cache_dir = os.path.join(WEIGHTS_PATH, "depth_anything_v2")
    os.makedirs(cache_dir, exist_ok=True)

    pipe = pipeline(
        task="depth-estimation",
        model=model_id,
        device=device,
        token=os.environ.get("HF_TOKEN"),
        cache_dir=cache_dir,
    )

    out = []
    for i, frame_bytes in enumerate(frames):
        img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        with torch.no_grad():
            result = pipe(img)
        depth_pil = result["predicted_depth"]
        # transformers pipeline returns a PIL image normalized to 0-255 OR
        # a tensor depending on version. Handle both.
        if hasattr(depth_pil, "cpu"):
            depth = depth_pil.cpu().numpy()
        else:
            depth = np.asarray(depth_pil).astype(np.float32)
        # Squeeze singleton dims
        while depth.ndim > 2:
            depth = depth.squeeze(0)
        # The metric-indoor variant outputs meters directly. Some versions
        # return inverse depth — heuristic: if median > 50, treat as inverse.
        if np.median(depth) > 50:
            depth = 1.0 / np.maximum(depth, 1e-3)
        max_depth = float(np.percentile(depth, 95))
        median_depth = float(np.median(depth))
        # Estimate horizontal extent: assume ~70° HFOV typical iPhone.
        # Horizontal extent at the median depth = 2 * d * tan(35°)
        horizontal_extent = 2.0 * median_depth * math.tan(math.radians(35.0))
        out.append(
            {
                "max_depth_m": max_depth,
                "median_depth_m": median_depth,
                "horizontal_extent_m": horizontal_extent,
                "width_px": img.width,
                "height_px": img.height,
            }
        )
        if i == 0 or i == len(frames) - 1 or i % 10 == 0:
            log.info(
                "depth frame %d/%d max=%.2fm med=%.2fm h_extent=%.2fm",
                i + 1,
                len(frames),
                max_depth,
                median_depth,
                horizontal_extent,
            )
    return out


def _measure_rooms(
    rooms_meta: list[dict],
    frame_ts: list[float],
    depth_results: list[dict],
    log,
) -> list[dict]:
    """Per room: aggregate depth frames whose timestamps fall in the room's
    [entered_at, exited_at] window. Estimate width = max horizontal extent
    seen in any frame, depth = max far-distance, median = stability."""
    import numpy as np

    measured = []
    for r in rooms_meta:
        entered = r.get("entered_at")
        exited = r.get("exited_at")
        if entered is None or exited is None or exited <= entered:
            measured.append(
                {
                    "id": r["id"],
                    "label": r["label"],
                    "schematic_w_ft": r.get("width_ft") or 12,
                    "schematic_d_ft": r.get("depth_ft") or 12,
                    "measured_w_m": None,
                    "measured_d_m": None,
                    "sample_count": 0,
                }
            )
            continue

        in_window = [
            d
            for ts, d in zip(frame_ts, depth_results)
            if entered <= ts <= exited
        ]
        if not in_window:
            # If exact window has no frames, take the closest few.
            mid = (entered + exited) / 2
            sorted_by_dist = sorted(
                zip(frame_ts, depth_results), key=lambda x: abs(x[0] - mid)
            )
            in_window = [d for _, d in sorted_by_dist[:3]]

        h_extents = [d["horizontal_extent_m"] for d in in_window]
        max_depths = [d["max_depth_m"] for d in in_window]
        med_depths = [d["median_depth_m"] for d in in_window]

        if h_extents and max_depths:
            measured_w = float(np.percentile(h_extents, 75))
            measured_d = float(np.percentile(max_depths, 75))
            # Sanity bounds: at least 2m, at most 12m for a single room.
            measured_w = max(2.0, min(12.0, measured_w))
            measured_d = max(2.0, min(12.0, measured_d))
        else:
            measured_w = None
            measured_d = None

        measured.append(
            {
                "id": r["id"],
                "label": r["label"],
                "schematic_w_ft": r.get("width_ft") or 12,
                "schematic_d_ft": r.get("depth_ft") or 12,
                "measured_w_m": measured_w,
                "measured_d_m": measured_d,
                "sample_count": len(in_window),
                "median_depth_m": (
                    float(np.median(med_depths)) if med_depths else None
                ),
            }
        )
        log.info(
            "room %s (%s): %d frames, w=%.2fm d=%.2fm",
            r["id"],
            r["label"],
            len(in_window),
            measured_w if measured_w is not None else -1,
            measured_d if measured_d is not None else -1,
        )

    return measured


def _place_rooms(measured_rooms: list[dict], doors: list[dict], log) -> dict:
    """Greedy grid placement using the schematic adjacency graph, sized with
    the measured (or schematic-fallback) dimensions in meters."""
    if not measured_rooms:
        return {"rooms": [], "doors": []}

    # Build adjacency from doors.
    adj = {r["id"]: set() for r in measured_rooms}
    for d in doors:
        if d["from"] in adj and d["to"] in adj:
            adj[d["from"]].add(d["to"])
            adj[d["to"]].add(d["from"])

    cell_of = {}
    cells_taken = {}

    def place(rid, x, y):
        cell_of[rid] = (x, y)
        cells_taken[(x, y)] = rid

    place(measured_rooms[0]["id"], 0, 0)
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    for i in range(1, len(measured_rooms)):
        rid = measured_rooms[i]["id"]
        anchors = [n for n in adj[rid] if n in cell_of] or [
            measured_rooms[i - 1]["id"]
        ]
        placed = False
        for a in anchors:
            ax, ay = cell_of[a]
            for dx, dy in dirs:
                if (ax + dx, ay + dy) not in cells_taken:
                    place(rid, ax + dx, ay + dy)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            # Spiral out
            ax, ay = cell_of[measured_rooms[i - 1]["id"]]
            radius = 1
            while not placed and radius < 50:
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        if abs(dx) != radius and abs(dy) != radius:
                            continue
                        if (ax + dx, ay + dy) not in cells_taken:
                            place(rid, ax + dx, ay + dy)
                            placed = True
                            break
                    if placed:
                        break
                radius += 1

    # Convert cells to coordinates using measured sizes.
    # Per row use max depth; per col use max width — same trick as schematic
    # renderer, but in meters.
    M_PER_FT = 0.3048
    sizes = {}
    for r in measured_rooms:
        w_m = r["measured_w_m"] or r["schematic_w_ft"] * M_PER_FT
        d_m = r["measured_d_m"] or r["schematic_d_ft"] * M_PER_FT
        sizes[r["id"]] = (w_m, d_m)

    cells = list(cell_of.values())
    if not cells:
        return {"rooms": [], "doors": []}
    minX = min(x for x, _ in cells)
    minY = min(y for _, y in cells)
    maxX = max(x for x, _ in cells)
    maxY = max(y for _, y in cells)

    col_w_m = {}
    row_h_m = {}
    for rid, (cx, cy) in cell_of.items():
        w, h = sizes[rid]
        col_w_m[cx] = max(col_w_m.get(cx, 0), w)
        row_h_m[cy] = max(row_h_m.get(cy, 0), h)

    col_x = {}
    cum = 0.0
    for cx in range(minX, maxX + 1):
        col_x[cx] = cum
        cum += col_w_m.get(cx, 3.0)
    row_y = {}
    cum = 0.0
    for cy in range(minY, maxY + 1):
        row_y[cy] = cum
        cum += row_h_m.get(cy, 3.0)

    out_rooms = []
    placement = {}
    for r in measured_rooms:
        rid = r["id"]
        cx, cy = cell_of[rid]
        x0 = col_x[cx]
        y0 = row_y[cy]
        w = col_w_m[cx]
        d = row_h_m[cy]
        polygon = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + d], [x0, y0 + d]]
        out_rooms.append(
            {
                "id": rid,
                "label": r["label"],
                "polygon_m": polygon,
                "width_m": round(w, 2),
                "depth_m": round(d, 2),
                "confidence": 0.6 if r["sample_count"] >= 3 else 0.3,
            }
        )
        placement[rid] = (x0, y0, w, d)

    out_doors = []
    seen = set()
    for d in doors:
        a = placement.get(d["from"])
        b = placement.get(d["to"])
        if not a or not b:
            continue
        key = tuple(sorted([d["from"], d["to"]]))
        if key in seen:
            continue
        seen.add(key)
        ax, ay, aw, ah = a
        bx, by, _, _ = b
        # Compute shared-wall midpoint (approximate).
        if abs((ax + aw) - bx) < 0.1:  # b is east of a
            out_doors.append(
                {"from": d["from"], "to": d["to"], "x_m": ax + aw, "z_m": ay + ah / 2}
            )
        elif abs(ax - (bx + a[2])) < 0.1:  # b is west
            out_doors.append(
                {"from": d["from"], "to": d["to"], "x_m": ax, "z_m": ay + ah / 2}
            )
        elif abs((ay + ah) - by) < 0.1:  # b south
            out_doors.append(
                {"from": d["from"], "to": d["to"], "x_m": ax + aw / 2, "z_m": ay + ah}
            )
        elif abs(ay - (by + b[3])) < 0.1:  # b north (placeholder b[3] may not exist)
            out_doors.append(
                {"from": d["from"], "to": d["to"], "x_m": ax + aw / 2, "z_m": ay}
            )
        else:
            # Centroid midpoint as fallback
            out_doors.append(
                {
                    "from": d["from"],
                    "to": d["to"],
                    "x_m": (ax + bx) / 2,
                    "z_m": (ay + by) / 2,
                }
            )

    return {"rooms": out_rooms, "doors": out_doors}


def _placeholder_plan(
    schematic: dict | None, *, confidence: str, notes: str, stats: dict
) -> dict:
    rooms = []
    if schematic and schematic.get("rooms"):
        x = 0.0
        for r in schematic["rooms"]:
            w = float(r.get("width_ft") or 12) * 0.3048
            d = float(r.get("depth_ft") or 12) * 0.3048
            rooms.append(
                {
                    "id": r["id"],
                    "label": r["label"],
                    "polygon_m": [
                        [x, 0],
                        [x + w, 0],
                        [x + w, d],
                        [x, d],
                    ],
                    "width_m": round(w, 2),
                    "depth_m": round(d, 2),
                    "confidence": 0.0,
                }
            )
            x += w
    return {
        "rooms": rooms,
        "doors": [],
        "scale_m_per_unit": 1.0,
        "confidence": confidence,
        "notes": notes,
        "model_version": "stub.v1",
        "stats": stats,
    }


@app.function(
    image=floorplan_image,
    gpu="A10G",
    timeout=600,
    volumes={WEIGHTS_PATH: weights_vol},
    secrets=[
        modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"]),
    ],
)
def vggt_smoke() -> dict:
    """Verify VGGT-1B-Commercial imports + downloads cleanly. Doesn't run
    inference — just confirms the install + auth flow works."""
    log = _setup_logging()
    sys.path.insert(0, VGGT_PATH)
    log.info("importing vggt...")
    import torch  # noqa: F401
    from vggt.models.vggt import VGGT  # type: ignore

    cache_dir = f"{WEIGHTS_PATH}/vggt"
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["HF_HOME"] = cache_dir
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
    log.info("loading commercial checkpoint...")
    model = VGGT.from_pretrained(
        "facebook/VGGT-1B-Commercial",
        token=os.environ.get("HF_TOKEN"),
        cache_dir=cache_dir,
    )
    n_params = sum(p.numel() for p in model.parameters())
    log.info("VGGT loaded: %.1fM params", n_params / 1e6)
    return {
        "ok": True,
        "params_m": n_params / 1e6,
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }


@app.function(
    image=floorplan_image,
    gpu="A10G",
    timeout=600,
    volumes={WEIGHTS_PATH: weights_vol},
    secrets=[
        modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"]),
    ],
)
def mast3r_smoke() -> dict:
    """Verify MASt3R is installed and the metric model loads. Doesn't run
    inference — just checks imports + weights download."""
    log = _setup_logging()
    sys.path.insert(0, MAST3R_PATH)
    sys.path.insert(0, f"{MAST3R_PATH}/dust3r")
    sys.path.insert(0, f"{MAST3R_PATH}/dust3r/croco")
    log.info("importing mast3r...")
    import torch  # noqa: F401
    from mast3r.model import AsymmetricMASt3R  # type: ignore

    cache_dir = f"{WEIGHTS_PATH}/mast3r"
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["HF_HOME"] = cache_dir
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
    log.info("loading metric checkpoint...")
    model_name = (
        "naver/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric"
    )
    model = AsymmetricMASt3R.from_pretrained(model_name)
    n_params = sum(p.numel() for p in model.parameters())
    log.info("model loaded: %.1fM params", n_params / 1e6)
    return {
        "ok": True,
        "params_m": n_params / 1e6,
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }


@app.function(
    image=floorplan_image,
    secrets=[
        modal.Secret.from_name(
            "supabase-service-role",
            required_keys=["SUPABASE_URL", "SUPABASE_SECRET_KEY"],
        ),
    ],
)
def fetch_schematic(house_id: str) -> dict | None:
    """Pull the existing schematic floor_plan_json from Supabase so the
    smoke test can pass it through unchanged (mirrors what the backend
    route does in production)."""
    from supabase import create_client

    sb = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    )
    res = (
        sb.table("houses")
        .select("floor_plan_json,video_url")
        .eq("id", house_id)
        .single()
        .execute()
    )
    return (res.data or {}).get("floor_plan_json")


@app.local_entrypoint()
def smoke_test(house_id: str, video_storage_path: str):
    """Run from local: `modal run modal_apps/floor_plan.py::smoke_test \\
        --house-id ... --video-storage-path ...`"""
    schematic = fetch_schematic.remote(house_id)
    print(
        f"[smoke] schematic rooms: "
        f"{len((schematic or {}).get('rooms') or [])}, "
        f"doors: {len((schematic or {}).get('doors') or [])}"
    )
    result = reconstruct_floor_plan.remote(
        house_id=house_id,
        video_storage_path=video_storage_path,
        schematic=schematic,
    )
    print(json.dumps(result, indent=2))
