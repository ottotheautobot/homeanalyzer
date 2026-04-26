# Operations — config touchpoints

Where credentials and URLs live across all the systems involved. When any of these change, every row in the relevant table must be updated to match — single-source-of-truth would be nicer but we're at MVP scale.

## Backend public URL (Railway)

If the Railway-issued domain changes (re-deploy under a new project, custom domain swap, etc.) **all of these must be updated to the new value**:

| System | Where | Notes |
|---|---|---|
| Railway env | `BACKEND_URL` | Used to build webhook + streaming URLs we hand to Meeting BaaS. No trailing slash. |
| Vercel env | `NEXT_PUBLIC_BACKEND_URL` | Frontend talks to this. No trailing slash. |
| Meeting BaaS dashboard (auth.meetingbaas.com) | Webhook config | Must point to `<BACKEND_URL>/webhooks/meetingbaas`. Wrong URL = no synthesis runs (bot.completed never lands). |

## Frontend public URL (Vercel)

When the Vercel domain changes (custom domain, project rename):

| System | Where | Notes |
|---|---|---|
| Vercel | Project URL | Managed by Vercel; for custom domains configure in Vercel dashboard. |
| Railway env | `FRONTEND_URL` | CORS allow-origin. Backend rejects browser requests from any other origin. |
| Zoom Marketplace app | OAuth Redirect URL + OAuth Allowlist | Even though we don't run OAuth, Zoom's form requires a value. Use frontend home URL. |

## Meeting BaaS account (v1 — auth.meetingbaas.com)

We're on v1; v2 (meetingbaas.com) is a separate platform with separate creds. Don't mix.

| Credential | Where it lives |
|---|---|
| API key | Railway env `MEETINGBAAS_API_KEY` |
| Webhook signing secret | Railway env `MEETINGBAAS_WEBHOOK_SECRET` (`whsec_...`) |
| Webhook URL | Configured in MB dashboard, points to `<BACKEND_URL>/webhooks/meetingbaas` |
| Subscribed events | `bot.status_change`, `bot.completed`, `bot.failed` |

## Zoom Marketplace app

General App with **Meeting SDK** + **Programmatic Join** features both toggled on. App must be installed via **Local Test → Add App Now** to activate dev credentials.

| Credential | Where | Notes |
|---|---|---|
| Dev Client ID | Railway env `ZOOM_SDK_ID` | Used as the Meeting SDK key — Zoom unified them in 2024. |
| Dev Client Secret | Railway env `ZOOM_SDK_SECRET` | |
| OAuth Redirect URL | Zoom app config | Must match the frontend public URL. Required by Zoom's form, not actually exercised by our flow. |

**Important:** the Zoom account hosting the meetings must be the same account that owns the Marketplace app (otherwise dev creds fail with `cannotJoinMeeting` / `sdkAuthFailed`). Production credentials require Zoom review (~4-6 weeks); we ship on dev creds.

## Deepgram

| Credential | Where |
|---|---|
| API key | Railway env `DEEPGRAM_API_KEY` |

## Resend (transactional email)

Used for "tour starting on this house" notifications to tour participants.

| Credential | Where | Notes |
|---|---|---|
| API key | Railway env `RESEND_API_KEY` | Free tier 100/day. Notifications are skipped silently if unset. |
| From address | Railway env `RESEND_FROM_EMAIL` | Default `onboarding@resend.dev` works without domain verification but will hit spam often. Verify a domain in Resend → use `noreply@yourdomain.com` for prod. |

## Supabase

| Credential | Where | Notes |
|---|---|---|
| URL | Railway `SUPABASE_URL`, Vercel `NEXT_PUBLIC_SUPABASE_URL` | Same value both sides. |
| Service-role secret key | Railway `SUPABASE_SECRET_KEY` | Backend only. Never expose to frontend — bypasses RLS. |
| Publishable (anon) key | Vercel `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Frontend only. |

## OpenAI / Anthropic

| Credential | Where |
|---|---|
| OpenAI key | Railway env `OPENAI_API_KEY` (used by Whisper for solo audio uploads) |
| Anthropic key | Railway env `ANTHROPIC_API_KEY` (Haiku extraction + Sonnet synthesis) |

## Sentry

| Credential | Where |
|---|---|
| Backend DSN | Railway env `SENTRY_DSN` |
| Frontend DSN | Vercel env `NEXT_PUBLIC_SENTRY_DSN` |

## Streaming URL token secret

Signs the per-house WebSocket URL handed to Meeting BaaS. Rotate by changing on Railway only — does not need to match anything else.

| | Where |
|---|---|
| Secret | Railway env `STREAMING_URL_SECRET` (any 32+ char random value) |

## User-level config

Stored in DB, not env. Set via SQL until the v2 settings page lands:

```sql
update public.users
   set default_zoom_url = 'https://zoom.us/j/<id>?pwd=<passcode>'
 where email = '<your-email>';
```

The PMR passcode must be embedded in the URL — Meeting BaaS bots can't enter a passcode prompt.
