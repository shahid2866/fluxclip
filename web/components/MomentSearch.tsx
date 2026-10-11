"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Scissors, Search, X } from "lucide-react";
import { SearchResult, api, fmtTime } from "@/lib/api";

function highlight(text: string, q: string) {
  const terms = q.toLowerCase().match(/\w{2,}/g) ?? [];
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) =>
    re.test(part) && i % 2 === 1 ? (
      <mark key={i} className="rounded bg-accent/25 px-0.5 text-white">{part}</mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

/** "Find keywords or moments": search the transcript and turn any hit into a clip. */
export default function MomentSearch({ projectId, onCreated }: { projectId: string; onCreated: () => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [making, setMaking] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    clearTimeout(timer.current);
    if (!q.trim()) {
      setResults(null);
      return;
    }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        setResults((await api.search(projectId, q)).results);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer.current);
  }, [q, projectId]);

  const makeClip = async (r: SearchResult) => {
    setMaking(r.sentence);
    setMsg("");
    try {
      // Pad short moments to a watchable length using the surrounding context.
      let { start, end } = r;
      if (end - start < 15) end = start + 15;
      await api.createClip(projectId, { start, end });
      setMsg("Clip created — it's rendering now under “Custom clips”.");
      onCreated();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setMaking(null);
    }
  };

  return (
    <div className="rounded-2xl border border-line bg-panel">
      <div className="flex items-center gap-3 px-4">
        <Search size={17} className="shrink-0 text-muted" />
        <input
          className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-zinc-500"
          placeholder="Find keywords or moments… (e.g. “pricing”, “the dog portrait story”)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search the transcript"
        />
        {loading && <Loader2 size={16} className="animate-spin text-muted" />}
        {q && (
          <button aria-label="Clear search" onClick={() => setQ("")} className="text-muted hover:text-white">
            <X size={16} />
          </button>
        )}
      </div>
      {msg && <p className="border-t border-line px-4 py-2 text-xs text-accent">{msg}</p>}
      {results && (
        <div className="max-h-96 overflow-auto border-t border-line p-2">
          {results.length === 0 && !loading && <p className="p-3 text-sm text-muted">No moments found for “{q}”.</p>}
          {results.map((r) => (
            <div key={r.sentence} className="flex items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-card">
              <span className="mt-0.5 shrink-0 font-mono text-xs text-muted">{fmtTime(r.match_start)}</span>
              <p className="flex-1 text-sm leading-relaxed text-zinc-300">{highlight(r.context, q)}</p>
              <button className="btn-ghost shrink-0 px-3 py-1.5 text-xs" onClick={() => makeClip(r)} disabled={making !== null}>
                {making === r.sentence ? <Loader2 size={13} className="animate-spin" /> : <Scissors size={13} />} Make clip
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
