"use client";

import { useState } from "react";
import {
  AlertTriangle, Check, Copy, Download, FileText, Heart, Loader2, Pencil, RotateCw, Trash2,
} from "lucide-react";
import { Clip, api, fmtTime } from "@/lib/api";

const SCORE_PARTS = [
  { key: "hook", label: "Hook" },
  { key: "flow", label: "Flow" },
  { key: "value", label: "Value" },
  { key: "trend", label: "Trend" },
] as const;

export function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 80 ? "bg-accent text-accent-ink" : score >= 60 ? "bg-yellow-300 text-black" : "bg-zinc-300 text-black";
  return <span className={`rounded-md px-1.5 py-0.5 text-xs font-extrabold ${tone}`}>{Math.round(score)}</span>;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn-ghost w-full justify-start"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {}
      }}
    >
      {done ? <Check size={15} className="text-accent" /> : <Copy size={15} />} {done ? "Copied" : label}
    </button>
  );
}

function Player({ clip, rounded = "rounded-xl" }: { clip: Clip; rounded?: string }) {
  const busy = clip.status === "pending" || clip.status === "rendering";
  return (
    <div className={`relative aspect-[9/16] w-full overflow-hidden bg-black ${rounded}`}>
      {clip.url && clip.status === "ready" ? (
        <video
          key={clip.url}
          src={clip.url}
          poster={clip.thumbnail_url ?? undefined}
          controls
          preload="none"
          playsInline
          className="h-full w-full object-cover"
        />
      ) : clip.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={clip.thumbnail_url} alt="" className="h-full w-full object-cover opacity-40" />
      ) : null}
      {busy && (
        <div className="absolute inset-0 grid place-items-center bg-black/60 text-sm">
          <span className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin" /> {clip.status === "pending" ? "Waiting to render…" : "Rendering…"}
          </span>
        </div>
      )}
      {clip.status === "failed" && (
        <div className="absolute inset-0 grid place-items-center bg-black/70 p-4 text-center text-xs text-red-200">
          <span>
            <AlertTriangle size={18} className="mx-auto mb-1" /> Render failed
            <span className="mt-1 line-clamp-3 block opacity-70">{clip.error}</span>
          </span>
        </div>
      )}
    </div>
  );
}

interface Props {
  clip: Clip;
  view: "grid" | "list";
  onEdit: (c: Clip) => void;
  onChanged: () => void;
}

export default function ClipCard({ clip, view, onEdit, onChanged }: Props) {
  const [liked, setLiked] = useState(clip.liked);
  const post = `${clip.caption || clip.title}\n\n${(clip.hashtags || []).join(" ")}`.trim();
  const ready = clip.status === "ready" && clip.url;

  const toggleLike = async () => {
    setLiked(!liked);
    try {
      await api.patchClip(clip.id, { liked: !liked });
    } catch {
      setLiked(liked);
    }
  };
  const remove = async () => {
    if (!confirm(`Delete "${clip.title}"?`)) return;
    await api.deleteClip(clip.id);
    onChanged();
  };
  const retry = async () => {
    await api.rerender(clip.id);
    onChanged();
  };

  if (view === "grid") {
    return (
      <div className="group flex flex-col">
        <div className="relative">
          <Player clip={clip} />
          <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-1.5">
            <ScoreBadge score={clip.score} />
          </div>
          <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-medium">
            {fmtTime(clip.duration)}
          </span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-1 px-0.5">
          <button aria-label="Like" onClick={toggleLike} className="rounded-lg p-1.5 text-zinc-400 hover:bg-card hover:text-white">
            <Heart size={16} className={liked ? "fill-red-500 text-red-500" : ""} />
          </button>
          {ready && (
            <a aria-label="Download" href={`${clip.url!.split("?")[0]}?download=true`} className="rounded-lg p-1.5 text-zinc-400 hover:bg-card hover:text-white">
              <Download size={16} />
            </a>
          )}
          <button aria-label="Edit" onClick={() => onEdit(clip)} className="rounded-lg p-1.5 text-zinc-400 hover:bg-card hover:text-white">
            <Pencil size={16} />
          </button>
          {clip.status === "failed" && (
            <button aria-label="Retry render" onClick={retry} className="rounded-lg p-1.5 text-zinc-400 hover:bg-card hover:text-white">
              <RotateCw size={16} />
            </button>
          )}
        </div>
        <p className="mt-1 line-clamp-2 px-0.5 text-sm font-semibold leading-snug">{clip.title}</p>
      </div>
    );
  }

  return (
    <div className="grid gap-5 rounded-2xl border border-line bg-panel p-4 md:grid-cols-[220px_1fr_190px]">
      <div className="mx-auto w-full max-w-[260px] md:max-w-none">
        <Player clip={clip} />
      </div>

      <div className="min-w-0">
        <div className="flex items-start gap-2">
          <ScoreBadge score={clip.score} />
          <h3 className="text-[17px] font-bold leading-snug">{clip.title}</h3>
        </div>
        <p className="mt-1.5 text-xs text-muted">
          [{fmtTime(clip.start)} – {fmtTime(clip.end)}] · {Math.round(clip.duration)}s
          {clip.layout ? ` · ${clip.layout === "crop" ? "speaker tracking" : "blurred background"}` : ""}
        </p>

        {clip.scores && Object.keys(clip.scores).length > 0 && (
          <div className="mt-3 grid max-w-md grid-cols-4 gap-3">
            {SCORE_PARTS.map(({ key, label }) => {
              const v = clip.scores[key] ?? 0;
              return (
                <div key={key}>
                  <div className="mb-1 flex justify-between text-[11px] text-muted">
                    <span>{label}</span>
                    <span className="text-zinc-300">{Math.round(v)}/25</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-card">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${(v / 25) * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {clip.headline && (
          <p className="mt-3 inline-block rounded-lg bg-white px-2.5 py-1 text-xs font-bold text-black">{clip.headline}</p>
        )}
        <p className="mt-3 max-h-44 overflow-auto pr-2 text-sm leading-relaxed text-zinc-300">{clip.transcript}</p>
        {clip.reason && <p className="mt-2 text-xs text-muted">💡 {clip.reason}</p>}
        {clip.hashtags?.length > 0 && <p className="mt-2 text-xs text-sky-300">{clip.hashtags.join(" ")}</p>}
      </div>

      <div className="flex flex-col gap-2">
        {ready ? (
          <a className="btn-primary w-full justify-start" href={`${clip.url!.split("?")[0]}?download=true`}>
            <Download size={15} /> Download
          </a>
        ) : (
          <button className="btn-primary w-full justify-start" disabled>
            <Download size={15} /> Download
          </button>
        )}
        <button className="btn-ghost w-full justify-start" onClick={() => onEdit(clip)}>
          <Pencil size={15} /> Edit clip
        </button>
        <CopyButton text={post} label="Copy caption" />
        <CopyButton text={clip.title} label="Copy title" />
        {ready && clip.srt_url && (
          <a className="btn-ghost w-full justify-start" href={`${clip.srt_url.split("?")[0]}?download=true`}>
            <FileText size={15} /> Subtitles (.srt)
          </a>
        )}
        <div className="mt-auto flex gap-2">
          <button className="btn-ghost flex-1" onClick={toggleLike} aria-label="Like">
            <Heart size={15} className={liked ? "fill-red-500 text-red-500" : ""} />
          </button>
          {clip.status === "failed" && (
            <button className="btn-ghost flex-1" onClick={retry} aria-label="Retry render">
              <RotateCw size={15} />
            </button>
          )}
          <button className="btn-danger flex-1" onClick={remove} aria-label="Delete clip">
            <Trash2 size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
