"use client";

import Link from "next/link";
import { AlertTriangle, Film, Loader2 } from "lucide-react";
import { Project, STAGES, fmtTime } from "@/lib/api";

export function StatusBadge({ p }: { p: Project }) {
  if (p.status === "done")
    return (
      <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-accent-ink">
        {p.clip_count ?? p.clips?.length ?? 0} clips
      </span>
    );
  if (p.status === "failed")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-950 px-2 py-0.5 text-[11px] font-semibold text-red-300">
        <AlertTriangle size={11} /> Failed
      </span>
    );
  const label =
    p.status === "queued"
      ? p.queue_position ? `Queued #${p.queue_position + 1}` : "Queued"
      : STAGES.find((s) => s.key === p.stage)?.label ?? "Processing";
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] font-semibold text-zinc-200">
      <Loader2 size={11} className="animate-spin" /> {label} {Math.round(p.progress * 100)}%
    </span>
  );
}

export default function ProjectCard({ p }: { p: Project }) {
  return (
    <Link
      href={`/projects/${p.id}`}
      className="group overflow-hidden rounded-2xl border border-line bg-panel transition hover:border-zinc-500"
    >
      <div className="relative aspect-video bg-card">
        {p.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={p.thumbnail_url} alt="" className="h-full w-full object-cover transition group-hover:scale-[1.02]" />
        ) : (
          <div className="grid h-full place-items-center text-zinc-600">
            <Film size={32} />
          </div>
        )}
        <div className="absolute left-2 top-2">
          <StatusBadge p={p} />
        </div>
        {p.duration ? (
          <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 text-[11px] font-medium">
            {fmtTime(p.duration)}
          </span>
        ) : null}
        {p.status === "processing" && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
            <div className="h-full bg-accent transition-all" style={{ width: `${p.progress * 100}%` }} />
          </div>
        )}
      </div>
      <div className="p-3">
        <p className="line-clamp-2 text-sm font-semibold leading-snug">{p.title || p.source}</p>
        <p className="mt-1 text-xs text-muted">{new Date(p.created_at * 1000).toLocaleString()}</p>
      </div>
    </Link>
  );
}
