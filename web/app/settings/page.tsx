"use client";

import { useEffect, useState } from "react";
import { Check, Eye, EyeOff, Loader2, Save } from "lucide-react";
import { Settings, api } from "@/lib/api";

const PROVIDERS = [
  { key: "auto", name: "Auto", desc: "Claude if a key is set, then OpenAI, then Ollama, else offline." },
  { key: "anthropic", name: "Claude", desc: "Best clip picks and titles. Needs an Anthropic API key." },
  { key: "openai", name: "OpenAI / compatible", desc: "OpenAI, Groq, OpenRouter, LM Studio… via base URL." },
  { key: "ollama", name: "Ollama (local)", desc: "Free and private. Needs Ollama running locally." },
  { key: "heuristic", name: "Offline picker", desc: "No AI. Keyword-based; weakest results." },
];

const QUALITIES = [
  { key: "auto", name: "Auto", desc: "large-v3-turbo on a GPU, small on CPU" },
  { key: "fast", name: "Fast", desc: "Whisper base" },
  { key: "balanced", name: "Balanced", desc: "Whisper small" },
  { key: "best", name: "Best", desc: "Whisper large-v3-turbo (slow on CPU)" },
];

function SecretInput({ id, value, onChange, isSet, placeholder }: {
  id: string; value: string; onChange: (v: string) => void; isSet?: boolean; placeholder: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={show ? "text" : "password"}
        className="input pr-10 font-mono"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isSet ? "Saved — type to replace, clear to remove" : placeholder}
        autoComplete="off"
        spellCheck={false}
      />
      <button type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide key" : "Show key"}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-white">
        {show ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [active, setActive] = useState<string>("");

  const load = async () => {
    const data = await api.settings();
    setS(data);
    setForm({
      provider: data.provider ?? "auto",
      model: data.model ?? "",
      anthropic_api_key: data.anthropic_api_key ?? "",
      openai_api_key: data.openai_api_key ?? "",
      openai_base_url: data.openai_base_url ?? "",
      ollama_host: data.ollama_host ?? "",
      quality: data.quality ?? "auto",
    });
    api.health().then((h) => setActive(h.provider)).catch(() => {});
  };

  useEffect(() => {
    load().catch((e) => setError((e as Error).message));
  }, []);

  const set = (k: string, v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setSaved(false);
  };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.saveSettings({
        ...form,
        provider: form.provider === "auto" ? "" : form.provider,
        quality: form.quality === "auto" ? "" : form.quality,
      });
      await load();
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!s) return <div className="p-10 text-muted">{error || "Loading…"}</div>;

  const provider = form.provider;

  return (
    <form onSubmit={save} className="mx-auto max-w-3xl px-4 pb-20 pt-20 md:px-8 md:pt-10">
      <h1 className="text-2xl font-bold">Settings</h1>
      <p className="mt-1 text-sm text-muted">
        Stored only in your local FluxClip database. Currently using:{" "}
        <b className="text-white">{PROVIDERS.find((p) => p.key === active)?.name ?? active}</b>
      </p>

      <section className="mt-8">
        <h2 className="mb-3 font-semibold">AI for picking clips</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {PROVIDERS.map((p) => (
            <button type="button" key={p.key} onClick={() => set("provider", p.key)}
              className={`rounded-xl border p-4 text-left transition ${provider === p.key ? "border-white bg-card" : "border-line bg-panel hover:border-zinc-500"}`}>
              <span className="flex items-center justify-between text-sm font-semibold">
                {p.name} {provider === p.key && <Check size={15} className="text-accent" />}
              </span>
              <span className="mt-1 block text-xs text-muted">{p.desc}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="mt-8 space-y-5 rounded-2xl border border-line bg-panel p-5">
        {(provider === "anthropic" || provider === "auto") && (
          <div>
            <label className="label" htmlFor="ak">Anthropic API key</label>
            <SecretInput id="ak" value={form.anthropic_api_key} onChange={(v) => set("anthropic_api_key", v)}
              isSet={s.anthropic_api_key_set} placeholder="sk-ant-…" />
            <p className="mt-1.5 text-xs text-muted">Get one at console.anthropic.com → API keys.</p>
          </div>
        )}
        {(provider === "openai" || provider === "auto") && (
          <>
            <div>
              <label className="label" htmlFor="ok">OpenAI (or compatible) API key</label>
              <SecretInput id="ok" value={form.openai_api_key} onChange={(v) => set("openai_api_key", v)}
                isSet={s.openai_api_key_set} placeholder="sk-…" />
            </div>
            <div>
              <label className="label" htmlFor="ob">Base URL (optional)</label>
              <input id="ob" className="input" value={form.openai_base_url} onChange={(e) => set("openai_base_url", e.target.value)}
                placeholder="https://api.openai.com/v1 — or Groq / OpenRouter / LM Studio URL" />
            </div>
          </>
        )}
        {(provider === "ollama" || provider === "auto") && (
          <div>
            <label className="label" htmlFor="oh">Ollama host (optional)</label>
            <input id="oh" className="input" value={form.ollama_host} onChange={(e) => set("ollama_host", e.target.value)}
              placeholder="http://localhost:11434" />
          </div>
        )}
        {provider !== "heuristic" && (
          <div>
            <label className="label" htmlFor="model">Model (optional)</label>
            <input id="model" className="input" value={form.model} onChange={(e) => set("model", e.target.value)}
              placeholder="Default: claude-sonnet-4-5 · gpt-4o-mini · llama3.1" />
          </div>
        )}
        {provider === "heuristic" && <p className="text-sm text-muted">No key needed. Clips are picked by keywords and pacing.</p>}
      </section>

      <section className="mt-8">
        <h2 className="mb-3 font-semibold">Transcription quality</h2>
        <div className="grid gap-2 sm:grid-cols-4">
          {QUALITIES.map((q) => (
            <button type="button" key={q.key} onClick={() => set("quality", q.key)}
              className={`rounded-xl border p-3 text-left transition ${form.quality === q.key ? "border-white bg-card" : "border-line bg-panel hover:border-zinc-500"}`}>
              <span className="block text-sm font-semibold">{q.name}</span>
              <span className="mt-0.5 block text-xs text-muted">{q.desc}</span>
            </button>
          ))}
        </div>
      </section>

      {error && <p className="mt-6 rounded-xl bg-red-950/50 p-3 text-sm text-red-200">{error}</p>}

      <div className="mt-8 flex items-center gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Save settings
        </button>
        {saved && <span className="inline-flex items-center gap-1 text-sm text-accent"><Check size={15} /> Saved</span>}
      </div>
    </form>
  );
}
