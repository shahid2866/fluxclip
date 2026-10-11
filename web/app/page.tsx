"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, Link2, Loader2, Sparkles, Upload } from "lucide-react";
import ClipSettings from "@/components/ClipSettings";
import ProjectCard from "@/components/ProjectCard";
import { DEFAULT_SETTINGS, Project, ProjectSettings, api, uploadVideo } from "@/lib/api";

const PROVIDER_NAMES: Record<string, string> = {
  anthropic: "Claude",
  openai: "OpenAI",
  ollama: "Ollama (local)",
  heuristic: "Offline picker",
};

export default function Home() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [settings, setSettings] = useState<ProjectSettings>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [recent, setRecent] = useState<Project[]>([]);
  const [provider, setProvider] = useState<string | null>(null);
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("fluxclip.settings");
      if (saved) setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(saved) });
    } catch {}
    api.projects().then((ps) => setRecent(ps.slice(0, 4))).catch(() => setApiDown(true));
    api.health().then((h) => setProvider(h.provider)).catch(() => setApiDown(true));
  }, []);

  const updateSettings = (s: ProjectSettings) => {
    setSettings(s);
    try {
      localStorage.setItem("fluxclip.settings", JSON.stringify(s));
    } catch {}
  };

  async function submitUrl(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError("");
    try {
      const p = await api.createFromUrl(url.trim(), { ...settings, prompt: settings.prompt || null });
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  async function submitFile(file: File) {
    setBusy(true);
    setError("");
    setUploadPct(0);
    try {
      const p = await uploadVideo(file, { ...settings, prompt: settings.prompt || null }, setUploadPct);
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
      setUploadPct(null);
    }
  }

  return (
    <div
      className="mx-auto max-w-5xl px-4 pb-16 pt-20 md:px-8 md:pt-14"
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files?.[0];
        if (f) submitFile(f);
      }}
    >
      {apiDown && (
        <div className="mb-6 rounded-xl border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Can&apos;t reach the FluxClip API. Start it with <code className="font-mono">fluxclip studio</code> (or{" "}
          <code className="font-mono">docker compose up</code>).
        </div>
      )}

      <div className="mb-8 text-center">
        <h1 className="text-3xl font-extrabold tracking-tight md:text-5xl">
          1 long video, <span className="text-accent">10 viral clips.</span>
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-muted">
          Paste a link or upload a video. FluxClip finds the best moments, reframes them to vertical and adds
          animated captions — open source, on your own machine.
        </p>
      </div>

      <form
        onSubmit={submitUrl}
        className={`flex flex-col gap-2 rounded-2xl border bg-panel p-2 transition sm:flex-row ${
          drag ? "border-accent" : "border-line"
        }`}
      >
        <div className="flex flex-1 items-center gap-3 px-3">
          <Link2 size={18} className="shrink-0 text-muted" />
          <input
            className="h-12 w-full bg-transparent text-[15px] outline-none placeholder:text-zinc-500"
            placeholder="Drop a YouTube link"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
            aria-label="Video link"
          />
        </div>
        <button className="btn-primary h-12 px-6 text-[15px]" disabled={busy || !url.trim()}>
          {busy && uploadPct === null ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
          Get clips in 1 click
        </button>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" className="btn-ghost" onClick={() => fileRef.current?.click()} disabled={busy}>
          <Upload size={16} /> Upload video
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="video/*,.mkv"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && submitFile(e.target.files[0])}
        />
        <span className="text-xs text-muted">or drag & drop a file anywhere · MP4, MOV, MKV, WEBM</span>
        {provider && (
          <Link
            href="/settings"
            className={`ml-auto inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
              provider === "heuristic"
                ? "border-amber-700/60 bg-amber-950/40 text-amber-200"
                : "border-line bg-card text-zinc-300"
            }`}
          >
            <Bot size={13} /> AI: {PROVIDER_NAMES[provider] ?? provider}
            {provider === "heuristic" && " — add an API key for better clips"}
          </Link>
        )}
      </div>

      {uploadPct !== null && (
        <div className="mt-4 rounded-xl border border-line bg-panel p-4">
          <div className="mb-2 flex justify-between text-sm">
            <span>Uploading…</span>
            <span>{Math.round(uploadPct * 100)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-card">
            <div className="h-full bg-accent transition-all" style={{ width: `${uploadPct * 100}%` }} />
          </div>
        </div>
      )}

      {error && (
        <p className="mt-4 rounded-xl border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">{error}</p>
      )}

      <div className="mt-6">
        <ClipSettings value={settings} onChange={updateSettings} />
      </div>

      {recent.length > 0 && (
        <section className="mt-12">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recent projects</h2>
            <Link href="/projects" className="inline-flex items-center gap-1 text-sm text-muted hover:text-white">
              View all <ArrowRight size={14} />
            </Link>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {recent.map((p) => (
              <ProjectCard key={p.id} p={p} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
