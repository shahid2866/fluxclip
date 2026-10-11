"""Background job runner for FluxClip Studio.

One worker thread processes a FIFO queue of jobs:
  ("project", project_id) – download -> transcribe -> find clips -> render all clips
  ("render", clip_id)     – (re-)render a single clip after an edit

Progress is written to SQLite; the API streams it to the browser via SSE.
Jobs that were interrupted by a restart are re-queued on startup.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import traceback
from pathlib import Path

from ..highlights import find_highlights
from ..llm import resolve_provider
from ..render import RenderOptions, make_thumbnail, render_clip
from ..transcribe import Segment, Transcript, transcribe
from ..utils import FluxClipError, probe, resolve_input, run, slugify
from . import db

log = logging.getLogger("fluxclip.studio")

_q: queue.Queue = queue.Queue()
_pending: list[tuple[str, str]] = []
_pending_lock = threading.Lock()
_cancelled: set[str] = set()
_thread: threading.Thread | None = None
_stop = threading.Event()

ENV_MAP = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
    "ollama_host": "OLLAMA_HOST",
    "model": "FLUXCLIP_MODEL",
}
_env_baseline = {v: os.environ.get(v) for v in ENV_MAP.values()}


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ queue
def _put(kind: str, ident: str) -> None:
    with _pending_lock:
        if (kind, ident) in _pending:
            return
        _pending.append((kind, ident))
    _q.put((kind, ident))


def enqueue_project(pid: str) -> None:
    _cancelled.discard(pid)
    _put("project", pid)


def enqueue_render(cid: str) -> None:
    _put("render", cid)


def queue_position(pid: str) -> int | None:
    with _pending_lock:
        items = [i for k, i in _pending if k == "project"]
    return items.index(pid) if pid in items else None


def cancel_project(pid: str) -> None:
    _cancelled.add(pid)


def apply_settings() -> dict:
    """Copy Studio settings (API keys, model…) into the environment used by the engine."""
    s = db.get_settings()
    for key, env in ENV_MAP.items():
        val = s.get(key)
        if val:
            os.environ[env] = str(val)
        elif _env_baseline.get(env) is not None:
            os.environ[env] = _env_baseline[env]
        else:
            os.environ.pop(env, None)
    return s


def effective_provider() -> str:
    s = apply_settings()
    try:
        return resolve_provider(s.get("provider") or "auto")
    except FluxClipError:
        return "heuristic"


# ----------------------------------------------------------------- worker
def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    # Recover work interrupted by a restart.
    for p in db.list_projects():
        if p["status"] in ("queued", "processing"):
            enqueue_project(p["id"])
        else:
            for c in db.list_clips(p["id"]):
                if c["status"] in ("pending", "rendering"):
                    enqueue_render(c["id"])
    _thread = threading.Thread(target=_loop, name="fluxclip-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    _q.put(("stop", ""))


def _loop() -> None:
    while not _stop.is_set():
        kind, ident = _q.get()
        if kind == "stop":
            break
        try:
            if kind == "project":
                _run_project(ident)
            elif kind == "render":
                _run_render(ident)
        except Exception:  # never let one job kill the worker
            log.error("Job %s %s crashed:\n%s", kind, ident, traceback.format_exc())
        finally:
            with _pending_lock:
                if (kind, ident) in _pending:
                    _pending.remove((kind, ident))


def run_sync(kind: str, ident: str) -> None:
    """Run one job in the current thread (used by tests)."""
    (_run_project if kind == "project" else _run_render)(ident)


# ---------------------------------------------------------------- helpers
def _check(pid: str) -> None:
    if pid in _cancelled or db.get_project(pid) is None:
        raise Cancelled()


def _set(pid: str, **fields) -> None:
    if db.get_project(pid) is not None:
        db.update_project(pid, **fields)


def _render_options(project: dict, clip: dict) -> RenderOptions:
    s = {**(project.get("settings") or {}), **(clip.get("render") or {})}
    return RenderOptions(
        aspect=s.get("aspect", "9:16"), layout=s.get("layout", "auto"),
        caption_style=s.get("caption_style", "opus"), headline=bool(s.get("headline", True)),
    )


def _render_row(project: dict, clip: dict, transcript: Transcript | None) -> None:
    pdir = db.project_dir(project["id"])
    version = int(clip.get("version") or 0) + 1
    rel = f"clips/{clip['idx']:02d}_{slugify(clip['title'])}_v{version}.mp4"
    db.update_clip(clip["id"], status="rendering", error=None)
    try:
        meta = render_clip(project["source_path"], clip["start"], clip["end"], pdir / rel, transcript,
                           _render_options(project, clip), title=clip["title"], headline=clip["headline"])
        thumb = make_thumbnail(meta["path"], at=min(1.0, (clip["end"] - clip["start"]) / 2))
    except Exception as e:
        db.update_clip(clip["id"], status="failed", error=str(e)[:2000])
        raise
    # Remove the previous version's files.
    for key in ("file", "thumbnail"):
        old = clip.get(key)
        if old and old != rel:
            (pdir / old).unlink(missing_ok=True)
            if key == "file":
                (pdir / old).with_suffix(".srt").unlink(missing_ok=True)
    db.update_clip(clip["id"], status="ready", file=rel, thumbnail=str(Path(rel).with_suffix(".jpg")),
                   layout=meta["layout"], version=version, start=meta["start"], end=meta["end"])
    _ = thumb


def _load_transcript(pid: str) -> Transcript | None:
    path = db.project_dir(pid) / "transcript.json"
    return Transcript.load(path) if path.exists() else None


# ------------------------------------------------------------ project job
def _run_project(pid: str) -> None:
    p = db.get_project(pid)
    if not p or pid in _cancelled:
        return
    settings = apply_settings()
    cfg = p.get("settings") or {}
    pdir = db.project_dir(pid)
    try:
        _set(pid, status="processing", stage="downloading", progress=0.02, message="Preparing video…", error=None)

        # 1. Source video ------------------------------------------------
        src = p.get("source_path")
        if not src or not Path(src).exists():
            info: dict = {}
            _set(pid, message="Downloading video…")
            path = resolve_input(p["source"], workdir=pdir / "download", info_out=info)
            dest = pdir / f"source{path.suffix}"
            shutil.move(str(path), dest)
            shutil.rmtree(pdir / "download", ignore_errors=True)
            src = str(dest)
            db.update_project(pid, source_path=src, title=p["title"] or info.get("title", "") or dest.stem)
        _check(pid)
        vi = probe(src)
        thumb = pdir / "thumbnail.jpg"
        try:
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(vi.duration * 0.1, 30):.2f}", "-i", src,
                 "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(thumb)])
            db.update_project(pid, thumbnail="thumbnail.jpg")
        except FluxClipError:
            pass
        db.update_project(pid, duration=vi.duration, progress=0.1)

        # 2. Transcribe ---------------------------------------------------
        _set(pid, stage="transcribing", message="Transcribing speech…")

        def on_tx(frac: float) -> None:
            _check(pid)
            _set(pid, progress=round(0.1 + 0.4 * min(1.0, frac), 3),
                 message=f"Transcribing speech… {int(frac * 100)}%")

        t = transcribe(src, cfg.get("quality") or settings.get("quality") or "auto",
                       cfg.get("language"), on_progress=on_tx)
        t.save(pdir / "transcript.json")
        db.update_project(pid, language=t.language, progress=0.5)
        _check(pid)

        # 3. Find clips ---------------------------------------------------
        provider = settings.get("provider") or "auto"
        _set(pid, stage="analyzing", message=f"Finding viral moments ({resolve_provider(provider)})…")
        scope = t
        rs, re_ = cfg.get("range_start"), cfg.get("range_end")
        if rs is not None or re_ is not None:
            lo, hi = rs or 0, re_ or t.duration
            scope = Transcript(t.language, t.duration,
                               [Segment(s.start, s.end, s.text, s.words) for s in t.segments
                                if s.start >= lo and s.end <= hi])
        clips = find_highlights(scope, cfg.get("num_clips", 8), cfg.get("min_len", 20), cfg.get("max_len", 60),
                                provider, settings.get("model"), cfg.get("prompt"))
        _check(pid)
        for c in db.list_clips(pid):  # retry: start fresh
            db.delete_clip(c["id"])
        rows = []
        for i, c in enumerate(clips, 1):
            rows.append(db.add_clip(
                pid, i, start=c.start, end=c.end, title=c.title, headline=c.headline,
                topic=c.topic, score=c.score, scores=c.scores, hashtags=c.hashtags, caption=c.caption,
                reason=c.reason, transcript=t.text_between(c.start, c.end), render={}, status="pending"))
        db.update_project(pid, progress=0.6)

        # 4. Render -------------------------------------------------------
        project = db.get_project(pid)
        for i, row in enumerate(rows, 1):
            _check(pid)
            _set(pid, stage="rendering", message=f"Rendering clip {i} of {len(rows)}…",
                 progress=round(0.6 + 0.4 * (i - 1) / max(1, len(rows)), 3))
            try:
                _render_row(project, row, t)
            except Exception as e:  # one bad clip shouldn't fail the project
                log.warning("Clip %s failed: %s", row["id"], e)
        n_ok = sum(1 for c in db.list_clips(pid) if c["status"] == "ready")
        msg = f"{n_ok} clip{'s' if n_ok != 1 else ''} ready" if clips else "No suitable clips found – try a longer video or other settings"
        _set(pid, status="done", stage="done", progress=1.0, message=msg)
    except Cancelled:
        log.info("Project %s cancelled", pid)
    except Exception as e:
        log.error("Project %s failed:\n%s", pid, traceback.format_exc())
        _set(pid, status="failed", error=str(e)[:2000], message="Failed")


# ------------------------------------------------------------- render job
def _run_render(cid: str) -> None:
    c = db.get_clip(cid)
    if not c:
        return
    p = db.get_project(c["project_id"])
    if not p or not p.get("source_path"):
        db.update_clip(cid, status="failed", error="Source video missing")
        return
    apply_settings()
    try:
        _render_row(p, c, _load_transcript(p["id"]))
    except Exception as e:
        log.warning("Render of clip %s failed: %s", cid, e)
