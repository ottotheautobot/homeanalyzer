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
weights_vol = modal.Volume.from_name("floorplan-weights", create_if_missing=True)

floorplan_image = (
    modal.Image.debian_slim(python_version="3.11")
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
    )
    .run_commands(
        f"git clone --recursive https://github.com/naver/mast3r {MAST3R_PATH}",
        # MASt3R's own requirements.txt is light — most heavy deps already listed above.
        # Skipping curope CUDA kernel build: pure-PyTorch fallback is plenty fast for 60 frames.
        f"pip install -r {MAST3R_PATH}/requirements.txt || true",
        f"pip install -r {MAST3R_PATH}/dust3r/requirements.txt || true",
    )
    .env(
        {
            "PYTHONPATH": (
                f"{MAST3R_PATH}:{MAST3R_PATH}/dust3r:"
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

    # Phase 3: try MASt3R first — full multi-view reconstruction.
    try:
        mast3r_out = _run_mast3r(frames, log)
    except Exception as e:
        log.exception("mast3r failed; will fall back to depth-only path")
        mast3r_out = None

    if mast3r_out is not None and rooms_meta:
        try:
            plan = _build_mast3r_plan(
                mast3r_out, frame_timestamps, rooms_meta, doors_meta, log
            )
            plan["stats"] = {
                "frames": len(frames),
                "duration_s": duration_s,
                "points_total": int(mast3r_out["n_points"]),
                "rooms_with_data": sum(
                    1 for r in plan["rooms"] if r.get("sample_count", 0) > 0
                ),
            }
            return plan
        except Exception as e:
            log.exception("mast3r plan-build failed; falling back to depth-only")

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
    """Translate all polygons so the global min is at (0, 0). Returns plain
    Python floats — no numpy leaks into the Modal return value."""
    if not rooms:
        return rooms
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
    return out


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
