"""End-to-end smoke test for the Hours 3-8 async pipeline.

Runs entirely on the host (no browser needed). Mints a session JWT for a
synthetic test user via the Supabase admin API, then exercises the backend
HTTP API exactly as the frontend would: create tour -> create house ->
upload audio -> poll observations + synthesis.

Usage (from /root/homeanalyzer/backend):
    uv run python scripts/smoke.py /path/to/audio.mp3

Requires backend running at $BACKEND_URL (default http://127.0.0.1:8000)
and the same .env file the backend uses for Supabase + LLM keys.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx
from supabase import create_client

# Reuse backend's settings loader so .env is read the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402

BACKEND_URL = "http://127.0.0.1:8000"
TEST_EMAIL = "smoke-test@homeanalyzer.dev"
TEST_PASSWORD = "smoke-test-pwd-9f3c2a1b8e7d"
POLL_TIMEOUT_SECONDS = 600  # 10 min budget for whisper + extract + synth
POLL_INTERVAL_SECONDS = 5


def ensure_test_user(admin_client) -> None:
    """Idempotent: create the synthetic test user with a known password."""
    try:
        admin_client.auth.admin.create_user(
            {
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "email_confirm": True,
            }
        )
        print(f"  created test user {TEST_EMAIL}")
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "registered" in msg or "exists" in msg or "422" in msg:
            print(f"  test user {TEST_EMAIL} already exists")
        else:
            raise


def sign_in(anon_client) -> str:
    res = anon_client.auth.sign_in_with_password(
        {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if not res.session or not res.session.access_token:
        raise RuntimeError("sign-in returned no session")
    return res.session.access_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_path", help="Path to audio file (MP3/M4A/WAV)")
    parser.add_argument(
        "--backend-url",
        default=BACKEND_URL,
        help=f"Backend URL (default: {BACKEND_URL})",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio_path)
    if not audio_path.is_file():
        print(f"audio file not found: {audio_path}", file=sys.stderr)
        return 2

    if not settings.supabase_url or not settings.supabase_secret_key:
        print(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set in backend/.env",
            file=sys.stderr,
        )
        return 2
    publishable_key = (Path(__file__).resolve().parents[2] / "frontend" / ".env.local").read_text()
    pub = None
    for line in publishable_key.splitlines():
        if line.startswith("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="):
            pub = line.split("=", 1)[1].strip()
            break
    if not pub:
        print("Could not read publishable key from frontend/.env.local", file=sys.stderr)
        return 2

    print("== Hours 3-8 smoke test ==")
    print(f"Backend:    {args.backend_url}")
    print(f"Supabase:   {settings.supabase_url}")
    print(f"Audio file: {audio_path} ({audio_path.stat().st_size:,} bytes)")
    print()

    print("[1/6] Ensuring test user...")
    admin = create_client(settings.supabase_url, settings.supabase_secret_key)
    ensure_test_user(admin)

    print("[2/6] Signing in...")
    anon = create_client(settings.supabase_url, pub)
    token = sign_in(anon)
    print(f"  got JWT ({len(token)} chars)")

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=args.backend_url, headers=headers, timeout=60.0) as http:
        # Health check first so a 401 here is unmistakably auth, not network.
        h = http.get("/health")
        h.raise_for_status()

        print("[3/6] Creating tour...")
        r = http.post(
            "/tours",
            json={"name": "Smoke test tour", "location": "VPS"},
        )
        r.raise_for_status()
        tour = r.json()
        print(f"  tour {tour['id']}")

        print("[4/6] Creating house...")
        r = http.post(
            f"/tours/{tour['id']}/houses",
            json={"address": "123 Smoke Test Ln"},
        )
        r.raise_for_status()
        house = r.json()
        house_id = house["id"]
        print(f"  house {house_id}")

        print(f"[5/6] Uploading {audio_path.name}...")
        with audio_path.open("rb") as f:
            r = http.post(
                f"/houses/{house_id}/audio",
                files={"audio": (audio_path.name, f, "audio/mpeg")},
                timeout=300.0,
            )
        r.raise_for_status()
        print(f"  {r.json()}")

        print(
            f"[6/6] Polling for observations + synthesis (timeout {POLL_TIMEOUT_SECONDS}s)..."
        )
        deadline = time.time() + POLL_TIMEOUT_SECONDS
        last_obs_count = -1
        last_status = None
        while time.time() < deadline:
            r = http.get(f"/houses/{house_id}/observations")
            r.raise_for_status()
            obs = r.json()
            if len(obs) != last_obs_count:
                print(f"  observations: {len(obs)}")
                last_obs_count = len(obs)

            r = http.get(f"/houses/{house_id}")
            r.raise_for_status()
            h = r.json()
            if h["status"] != last_status:
                print(f"  house status: {h['status']}")
                last_status = h["status"]

            if h["status"] == "completed" and h.get("synthesis_md"):
                print()
                print("=" * 60)
                print("SYNTHESIS")
                print("=" * 60)
                print(h["synthesis_md"])
                print("=" * 60)
                print(f"Score: {h.get('overall_score')}")
                print(f"Observations: {len(obs)}")
                print(f"Audio path:   {h.get('audio_url')}")
                print()
                print("OK - smoke test passed.")
                return 0

            time.sleep(POLL_INTERVAL_SECONDS)

        print(
            f"\nFAIL - timed out after {POLL_TIMEOUT_SECONDS}s. Last observed: "
            f"{last_obs_count} obs, status={last_status}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
