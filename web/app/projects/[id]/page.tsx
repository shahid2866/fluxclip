"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ExternalLink, LayoutGrid, List, Trash2 } from "lucide-react";
import ClipCard from "@/components/ClipCard";
import ClipEditor from "@/components/ClipEditor";
import MomentSearch from "@/components/MomentSearch";
import ProgressView from "@/components/ProgressView";
import { Clip, Project, api, fmtTime, isUrl } from "@/lib/api";

type Sort = "score" | "time" | "liked";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<"grid" | "list">("list");
  const [sort, setSort] = useState<Sort>("score");
  const [editing, setEditing] = useState<Clip | null>(null);
  const [streamKey, setStreamKey] = useState(0); // bump to reconnect the live stream
  const lastSnap = useRef("");

  const load = useCallback(async () => {
    try {
      const data = await api.project(id);
      setP(data);
      setError("");
      return data;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  // Live updates: SSE stream from the API, with polling as a fallback.
  useEffect(() => {
    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let alive = true;

    const startPolling = () => {
      if (poll) return;
      poll = setInterval(async () => {
        const d = await load();
        const busy = d && (d.status === "queued" || d.status === "processing" ||
          d.clips?.some((c) => c.status === "pending" || c.status === "rendering"));
        if (!busy && poll) {
          clearInterval(poll);
          poll = null;
        }
      }, 2000);
    };

    const connect = () => {
      es = new EventSource(`/api/projects/${id}/events`);
      es.onmessage = (ev) => {
        if (!alive) return;
        const snap = JSON.parse(ev.data);
        // Progress fields update immediately; refetch the full project when clips change.
        setP((prev) => (prev ? { ...prev, ...snap, clips: prev.clips } : prev));
        const key = JSON.stringify([snap.status, snap.clips]);
        if (key !== lastSnap.current) {
          lastSnap.current = key;
          load();
        }
      };
      es.addEventListener("end", () => {
        es?.close();
        load();
      });
      es.onerror = () => {
        es?.close();
        if (alive) startPolling();
      };
    };

    load().then(connect);
    return () => {
      alive = false;
      es?.close();
      if (poll) clearInterval(poll);
    };
  }, [id, load, streamKey]);

  // After an edit / retry / new clip: reconnect the live stream (it also reloads the project).
  const refreshAfterChange = useCallback(() => {
    lastSnap.current = "";
    setStreamKey((k) => k + 1);
  }, []);

  const groups = useMemo(() => {
    const clips = [...(p?.clips ?? [])];
    if (sort === "time") clips.sort((a, b) => a.start - b.start);
    else if (sort === "liked") clips.sort((a, b) => Number(b.liked) - Number(a.liked) || b.score - a.score);
    else clips.sort((a, b) => b.score - a.score);
    const map = new Map<string, Clip[]>();
    for (const c of clips) {
      const k = c.topic || "Top clips";
      map.set(k, [...(map.get(k) ?? []), c]);
    }
    // Order groups by their best clip.
    return [...map.entries()].sort((a, b) => Math.max(...b[1].map((c) => c.score)) - Math.max(...a[1].map((c) => c.score)));
  }, [p?.clips, sort]);

  if (error && !p) {
    return (
      <div className="mx-auto max-w-xl px-4 pt-24 text-center">
        <p className="text-lg font-semibold">Project not found</p>
        <p className="mt-1 text-sm text-muted">{error}</p>
        <Link href="/projects" className="btn-ghost mt-5">
          <ArrowLeft size={15} /> Back to projects
        </Link>
      </div>
    );
  }
  if (!p) return <div className="p-10 text-muted">Loading…</div>;

  const processing = p.status !== "done";

  return (
    <div className="mx-auto max-w-6xl px-4 pb-20 pt-20 md:px-8 md:pt-8">
      <div className="mb-6 flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link href="/projects" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-white">
            <ArrowLeft size={14} /> My projects
          </Link>
          <h1 className="text-xl font-bold leading-snug md:text-2xl">{p.title || "Untitled project"}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            {p.duration ? <span>{fmtTime(p.duration)} source</span> : null}
            {p.language ? <span>· {p.language.toUpperCase()}</span> : null}
            {p.clips ? <span>· {p.clips.length} clips</span> : null}
            {isUrl(p.source) && (
              <a href={p.source} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-white">
                · Source <ExternalLink size={11} />
              </a>
            )}
          </p>
        </div>
        <button
          className="btn-danger"
          onClick={async () => {
            if (!confirm("Delete this project and all its clips?")) return;
            await api.deleteProject(p.id);
            router.push("/projects");
          }}
        >
          <Trash2 size={15} /> Delete
        </button>
      </div>

      {processing ? (
        <ProgressView
          p={p}
          onRetry={async () => {
            setP(await api.retry(p.id));
            refreshAfterChange();
          }}
        />
      ) : (
        <>
          <MomentSearch projectId={p.id} onCreated={refreshAfterChange} />

          <div className="mb-5 mt-6 flex flex-wrap items-center gap-3">
            <p className="mr-auto text-sm text-muted">
              {(() => {
                const n = p.clips?.filter((c) => c.status === "ready").length ?? 0;
                return `${n} clip${n === 1 ? "" : "s"} ready`;
              })()}
            </p>
            <select className="input w-auto py-2" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort clips">
              <option value="score">Sort: virality score</option>
              <option value="time">Sort: timeline</option>
              <option value="liked">Sort: liked first</option>
            </select>
            <div className="flex rounded-xl border border-line bg-panel p-1">
              <button aria-label="Grid view" onClick={() => setView("grid")}
                className={`rounded-lg p-1.5 ${view === "grid" ? "bg-card text-white" : "text-zinc-500"}`}>
                <LayoutGrid size={16} />
              </button>
              <button aria-label="List view" onClick={() => setView("list")}
                className={`rounded-lg p-1.5 ${view === "list" ? "bg-card text-white" : "text-zinc-500"}`}>
                <List size={16} />
              </button>
            </div>
          </div>

          {p.clips?.length === 0 && (
            <div className="rounded-2xl border border-dashed border-line p-10 text-center text-sm text-muted">
              No clips were found. Try a different clip length, a prompt, or search for a moment above to make one.
            </div>
          )}

          {groups.map(([topic, clips]) => (
            <section key={topic} className="mb-10">
              <h2 className="mb-4 text-sm font-semibold text-muted">
                {topic} <span className="opacity-60">({clips.length})</span>
              </h2>
              {view === "grid" ? (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                  {clips.map((c) => (
                    <ClipCard key={`${c.id}-${c.version}`} clip={c} view="grid" onEdit={setEditing} onChanged={refreshAfterChange} />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {clips.map((c) => (
                    <ClipCard key={`${c.id}-${c.version}`} clip={c} view="list" onEdit={setEditing} onChanged={refreshAfterChange} />
                  ))}
                </div>
              )}
            </section>
          ))}
        </>
      )}

      {editing && (
        <ClipEditor
          clip={editing}
          project={p}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            refreshAfterChange();
          }}
        />
      )}
    </div>
  );
}
