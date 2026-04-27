"use client";

import { Mic, Square, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type UploadResponse = {
  house_id: string;
  status: string;
  storage_path: string;
};

type Phase = "idle" | "recording" | "ready";

function pickRecordingMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  // Safari (iOS) only supports a small set; chrome supports webm/opus.
  const candidates = [
    "audio/mp4",
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  for (const m of candidates) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return undefined;
}

function fmtElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toString().padStart(2, "0")}`;
}

export function RecordAudio({ houseId }: { houseId: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const tickRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (tickRef.current) window.clearInterval(tickRef.current);
      const r = recorderRef.current;
      if (r && r.state !== "inactive") {
        try {
          r.stop();
        } catch {}
      }
      r?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const upload = useMutation({
    mutationFn: async (b: Blob): Promise<UploadResponse> => {
      const ext = b.type.includes("mp4")
        ? "m4a"
        : b.type.includes("webm")
          ? "webm"
          : b.type.includes("ogg")
            ? "ogg"
            : "audio";
      const fd = new FormData();
      const file = new File([b], `tour-recording.${ext}`, { type: b.type });
      fd.append("audio", file, file.name);
      return clientFetch<UploadResponse>(`/houses/${houseId}/audio`, {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: () => {
      setBlob(null);
      setElapsed(0);
      setPhase("idle");
      router.refresh();
    },
  });

  async function start() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickRecordingMime();
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      r.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      r.onstop = () => {
        const merged = new Blob(chunksRef.current, {
          type: r.mimeType || "audio/webm",
        });
        setBlob(merged);
        setPhase("ready");
        stream.getTracks().forEach((t) => t.stop());
        if (tickRef.current) {
          window.clearInterval(tickRef.current);
          tickRef.current = null;
        }
      };
      recorderRef.current = r;
      startedAtRef.current = Date.now();
      tickRef.current = window.setInterval(() => {
        setElapsed(Date.now() - startedAtRef.current);
      }, 250);
      r.start(1000); // 1s timeslice — robust against tab backgrounding
      setPhase("recording");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Microphone access denied or unavailable",
      );
    }
  }

  function stop() {
    const r = recorderRef.current;
    if (r && r.state !== "inactive") r.stop();
  }

  function discard() {
    setBlob(null);
    setElapsed(0);
    setPhase("idle");
  }

  return (
    <div className="space-y-3">
      {phase === "idle" ? (
        <div className="space-y-2">
          <Button
            type="button"
            onClick={start}
            disabled={upload.isPending}
            variant="secondary"
            size="sm"
          >
            <Mic className="size-4 mr-1.5" />
            Record now (in browser)
          </Button>
          <p className="text-xs text-zinc-500">
            Or upload a file recorded elsewhere — see below.
          </p>
        </div>
      ) : null}

      {phase === "recording" ? (
        <div className="rounded-md border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/20 p-3 flex items-center gap-3">
          <span className="size-2.5 rounded-full bg-red-500 animate-pulse" />
          <span className="text-sm font-medium tabular-nums">
            Recording · {fmtElapsed(elapsed)}
          </span>
          <Button
            type="button"
            onClick={stop}
            size="sm"
            variant="secondary"
            className="ml-auto"
          >
            <Square className="size-3.5 mr-1.5 fill-current" />
            Stop
          </Button>
        </div>
      ) : null}

      {phase === "ready" && blob ? (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 p-3 space-y-2">
          <p className="text-sm">
            Got <span className="font-medium tabular-nums">{fmtElapsed(elapsed)}</span> of audio (
            {(blob.size / (1024 * 1024)).toFixed(1)} MB).
          </p>
          <audio
            controls
            className="w-full"
            src={URL.createObjectURL(blob)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => upload.mutate(blob)}
              disabled={upload.isPending}
            >
              <Upload className="size-4 mr-1.5" />
              {upload.isPending ? "Uploading…" : "Use this recording"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={discard}
              disabled={upload.isPending}
            >
              Discard
            </Button>
          </div>
          {upload.isError ? (
            <p className="text-xs text-red-600 dark:text-red-400">
              {upload.error instanceof Error
                ? upload.error.message
                : "Upload failed"}
            </p>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : null}
    </div>
  );
}
