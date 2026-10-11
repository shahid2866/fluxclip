// Typed client for the FluxClip Studio API (proxied through Next.js at /api and /files).

export type Stage = "queued" | "downloading" | "transcribing" | "analyzing" | "rendering" | "done";
export type ProjectStatus = "queued" | "processing" | "done" | "failed";
export type ClipStatus = "pending" | "rendering" | "ready" | "failed";

export interface ProjectSettings {
  num_clips: number;
  min_len: number;
  max_len: number;
  prompt?: string | null;
  aspect: string;
  layout: string;
  caption_style: string;
  headline: boolean;
  language?: string | null;
  quality?: string | null;
  range_start?: number | null;
  range_end?: number | null;
}

export interface Clip {
  id: string;
  project_id: string;
  idx: number;
  start: number;
  end: number;
  duration: number;
  title: string;
  headline: string;
  topic: string;
  score: number;
  scores: { hook?: number; flow?: number; value?: number; trend?: number };
  hashtags: string[];
  caption: string;
  reason: string;
  transcript: string;
  render: { aspect?: string; layout?: string; caption_style?: string; headline?: boolean };
  status: ClipStatus;
  error?: string | null;
  layout?: string | null;
  version: number;
  liked: boolean;
  url?: string | null;
  thumbnail_url?: string | null;
  srt_url?: string | null;
}

export interface Project {
  id: string;
  title: string;
  source: string;
  status: ProjectStatus;
  stage: Stage;
  progress: number;
  message: string;
  error?: string | null;
  settings: ProjectSettings;
  duration?: number | null;
  language?: string | null;
  thumbnail_url?: string | null;
  source_url?: string | null;
  created_at: number;
  clip_count?: number;
  queue_position?: number | null;
  clips?: Clip[];
}

export interface Settings {
  provider?: string | null;
  model?: string | null;
  anthropic_api_key?: string | null;
  anthropic_api_key_set?: boolean;
  openai_api_key?: string | null;
  openai_api_key_set?: boolean;
  openai_base_url?: string | null;
  ollama_host?: string | null;
  quality?: string | null;
}

export interface SearchResult {
  sentence: number;
  score: number;
  start: number;
  end: number;
  match_start: number;
  match_end: number;
  text: string;
  context: string;
}

export const DEFAULT_SETTINGS: ProjectSettings = {
  num_clips: 8,
  min_len: 20,
  max_len: 60,
  prompt: "",
  aspect: "9:16",
  layout: "auto",
  caption_style: "opus",
  headline: true,
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => req<{ ok: boolean; provider: string; ffmpeg: boolean }>("/api/health"),
  projects: () => req<Project[]>("/api/projects"),
  project: (id: string) => req<Project>(`/api/projects/${id}`),
  createFromUrl: (source: string, settings: ProjectSettings) =>
    req<Project>("/api/projects", json("POST", { source, settings })),
  deleteProject: (id: string) => req<void>(`/api/projects/${id}`, { method: "DELETE" }),
  retry: (id: string) => req<Project>(`/api/projects/${id}/retry`, { method: "POST" }),
  search: (id: string, q: string) =>
    req<{ results: SearchResult[] }>(`/api/projects/${id}/search?q=${encodeURIComponent(q)}`),
  createClip: (id: string, body: { start: number; end: number; title?: string; headline?: string }) =>
    req<Clip>(`/api/projects/${id}/clips`, json("POST", body)),
  patchClip: (id: string, body: Partial<Pick<Clip, "title" | "headline" | "caption" | "hashtags" | "start" | "end" | "liked">> & { render?: Clip["render"] }) =>
    req<Clip>(`/api/clips/${id}`, json("PATCH", body)),
  rerender: (id: string) => req<Clip>(`/api/clips/${id}/render`, { method: "POST" }),
  deleteClip: (id: string) => req<void>(`/api/clips/${id}`, { method: "DELETE" }),
  transcript: (id: string) =>
    req<{ sentences: { i: number; start: number; end: number; text: string }[]; duration: number }>(
      `/api/projects/${id}/transcript`,
    ),
  settings: () => req<Settings>("/api/settings"),
  saveSettings: (s: Partial<Settings>) => req<Settings>("/api/settings", json("PUT", s)),
};

/** Upload with progress (fetch has no upload progress, so use XHR). */
export function uploadVideo(
  file: File,
  settings: ProjectSettings,
  onProgress: (frac: number) => void,
): Promise<Project> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("settings", JSON.stringify(settings));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects/upload");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new Error(typeof body.detail === "string" ? body.detail : "Upload failed"));
      } catch {
        reject(new Error("Upload failed"));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}

export const isUrl = (s: string) => /^https?:\/\//i.test(s);

export function fmtTime(s: number): string {
  s = Math.max(0, s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function parseTime(v: string): number | null {
  const parts = v.trim().split(":").map(Number);
  if (!parts.length || parts.some((p) => Number.isNaN(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

export const STAGES: { key: Stage; label: string }[] = [
  { key: "downloading", label: "Preparing video" },
  { key: "transcribing", label: "Transcribing" },
  { key: "analyzing", label: "Finding viral moments" },
  { key: "rendering", label: "Rendering clips" },
];
