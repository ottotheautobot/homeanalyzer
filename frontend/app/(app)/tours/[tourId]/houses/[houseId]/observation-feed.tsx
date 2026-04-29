"use client";

import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  LayoutGrid,
  Loader2,
  MessageCircle,
  Quote,
  Video,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { clientFetch } from "@/lib/api-client";
import { createSupabaseBrowserClient } from "@/lib/supabase/browser";
import type { Observation } from "@/lib/types";

const CATEGORY_META: Record<
  Observation["category"],
  { label: string; Icon: LucideIcon; ring: string; chip: string }
> = {
  hazard: {
    label: "Hazard",
    Icon: AlertTriangle,
    ring: "border-red-200 dark:border-red-900/60",
    chip: "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300",
  },
  concern: {
    label: "Concern",
    Icon: CircleAlert,
    ring: "border-amber-200 dark:border-amber-900/60",
    chip: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300",
  },
  positive: {
    label: "Positive",
    Icon: CheckCircle2,
    ring: "border-emerald-200 dark:border-emerald-900/60",
    chip: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300",
  },
  layout: {
    label: "Layout",
    Icon: LayoutGrid,
    ring: "border-zinc-200 dark:border-zinc-800",
    chip: "bg-zinc-100 dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300",
  },
  condition: {
    label: "Condition",
    Icon: Wrench,
    ring: "border-zinc-200 dark:border-zinc-800",
    chip: "bg-zinc-100 dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300",
  },
  agent_said: {
    label: "Agent",
    Icon: Quote,
    ring: "border-blue-200 dark:border-blue-900/60",
    chip: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300",
  },
  partner_said: {
    label: "Partner",
    Icon: MessageCircle,
    ring: "border-violet-200 dark:border-violet-900/60",
    chip: "bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300",
  },
};

const SEVERITY_TONE: Record<NonNullable<Observation["severity"]>, string> = {
  info: "text-zinc-500",
  warn: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400 font-semibold",
};

