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
import tempfile
from pathlib import Path

import modal

WEIGHTS_PATH = "/weights"
weights_vol = modal.Volume.from_name("floorplan-weights", create_if_missing=True)

floorplan_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "git",
        "ffmpeg",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "build-essential",
    )
    .pip_install(
        "torch==2.4.0",
        "torchvision==0.19.0",
        "numpy<2.0",
        "scipy",
        "scikit-image",
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

    # Phase 2: per-frame metric depth via Depth Anything V2.
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

    # Group frames by room using schematic timestamps.
    rooms_meta = (schematic or {}).get("rooms") or []
    if not rooms_meta:
        return _placeholder_plan(
            schematic,
            confidence="low",
            notes="No schematic rooms to anchor measurements to.",
            stats={"frames": len(frames)},
        )

    # Compute per-room dimensions from the depth maps that fall in each room's
    # time window.
    measured_rooms = _measure_rooms(
        rooms_meta, frame_timestamps, depth_results, log
    )

    # Place rooms in 2D using schematic adjacency + measured sizes.
    placed = _place_rooms(measured_rooms, (schematic or {}).get("doors") or [], log)

    return {
        "rooms": placed["rooms"],
        "doors": placed["doors"],
        "scale_m_per_unit": 1.0,
        "confidence": "low",
        "notes": (
            "Reconstructed from monocular depth without camera tracking — "
            "dimensions are approximate (~30-50% error). Layout follows the "
            "schematic adjacency graph. Camera-tracked reconstruction is on "
            "the v2 backlog."
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
