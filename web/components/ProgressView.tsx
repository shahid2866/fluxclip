"use client";

import { AlertTriangle, Check, Loader2, RotateCw } from "lucide-react";
import { Project, STAGES } from "@/lib/api";

export default function ProgressView({ p, onRetry }: { p: Project; onRetry: () => void }) {
  const current = STAGES.findIndex((s) => s.key === p.stage);
  const failed = p.status === "failed";
  return (
    <div className="mx-auto max-w-xl rounded-2xl border border-line bg-panel p-6">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-lg font-bold">
          {failed ? "Something went wrong" : p.status === "queued" ? "Waiting in queue" : "Creating your clips"}
        </h2>
        {!failed && <span className="text-2xl font-extrabold text-accent">{Math.round(p.progress * 100)}%</span>}
      </div>
      <p className="mb-5 text-sm text-muted">
        {p.status === "queued"
          ? p.queue_position
            ? `${p.queue_position} video${p.queue_position > 1 ? "s" : ""} ahead of this one.`
            : "Starting…"
          : p.message || "Working…"}
      </p>

      {!failed && (
        <div className="mb-6 h-2 overflow-hidden rounded-full bg-card">
          <div className="h-full bg-accent transition-all duration-500" style={{ width: `${Math.max(2, p.progress * 100)}%` }} />
        </div>
      )}

      <ol className="space-y-3">
        {STAGES.map((s, i) => {
          const done = p.status === "done" || i < current;
          const active = i === current && p.status === "processing";
          const errored = failed && i === Math.max(0, current);
          return (
            <li key={s.key} className="flex items-center gap-3 text-sm">
              <span
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border ${
                  errored ? "border-red-700 bg-red-950 text-red-300"
                    : done ? "border-accent bg-accent text-accent-ink"
                    : active ? "border-white" : "border-line text-zinc-600"
                }`}
              >
                {errored ? <AlertTriangle size={12} /> : done ? <Check size={13} strokeWidth={3} /> : active ? <Loader2 size={13} className="animate-spin" /> : i + 1}
              </span>
              <span className={done || active ? "text-zinc-100" : "text-zinc-500"}>{s.label}</span>
            </li>
          );
        })}
      </ol>

      {failed && (
        <div className="mt-6">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-red-950/40 p-3 text-xs text-red-200">{p.error}</pre>
          <button className="btn-primary mt-4" onClick={onRetry}>
            <RotateCw size={15} /> Try again
          </button>
        </div>
      )}
      {!failed && (
        <p className="mt-6 text-xs text-muted">
          You can leave this page — processing continues in the background. A 1-hour video usually takes a few minutes
          on a GPU and longer on CPU.
        </p>
      )}
    </div>
  );
}
