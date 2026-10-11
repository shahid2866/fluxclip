"use client";

import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { ProjectSettings, fmtTime, parseTime } from "@/lib/api";

const LENGTHS = [
  { label: "<30s", min: 10, max: 30 },
  { label: "30–60s", min: 30, max: 60 },
  { label: "20–60s", min: 20, max: 60 },
  { label: "60–90s", min: 60, max: 90 },
  { label: "90s–3m", min: 90, max: 180 },
];

const STYLES: { key: string; label: string; hi: string; upper: boolean }[] = [
  { key: "opus", label: "Opus", hi: "#3cff22", upper: true },
  { key: "bold", label: "Bold", hi: "#ffe500", upper: true },
  { key: "neon", label: "Neon", hi: "#33ff66", upper: true },
  { key: "fire", label: "Fire", hi: "#ff5b24", upper: true },
  { key: "minimal", label: "Minimal", hi: "#ffffff", upper: false },
  { key: "boxed", label: "Boxed", hi: "#ffe500", upper: false },
  { key: "none", label: "No captions", hi: "", upper: false },
];

const ASPECTS = ["9:16", "1:1", "4:5", "16:9"];
const LAYOUTS = [
  { key: "auto", label: "Auto" },
  { key: "crop", label: "Follow speaker" },
  { key: "fit", label: "Blurred background" },
];

export function CaptionPreview({ styleKey, small = false }: { styleKey: string; small?: boolean }) {
  const st = STYLES.find((s) => s.key === styleKey) ?? STYLES[0];
  if (st.key === "none") return <span className="text-xs text-muted">Off</span>;
  const words = st.upper ? ["THIS", "IS", "VIRAL"] : ["This", "is", "viral"];
  const boxed = st.key === "boxed";
  return (
    <span
      className={`font-extrabold ${small ? "text-[11px]" : "text-sm"} ${boxed ? "rounded bg-black/80 px-1.5 py-0.5" : ""}`}
      style={{ textShadow: boxed ? undefined : "0 0 3px #000, 0 0 3px #000, 0 2px 4px #000" }}
    >
      {words.map((w, i) => (
        <span key={w} style={{ color: i === 1 ? st.hi : "#fff" }}>
          {w}{" "}
        </span>
      ))}
    </span>
  );
}

export default function ClipSettings({
  value,
  onChange,
}: {
  value: ProjectSettings;
  onChange: (v: ProjectSettings) => void;
}) {
  const [open, setOpen] = useState(false);
  const set = (patch: Partial<ProjectSettings>) => onChange({ ...value, ...patch });
  const lengthKey = LENGTHS.find((l) => l.min === value.min_len && l.max === value.max_len)?.label;

  return (
    <div className="rounded-2xl border border-line bg-panel">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2.5 text-sm font-semibold">
          <SlidersHorizontal size={16} /> Clip settings
          <span className="hidden font-normal text-muted sm:inline">
            · {value.num_clips} clips · {lengthKey ?? `${value.min_len}–${value.max_len}s`} · {value.aspect} ·{" "}
            {STYLES.find((s) => s.key === value.caption_style)?.label}
          </span>
        </span>
        <ChevronDown size={18} className={`transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="grid gap-6 border-t border-line px-5 py-5 lg:grid-cols-2">
          <div>
            <label className="label">Number of clips: {value.num_clips}</label>
            <input
              type="range"
              min={1}
              max={20}
              value={value.num_clips}
              onChange={(e) => set({ num_clips: Number(e.target.value) })}
              className="w-full accent-[#3cff22]"
            />
          </div>

          <div>
            <span className="label">Clip length</span>
            <div className="flex flex-wrap gap-2">
              {LENGTHS.map((l) => (
                <button
                  type="button"
                  key={l.label}
                  className={`chip ${lengthKey === l.label ? "chip-on" : ""}`}
                  onClick={() => set({ min_len: l.min, max_len: l.max })}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <div className="lg:col-span-2">
            <span className="label">Caption style</span>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
              {STYLES.map((s) => (
                <button
                  type="button"
                  key={s.key}
                  onClick={() => set({ caption_style: s.key })}
                  className={`flex flex-col items-center gap-2 rounded-xl border p-3 transition ${
                    value.caption_style === s.key ? "border-white bg-card" : "border-line hover:border-zinc-500"
                  }`}
                >
                  <span className="grid h-12 w-full place-items-center rounded-lg bg-gradient-to-b from-zinc-700 to-zinc-900">
                    <CaptionPreview styleKey={s.key} small />
                  </span>
                  <span className="text-xs text-zinc-300">{s.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="label">Aspect ratio</span>
            <div className="flex flex-wrap gap-2">
              {ASPECTS.map((a) => (
                <button type="button" key={a} className={`chip ${value.aspect === a ? "chip-on" : ""}`}
                  onClick={() => set({ aspect: a })}>
                  {a}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="label">Framing</span>
            <div className="flex flex-wrap gap-2">
              {LAYOUTS.map((l) => (
                <button type="button" key={l.key} className={`chip ${value.layout === l.key ? "chip-on" : ""}`}
                  onClick={() => set({ layout: l.key })}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-line bg-card px-4 py-3">
            <span>
              <span className="block text-sm font-semibold">Auto headline</span>
              <span className="text-xs text-muted">Hook text box over the first 5 seconds</span>
            </span>
            <input
              type="checkbox"
              checked={value.headline}
              onChange={(e) => set({ headline: e.target.checked })}
              className="h-5 w-5 accent-[#3cff22]"
            />
          </label>

          <div>
            <span className="label">Processing timeframe (optional)</span>
            <div className="flex items-center gap-2">
              <input
                className="input"
                placeholder="Start 00:00"
                defaultValue={value.range_start != null ? fmtTime(value.range_start) : ""}
                onBlur={(e) => set({ range_start: e.target.value ? parseTime(e.target.value) : null })}
              />
              <span className="text-muted">–</span>
              <input
                className="input"
                placeholder="End (full video)"
                defaultValue={value.range_end != null ? fmtTime(value.range_end) : ""}
                onBlur={(e) => set({ range_end: e.target.value ? parseTime(e.target.value) : null })}
              />
            </div>
          </div>

          <div className="lg:col-span-2">
            <label className="label" htmlFor="prompt">
              Clip prompt (optional)
            </label>
            <textarea
              id="prompt"
              rows={2}
              className="input resize-none"
              placeholder='e.g. "Stories with specific numbers, skip the intro and sponsor"'
              value={value.prompt ?? ""}
              onChange={(e) => set({ prompt: e.target.value })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
