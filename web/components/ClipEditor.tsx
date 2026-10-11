"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Minus, Pause, Play, Plus, Save, X } from "lucide-react";
import { CaptionPreview } from "@/components/ClipSettings";
import { Clip, Project, api, fmtTime } from "@/lib/api";

type Sentence = { i: number; start: number; end: number; text: string };

const STYLES = ["opus", "bold", "neon", "fire", "minimal", "boxed", "none"];
const ASPECTS = ["9:16", "1:1", "4:5", "16:9"];
const LAYOUTS = [
  { key: "auto", label: "Auto" },
  { key: "crop", label: "Follow speaker" },
  { key: "fit", label: "Blurred bg" },
];

function fmtPrecise(s: number) {
  return `${fmtTime(s)}.${Math.floor((s % 1) * 10)}`;
}

export default function ClipEditor({
  clip,
  project,
  onClose,
  onSaved,
}: {
  clip: Clip;
  project: Project;
  onClose: () => void;
  onSaved: () => void;
}) {
  const defaults = project.settings;
  const [start, setStart] = useState(clip.start);
  const [end, setEnd] = useState(clip.end);
  const [title, setTitle] = useState(clip.title);
  const [headline, setHeadline] = useState(clip.headline);
  const [caption, setCaption] = useState(clip.caption);
  const [tags, setTags] = useState((clip.hashtags || []).join(" "));
  const [style, setStyle] = useState(clip.render?.caption_style ?? defaults.caption_style ?? "opus");
  const [aspect, setAspect] = useState(clip.render?.aspect ?? defaults.aspect ?? "9:16");
  const [layout, setLayout] = useState(clip.render?.layout ?? defaults.layout ?? "auto");
  const [showHeadline, setShowHeadline] = useState(clip.render?.headline ?? defaults.headline ?? true);
  const [sentences, setSentences] = useState<Sentence[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const duration = project.duration ?? clip.end + 60;

  useEffect(() => {
    api.transcript(project.id).then((t) => setSentences(t.sentences)).catch(() => {});
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [project.id, onClose]);

  // Sentences around the clip, so you can extend or shorten on sentence boundaries.
  const nearby = useMemo(
    () => sentences.filter((s) => s.end > start - 45 && s.start < end + 45),
    [sentences, start, end],
  );

  // Preview the selected range from the source video.
  const playRange = () => {
    const v = videoRef.current;
    if (!v) return;
    if (playing) {
      v.pause();
      return;
    }
    v.currentTime = start;
    v.play().catch(() => {});
  };
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => {
      if (v.currentTime >= end) {
        v.pause();
        v.currentTime = start;
      }
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [start, end]);

  const nudge = (which: "start" | "end", d: number) => {
    if (which === "start") setStart((s) => Math.min(Math.max(0, +(s + d).toFixed(2)), end - 1));
    else setEnd((e) => Math.max(Math.min(duration, +(e + d).toFixed(2)), start + 1));
  };

  const len = end - start;

  async function save() {
    setSaving(true);
    setError("");
    try {
      await api.patchClip(clip.id, {
        title: title.trim() || clip.title,
        headline: headline.trim(),
        caption,
        hashtags: tags.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`)),
        start: +start.toFixed(2),
        end: +end.toFixed(2),
        render: { caption_style: style, aspect, layout, headline: showHeadline },
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/70 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true">
      <div className="flex max-h-full w-full max-w-6xl flex-col overflow-hidden border-line bg-bg md:rounded-2xl md:border">
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-semibold">Edit clip</h2>
          <button aria-label="Close editor" onClick={onClose} className="rounded-lg p-1.5 text-zinc-400 hover:bg-card hover:text-white">
            <X size={18} />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 gap-6 overflow-auto p-5 lg:grid-cols-[1fr_380px]">
          {/* Left: preview + trim + transcript */}
          <div className="min-w-0">
            <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
              <div className="overflow-hidden rounded-xl bg-black">
                {project.source_url ? (
                  <video ref={videoRef} src={project.source_url} preload="metadata" className="aspect-video w-full" controls />
                ) : (
                  <div className="grid aspect-video place-items-center text-sm text-muted">Source preview unavailable</div>
                )}
              </div>
              <div className="hidden sm:block">
                <p className="label">Current render</p>
                {clip.url ? (
                  <video src={clip.url} poster={clip.thumbnail_url ?? undefined} controls preload="none" className="aspect-[9/16] w-full rounded-xl bg-black object-cover" />
                ) : (
                  <div className="grid aspect-[9/16] place-items-center rounded-xl bg-card text-xs text-muted">Not rendered</div>
                )}
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-line bg-panel p-4">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <button className="btn-ghost" onClick={playRange} disabled={!project.source_url}>
                  {playing ? <Pause size={15} /> : <Play size={15} />} Preview range
                </button>
                <span className="text-sm text-muted">
                  Length <b className={len > 180 ? "text-amber-300" : "text-white"}>{len.toFixed(1)}s</b>
                </span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {(["start", "end"] as const).map((w) => (
                  <div key={w}>
                    <span className="label">{w === "start" ? "Start" : "End"}</span>
                    <div className="flex items-center gap-2">
                      <button aria-label={`${w} minus 1 second`} className="btn-ghost px-2.5" onClick={() => nudge(w, -1)}><Minus size={14} /></button>
                      <button className="btn-ghost px-2.5 text-xs" onClick={() => nudge(w, -0.2)}>-0.2</button>
                      <span className="flex-1 text-center font-mono text-sm">{fmtPrecise(w === "start" ? start : end)}</span>
                      <button className="btn-ghost px-2.5 text-xs" onClick={() => nudge(w, 0.2)}>+0.2</button>
                      <button aria-label={`${w} plus 1 second`} className="btn-ghost px-2.5" onClick={() => nudge(w, 1)}><Plus size={14} /></button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4">
              <p className="label">Transcript — click a sentence to start or end the clip there</p>
              <div className="max-h-72 space-y-1 overflow-auto rounded-xl border border-line bg-panel p-2">
                {nearby.length === 0 && <p className="p-3 text-sm text-muted">Loading transcript…</p>}
                {nearby.map((s) => {
                  const inside = s.start >= start - 0.3 && s.end <= end + 0.4;
                  return (
                    <div key={s.i} className={`group flex items-start gap-3 rounded-lg px-3 py-2 text-sm ${inside ? "bg-accent/10 text-white" : "text-zinc-400"}`}>
                      <span className="mt-0.5 shrink-0 font-mono text-[11px] text-muted">{fmtTime(s.start)}</span>
                      <span className="flex-1">{s.text}</span>
                      <span className="flex shrink-0 gap-1 opacity-60 group-hover:opacity-100">
                        <button className="rounded-md border border-line px-2 py-0.5 text-[11px] hover:border-zinc-400"
                          onClick={() => { setStart(Math.max(0, s.start - 0.05)); if (s.start >= end) setEnd(s.end + 0.3); }}>
                          Start
                        </button>
                        <button className="rounded-md border border-line px-2 py-0.5 text-[11px] hover:border-zinc-400"
                          onClick={() => { setEnd(s.end + 0.3); if (s.end <= start) setStart(Math.max(0, s.start - 0.05)); }}>
                          End
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Right: text + style */}
          <div className="space-y-4">
            <div>
              <label className="label" htmlFor="ed-title">Title</label>
              <input id="ed-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
            </div>
            <div>
              <label className="label" htmlFor="ed-headline">On-screen headline (first 5 s)</label>
              <input id="ed-headline" className="input" value={headline} onChange={(e) => setHeadline(e.target.value)} maxLength={90} />
              <label className="mt-2 flex items-center gap-2 text-sm text-zinc-300">
                <input type="checkbox" checked={showHeadline} onChange={(e) => setShowHeadline(e.target.checked)} className="accent-[#3cff22]" />
                Show headline
              </label>
            </div>
            <div>
              <label className="label" htmlFor="ed-caption">Post caption</label>
              <textarea id="ed-caption" rows={3} className="input resize-none" value={caption} onChange={(e) => setCaption(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="ed-tags">Hashtags</label>
              <input id="ed-tags" className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="#shorts #podcast" />
            </div>
            <div>
              <span className="label">Caption style</span>
              <div className="grid grid-cols-4 gap-2">
                {STYLES.map((s) => (
                  <button key={s} onClick={() => setStyle(s)}
                    className={`grid h-11 place-items-center rounded-lg border bg-gradient-to-b from-zinc-700 to-zinc-900 ${style === s ? "border-white" : "border-line"}`}
                    title={s}>
                    <CaptionPreview styleKey={s} small />
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="label">Aspect</span>
                <select className="input" value={aspect} onChange={(e) => setAspect(e.target.value)}>
                  {ASPECTS.map((a) => <option key={a}>{a}</option>)}
                </select>
              </div>
              <div>
                <span className="label">Framing</span>
                <select className="input" value={layout} onChange={(e) => setLayout(e.target.value)}>
                  {LAYOUTS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
                </select>
              </div>
            </div>
            {error && <p className="rounded-lg bg-red-950/50 p-3 text-sm text-red-200">{error}</p>}
          </div>
        </div>

        <footer className="flex items-center justify-end gap-3 border-t border-line px-5 py-3">
          <p className="mr-auto hidden text-xs text-muted sm:block">Saving re-renders the clip if timing, headline or style changed.</p>
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={saving || len < 1}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Save & render
          </button>
        </footer>
      </div>
    </div>
  );
}
