"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import ProjectCard from "@/components/ProjectCard";
import { Project, api } from "@/lib/api";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "processing", label: "Processing" },
  { key: "done", label: "Ready" },
  { key: "failed", label: "Failed" },
] as const;

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;
    const load = async () => {
      try {
        const ps = await api.projects();
        if (!alive) return;
        setProjects(ps);
        setError("");
        // Keep polling while something is still being processed.
        if (ps.some((p) => p.status === "queued" || p.status === "processing")) timer = setTimeout(load, 2000);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  const shown = useMemo(() => {
    const list = projects ?? [];
    return list.filter((p) => {
      const statusOk =
        filter === "all" ||
        (filter === "processing" ? p.status === "queued" || p.status === "processing" : p.status === filter);
      const text = `${p.title} ${p.source}`.toLowerCase();
      return statusOk && (!q || text.includes(q.toLowerCase()));
    });
  }, [projects, filter, q]);

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-20 md:px-8 md:pt-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">My projects</h1>
        <Link href="/" className="btn-primary">
          <Plus size={16} /> New project
        </Link>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className="input pl-9" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2">
          {FILTERS.map((f) => (
            <button key={f.key} className={`chip ${filter === f.key ? "chip-on" : ""}`} onClick={() => setFilter(f.key)}>
              {f.label}
              {projects && (
                <span className="opacity-60">
                  {f.key === "all"
                    ? projects.length
                    : projects.filter((p) =>
                        f.key === "processing" ? p.status === "queued" || p.status === "processing" : p.status === f.key,
                      ).length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-sm text-red-200">{error}</p>}

      {projects === null && !error && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="aspect-[4/3] animate-pulse rounded-2xl bg-panel" />
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="rounded-2xl border border-dashed border-line p-12 text-center">
          <p className="text-lg font-semibold">No projects yet</p>
          <p className="mt-1 text-sm text-muted">Paste a YouTube link or upload a video to get your first clips.</p>
          <Link href="/" className="btn-primary mt-5">
            <Plus size={16} /> Create your first project
          </Link>
        </div>
      )}

      {projects && projects.length > 0 && shown.length === 0 && (
        <p className="py-10 text-center text-sm text-muted">No projects match your filters.</p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {shown.map((p) => (
          <ProjectCard key={p.id} p={p} />
        ))}
      </div>
    </div>
  );
}
