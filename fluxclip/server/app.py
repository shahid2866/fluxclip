"""FluxClip Studio API (FastAPI).

Run:  fluxclip studio            (API on http://localhost:8000)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..captions import THEMES
from ..render import ASPECTS, LAYOUTS
from ..transcribe import Transcript
from ..utils import is_url, slugify
from . import db, jobs

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.conn()
    jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="FluxClip Studio API", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SECRET_KEYS = ("anthropic_api_key", "openai_api_key")


# ------------------------------------------------------------------ models
class ProjectSettings(BaseModel):
    num_clips: int = Field(8, ge=1, le=30)
    min_len: float = Field(20, ge=5, le=180)
    max_len: float = Field(60, ge=10, le=600)
    prompt: str | None = None
    aspect: str = "9:16"
    layout: str = "auto"
    caption_style: str = "opus"
    headline: bool = True
    language: str | None = None
    quality: str | None = None          # None -> studio default
    range_start: float | None = None    # only clip from this part of the video (seconds)
    range_end: float | None = None


class CreateProject(BaseModel):
    source: str
    title: str | None = None
    settings: ProjectSettings = ProjectSettings()


class ClipRender(BaseModel):
    aspect: str | None = None
    layout: str | None = None
    caption_style: str | None = None
    headline: bool | None = None


class ClipPatch(BaseModel):
    title: str | None = None
    headline: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    start: float | None = None
    end: float | None = None
    liked: bool | None = None
    render: ClipRender | None = None


class NewClip(BaseModel):
    start: float
    end: float
    snap: bool = True  # align to sentence boundaries
    title: str | None = None
    headline: str | None = None


class SettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    ollama_host: str | None = None
    quality: str | None = None


# ----------------------------------------------------------------- helpers
def _validate(s: ProjectSettings) -> None:
    if s.aspect not in ASPECTS:
        raise HTTPException(422, f"aspect must be one of {list(ASPECTS)}")
    if s.layout not in LAYOUTS:
        raise HTTPException(422, f"layout must be one of {list(LAYOUTS)}")
    if s.caption_style not in [*THEMES, "none"]:
        raise HTTPException(422, f"caption_style must be one of {[*THEMES, 'none']}")
    if s.min_len >= s.max_len:
        raise HTTPException(422, "min_len must be smaller than max_len")


def _file_url(pid: str, rel: str | None, version: int = 0) -> str | None:
    return f"/files/{pid}/{rel}?v={version}" if rel else None


def _clip_out(c: dict) -> dict:
    c = dict(c)
    c["duration"] = round(c["end"] - c["start"], 2)
    c["url"] = _file_url(c["project_id"], c.get("file"), c.get("version", 0))
    c["thumbnail_url"] = _file_url(c["project_id"], c.get("thumbnail"), c.get("version", 0))
    srt = str(Path(c["file"]).with_suffix(".srt")) if c.get("file") else None
    c["srt_url"] = _file_url(c["project_id"], srt, c.get("version", 0))
    return c


def _project_out(p: dict, with_clips: bool = False) -> dict:
    p = dict(p)
    p["thumbnail_url"] = _file_url(p["id"], p.get("thumbnail"))
    sp = p.get("source_path")
    p["source_url"] = _file_url(p["id"], Path(sp).name) if sp and Path(sp).parent.name == p["id"] else None
    p.pop("source_path", None)  # don't leak server paths to the browser
    p["queue_position"] = jobs.queue_position(p["id"])
    if with_clips:
        p["clips"] = [_clip_out(c) for c in db.list_clips(p["id"])]
    return p


def _need_project(pid: str) -> dict:
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _need_clip(cid: str) -> dict:
    c = db.get_clip(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    return c


def _transcript(pid: str) -> Transcript:
    path = db.project_dir(pid) / "transcript.json"
    if not path.exists():
        raise HTTPException(409, "Transcript not ready yet")
    return Transcript.load(path)


def _mask(settings: dict) -> dict:
    out = dict(settings)
    for k in SECRET_KEYS:
        v = out.get(k)
        if v:
            out[k] = f"••••{v[-4:]}"
            out[f"{k}_set"] = True
        else:
            out[f"{k}_set"] = False
    return out


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "ffmpeg": shutil.which("ffmpeg") is not None,
            "provider": jobs.effective_provider(), "data_dir": str(db.data_dir())}


@app.get("/api/options")
def options() -> dict:
    return {"aspects": list(ASPECTS), "layouts": list(LAYOUTS), "caption_styles": [*THEMES, "none"],
            "providers": ["auto", "anthropic", "openai", "ollama", "heuristic"],
            "qualities": ["auto", "fast", "balanced", "best"]}


@app.get("/api/settings")
def get_settings() -> dict:
    return _mask(db.get_settings())


@app.put("/api/settings")
def put_settings(body: SettingsIn) -> dict:
    values = body.model_dump(exclude_unset=True)
    for k in SECRET_KEYS:  # never overwrite a stored key with its masked echo
        if isinstance(values.get(k), str) and values[k].startswith("••••"):
            values.pop(k)
    values = {k: (v if v != "" else None) for k, v in values.items()}
    return _mask(db.set_settings(values))


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [_project_out(p) for p in db.list_projects()]


@app.post("/api/projects", status_code=201)
def create_project(body: CreateProject) -> dict:
    _validate(body.settings)
    if not is_url(body.source):
        raise HTTPException(422, "source must be an http(s) link; use /api/projects/upload for files")
    p = db.create_project(body.source.strip(), body.settings.model_dump(), title=body.title or "")
    jobs.enqueue_project(p["id"])
    return _project_out(db.get_project(p["id"]))


@app.post("/api/projects/upload", status_code=201)
async def upload_project(file: UploadFile = File(...), settings: str = Form("{}"),
                         title: str = Form("")) -> dict:
    try:
        s = ProjectSettings(**json.loads(settings or "{}"))
    except Exception as e:
        raise HTTPException(422, f"Invalid settings: {e}") from e
    _validate(s)
    name = file.filename or "video.mp4"
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(422, f"Unsupported file type {ext}. Use {sorted(VIDEO_EXT)}")
    p = db.create_project(f"upload:{name}", s.model_dump(), title=title or Path(name).stem)
    dest = db.project_dir(p["id"]) / f"source{ext}"
    with dest.open("wb") as fh:
        while chunk := await file.read(8 * 1024 * 1024):
            fh.write(chunk)
    db.update_project(p["id"], source_path=str(dest))
    jobs.enqueue_project(p["id"])
    return _project_out(db.get_project(p["id"]))


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _project_out(_need_project(pid), with_clips=True)


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str) -> None:
    _need_project(pid)
    jobs.cancel_project(pid)
    db.delete_project(pid)
    shutil.rmtree(db.data_dir() / "projects" / pid, ignore_errors=True)


@app.post("/api/projects/{pid}/retry")
def retry_project(pid: str) -> dict:
    p = _need_project(pid)
    if p["status"] not in ("failed", "done"):
        raise HTTPException(409, "Project is still processing")
    db.update_project(pid, status="queued", stage="queued", progress=0, error=None, message="")
    jobs.enqueue_project(pid)
    return _project_out(db.get_project(pid))


@app.get("/api/projects/{pid}/events")
async def project_events(pid: str) -> StreamingResponse:
    """Server-sent events with live progress until the project finishes."""
    _need_project(pid)

    async def stream():
        last = None
        while True:
            p = db.get_project(pid)
            if not p:
                yield "event: deleted\ndata: {}\n\n"
                return
            clips = db.list_clips(pid)
            snap = {k: p[k] for k in ("status", "stage", "progress", "message", "error")}
            snap["clips"] = [{"id": c["id"], "status": c["status"], "version": c["version"]} for c in clips]
            snap["queue_position"] = jobs.queue_position(pid)
            if snap != last:
                yield f"data: {json.dumps(snap)}\n\n"
                last = snap
            busy = p["status"] in ("queued", "processing") or any(
                c["status"] in ("pending", "rendering") for c in clips)
            if not busy:
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/projects/{pid}/transcript")
def get_transcript(pid: str) -> dict:
    _need_project(pid)
    t = _transcript(pid)
    return {"language": t.language, "duration": t.duration,
            "sentences": [{"i": i, "start": s.start, "end": s.end, "text": s.text}
                          for i, s in enumerate(t.sentences())]}


@app.get("/api/projects/{pid}/search")
def search(pid: str, q: str, limit: int = 20) -> dict:
    """Find keywords or moments: matches sentences, returns them with surrounding context."""
    _need_project(pid)
    q = q.strip()
    if not q:
        return {"query": q, "results": []}
    sents = _transcript(pid).sentences()
    terms = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]
    phrase = q.lower()
    results = []
    for i, s in enumerate(sents):
        low = s.text.lower()
        hits = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}", low))
        if phrase in low:
            hits += len(terms) + 1
        if hits == 0 or (len(terms) > 1 and hits < max(1, len(terms) // 2)):
            continue
        a, b = max(0, i - 1), min(len(sents) - 1, i + 2)
        results.append({
            "sentence": i, "score": hits, "start": sents[a].start, "end": sents[b].end,
            "match_start": s.start, "match_end": s.end, "text": s.text,
            "context": " ".join(x.text for x in sents[a:b + 1]),
        })
    results.sort(key=lambda r: (-r["score"], r["start"]))
    return {"query": q, "results": results[:limit]}


@app.post("/api/projects/{pid}/clips", status_code=201)
def create_clip(pid: str, body: NewClip) -> dict:
    p = _need_project(pid)
    if p["status"] != "done":
        raise HTTPException(409, "Wait for the project to finish first")
    if body.end - body.start < 1:
        raise HTTPException(422, "Clip must be at least 1 second long")
    t = _transcript(pid)
    start, end = body.start, body.end
    if body.snap:
        # Start on the sentence containing `start`, end at the end of the sentence containing `end`.
        sents = t.sentences()
        if sents:
            first = max((s for s in sents if s.start <= start + 0.3), key=lambda s: s.start, default=sents[0])
            last = min((s for s in sents if s.end >= end - 0.3), key=lambda s: s.end, default=sents[-1])
            start, end = max(0.0, first.start - 0.05), min(t.duration or last.end + 0.3, last.end + 0.3)
    text = t.text_between(start, end)
    first_sentence = next((s.text for s in t.sentences() if s.end > start), text)
    title = body.title or (text[:57] + "…" if len(text) > 60 else text) or "Custom clip"
    headline = body.headline or " ".join(str(first_sentence).split()[:9])
    idx = max([c["idx"] for c in db.list_clips(pid)] or [0]) + 1
    c = db.add_clip(pid, idx, start=round(start, 2), end=round(end, 2), title=title,
                    headline=headline, topic="Custom clips", transcript=text,
                    render={}, status="pending")
    jobs.enqueue_render(c["id"])
    return _clip_out(db.get_clip(c["id"]))


@app.patch("/api/clips/{cid}")
def patch_clip(cid: str, body: ClipPatch) -> dict:
    c = _need_clip(cid)
    data = body.model_dump(exclude_unset=True)
    needs_render = False
    if "render" in data:
        r = {**(c.get("render") or {}), **{k: v for k, v in (data.pop("render") or {}).items() if v is not None}}
        if r.get("aspect") and r["aspect"] not in ASPECTS:
            raise HTTPException(422, "bad aspect")
        if r.get("layout") and r["layout"] not in LAYOUTS:
            raise HTTPException(422, "bad layout")
        if r.get("caption_style") and r["caption_style"] not in [*THEMES, "none"]:
            raise HTTPException(422, "bad caption_style")
        if r != c.get("render"):
            data["render"] = r
            needs_render = True
    start, end = data.get("start", c["start"]), data.get("end", c["end"])
    if end - start < 1:
        raise HTTPException(422, "Clip must be at least 1 second long")
    if "start" in data or "end" in data:
        needs_render = True
        path = db.project_dir(c["project_id"]) / "transcript.json"
        if path.exists():
            data["transcript"] = Transcript.load(path).text_between(start, end)
    if "headline" in data:
        needs_render = True
    db.update_clip(cid, **data)
    if needs_render:
        db.update_clip(cid, status="pending")
        jobs.enqueue_render(cid)
    return _clip_out(db.get_clip(cid))


@app.post("/api/clips/{cid}/render")
def rerender_clip(cid: str) -> dict:
    _need_clip(cid)
    db.update_clip(cid, status="pending", error=None)
    jobs.enqueue_render(cid)
    return _clip_out(db.get_clip(cid))


@app.delete("/api/clips/{cid}", status_code=204)
def delete_clip(cid: str) -> None:
    c = _need_clip(cid)
    d = db.project_dir(c["project_id"])
    for key in ("file", "thumbnail"):
        if c.get(key):
            (d / c[key]).unlink(missing_ok=True)
    db.delete_clip(cid)


@app.get("/files/{pid}/{path:path}")
def files(pid: str, path: str, download: bool = False) -> FileResponse:
    base = (db.data_dir() / "projects" / pid).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found")
    name = None
    if download:
        clip = next((c for c in db.list_clips(pid) if c.get("file") == path), None)
        name = f"{slugify(clip['title'])}{target.suffix}" if clip else target.name
    return FileResponse(target, filename=name)


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


__all__: list[Any] = ["app", "main"]