function formatTimestamp(seconds: number | null) {
  if (seconds == null) return null;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

type MediaResponse = {
  audio_url: string | null;
  video_url: string | null;
  photo_url: string | null;
};

export function ObservationFeed({
  houseId,
  initial,
}: {
  houseId: string;
  initial: Observation[];
}) {
  const [observations, setObservations] = useState<Observation[]>(initial);
  // Lazy-loaded once the first 'Show evidence' expander on this page asks for
  // it. Shared across rows so we don't fetch the signed video URL N times.
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoState, setVideoState] = useState<"idle" | "loading" | "ready" | "missing">("idle");
  const inflight = useRef<Promise<string | null> | null>(null);

  async function ensureVideo(): Promise<string | null> {
    if (videoState === "ready") return videoUrl;
    if (videoState === "missing") return null;
    if (inflight.current) return inflight.current;
    setVideoState("loading");
    inflight.current = clientFetch<MediaResponse>(
      `/houses/${houseId}/media`,
    )
      .then((m) => {
        if (m.video_url) {
          setVideoUrl(m.video_url);
          setVideoState("ready");
          return m.video_url;
        }
        setVideoState("missing");
        return null;
      })
      .catch(() => {
        setVideoState("missing");
        return null;
      })
      .finally(() => {
        inflight.current = null;
      });
    return inflight.current;
  }

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const channel = supabase
      .channel(`obs:${houseId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "observations",
          filter: `house_id=eq.${houseId}`,
        },
        (payload) => {
          const next = payload.new as Observation;
          setObservations((prev) =>
            prev.some((o) => o.id === next.id) ? prev : [...prev, next],
          );
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [houseId]);

  if (observations.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 px-6 py-10 text-center">
        <p className="text-sm text-zinc-500">
          No observations yet. They&apos;ll start landing here within ~20s of
          someone speaking on the tour. Snap a photo above to add one yourself.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {observations.map((obs) => {
        const meta = CATEGORY_META[obs.category];
        const Icon = meta.Icon;
        const hasEvidence =
          obs.source === "photo_analysis" && obs.recall_timestamp != null;
        return (
          <li
            key={obs.id}
            className={`flex gap-3 rounded-xl border ${meta.ring} bg-white dark:bg-zinc-950 p-3`}
          >
            <span
              className={`shrink-0 inline-flex items-center justify-center size-8 rounded-lg ${meta.chip}`}
              aria-hidden="true"
            >
              <Icon className="size-4" strokeWidth={2.25} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 text-[11px] mb-0.5">
                <div className="flex items-center gap-1.5 min-w-0 text-zinc-500">
                  <span className="font-medium uppercase tracking-wide">
                    {meta.label}
                  </span>
                  {obs.source === "photo_analysis" ? (
                    <span
                      className="inline-flex items-center gap-0.5 text-primary"
                      title="From video analysis"
                    >
                      <Video className="size-3" strokeWidth={2.25} />
                    </span>
                  ) : null}
                  {obs.room ? (
                    <span className="truncate">· {obs.room}</span>
                  ) : null}
                  {obs.severity ? (
                    <span
                      className={`uppercase tracking-wide ${SEVERITY_TONE[obs.severity]}`}
                    >
                      · {obs.severity}
                    </span>
                  ) : null}
                </div>
                <span className="text-zinc-400 tabular-nums shrink-0">
                  {formatTimestamp(obs.recall_timestamp) ??
                    formatDistanceToNow(new Date(obs.created_at), {
                      addSuffix: true,
                    })}
                </span>
              </div>
              <div className="text-sm text-zinc-900 dark:text-zinc-100 leading-snug">
                {obs.content}
              </div>
              {hasEvidence ? (
                <EvidenceDisclosure
                  timestamp={obs.recall_timestamp!}
                  ensureVideo={ensureVideo}
                  videoState={videoState}
                />
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function VideoClip({
  videoUrl,
  timestamp,
}: {
  videoUrl: string;
  timestamp: number;
}) {
  // recall_timestamp from the vision pipeline pins to one frame, but the
  // observation was extracted from a batch of ~30 frames — the detail
  // can land on neighboring sampled frames. Show a -2s to +5s window the
  // user can scrub.
  //
  // We can't trust the #t=start,end URL fragment to enforce the upper
  // bound (Safari/iOS frequently ignores the end and plays through to
  // the file's actual duration). Drive the window in JS instead: seek
  // to start on loadedmetadata, and on timeupdate snap back to start
  // whenever we've crossed end.
  const start = Math.max(0, timestamp - 2);
  const end = timestamp + 5;
  return (
    <video
      src={videoUrl}
      autoPlay
      muted
      loop
      controls
      playsInline
      preload="metadata"
      onLoadedMetadata={(e) => {
        e.currentTarget.currentTime = start;
      }}
      onTimeUpdate={(e) => {
        const t = e.currentTarget.currentTime;
        if (t >= end || t < start - 0.25) {
          e.currentTarget.currentTime = start;
        }
      }}
      className="w-full max-w-sm rounded-md border border-zinc-200 dark:border-zinc-800 bg-black"
    />
  );
}

function EvidenceDisclosure({
  timestamp,
  ensureVideo,
  videoState,
}: {
  timestamp: number;
  ensureVideo: () => Promise<string | null>;
  videoState: "idle" | "loading" | "ready" | "missing";
}) {
  const [open, setOpen] = useState(false);
  const [resolvedUrl, setResolvedUrl] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [missing, setMissing] = useState(videoState === "missing");

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (resolvedUrl) return;
    setResolving(true);
    const url = await ensureVideo();
    setResolving(false);
    if (url) setResolvedUrl(url);
    else setMissing(true);
  }

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
      >
        {open ? (
          <ChevronDown className="size-3" />
        ) : (
          <ChevronRight className="size-3" />
        )}
        {open ? "Hide evidence" : "Show evidence"}
      </button>
      {open ? (
        <div className="mt-1.5">
          {resolving ? (
            <p className="text-xs text-zinc-500 inline-flex items-center gap-1.5">
              <Loader2 className="size-3 animate-spin" /> Loading video…
            </p>
          ) : missing ? (
            <p className="text-xs text-zinc-500">
              No video archived for this house — can&apos;t show evidence.
            </p>
          ) : resolvedUrl ? (
            <VideoClip
              key={resolvedUrl + timestamp}
              videoUrl={resolvedUrl}
              timestamp={timestamp}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
