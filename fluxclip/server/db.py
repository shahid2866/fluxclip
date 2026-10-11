"""SQLite storage for FluxClip Studio (projects, clips, settings).

Everything lives under one data folder (FLUXCLIP_DATA, default ~/.fluxclip-studio):
  studio.db                 – this database
  projects/<id>/source.*    – the uploaded / downloaded video
  projects/<id>/clips/*     – rendered clips, thumbnails, subtitles
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("FLUXCLIP_DATA", Path.home() / ".fluxclip-studio")).expanduser()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  source_path TEXT,
  status TEXT NOT NULL DEFAULT 'queued',     -- queued | processing | done | failed
  stage TEXT NOT NULL DEFAULT 'queued',      -- queued | downloading | transcribing | analyzing | rendering | done
  progress REAL NOT NULL DEFAULT 0,          -- 0..1 overall
  message TEXT NOT NULL DEFAULT '',
  error TEXT,
  settings TEXT NOT NULL DEFAULT '{}',
  duration REAL,
  language TEXT,
  thumbnail TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  start REAL NOT NULL,
  end REAL NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  headline TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL DEFAULT 0,
  scores TEXT NOT NULL DEFAULT '{}',
  hashtags TEXT NOT NULL DEFAULT '[]',
  caption TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  transcript TEXT NOT NULL DEFAULT '',
  render TEXT NOT NULL DEFAULT '{}',          -- per-clip render options (style, layout, aspect…)
  status TEXT NOT NULL DEFAULT 'pending',     -- pending | rendering | ready | failed
  error TEXT,
  file TEXT,
  thumbnail TEXT,
  layout TEXT,
  version INTEGER NOT NULL DEFAULT 0,
  liked INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_project ON clips(project_id, idx);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

JSON_FIELDS = {"settings", "scores", "hashtags", "render"}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def project_dir(project_id: str) -> Path:
    p = data_dir() / "projects" / project_id
    (p / "clips").mkdir(parents=True, exist_ok=True)
    return p


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(data_dir() / "studio.db", check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.executescript(SCHEMA)
        return _conn


def reset_for_tests(path: Path) -> None:
    """Point the module at a fresh data folder (used by tests)."""
    global _conn, DATA_DIR
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        DATA_DIR = Path(path)


@contextmanager
def tx():
    with _lock:
        c = conn()
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS & d.keys():
        try:
            d[k] = json.loads(d[k] or "null")
        except json.JSONDecodeError:
            d[k] = None
    if "liked" in d:
        d["liked"] = bool(d["liked"])
    return d


def _dump(fields: dict) -> dict:
    return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v) for k, v in fields.items()}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ----------------------------------------------------------------- projects
def create_project(source: str, settings: dict, title: str = "", source_path: str | None = None) -> dict:
    pid = new_id()
    now = time.time()
    with tx() as c:
        c.execute(
            "INSERT INTO projects (id, title, source, source_path, settings, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, title, source, source_path, json.dumps(settings), now, now),
        )
    project_dir(pid)
    return get_project(pid)


def get_project(pid: str) -> dict | None:
    with _lock:
        return _row(conn().execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone())


def list_projects() -> list[dict]:
    with _lock:
        rows = conn().execute(
            "SELECT p.*, (SELECT COUNT(*) FROM clips c WHERE c.project_id = p.id) AS clip_count "
            "FROM projects p ORDER BY created_at DESC"
        ).fetchall()
    return [_row(r) for r in rows]


def update_project(pid: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    f = _dump(fields)
    cols = ", ".join(f"{k} = ?" for k in f)
    with tx() as c:
        c.execute(f"UPDATE projects SET {cols} WHERE id = ?", (*f.values(), pid))


def delete_project(pid: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM clips WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM projects WHERE id = ?", (pid,))


# -------------------------------------------------------------------- clips
CLIP_COLUMNS = ("start", "end", "title", "headline", "topic", "score", "scores", "hashtags", "caption",
                "reason", "transcript", "render", "status", "error", "file", "thumbnail", "layout",
                "version", "liked")


def add_clip(project_id: str, idx: int, **fields) -> dict:
    cid = new_id()
    now = time.time()
    f = _dump({k: v for k, v in fields.items() if k in CLIP_COLUMNS})
    cols = ["id", "project_id", "idx", "created_at", "updated_at", *f.keys()]
    vals = [cid, project_id, idx, now, now, *f.values()]
    with tx() as c:
        c.execute(f"INSERT INTO clips ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    return get_clip(cid)


def get_clip(cid: str) -> dict | None:
    with _lock:
        return _row(conn().execute("SELECT * FROM clips WHERE id = ?", (cid,)).fetchone())


def list_clips(project_id: str) -> list[dict]:
    with _lock:
        rows = conn().execute(
            "SELECT * FROM clips WHERE project_id = ? ORDER BY score DESC, idx", (project_id,)
        ).fetchall()
    return [_row(r) for r in rows]


def update_clip(cid: str, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in CLIP_COLUMNS}
    if not fields:
        return
    fields["updated_at"] = time.time()
    f = _dump(fields)
    cols = ", ".join(f"{k} = ?" for k in f)
    with tx() as c:
        c.execute(f"UPDATE clips SET {cols} WHERE id = ?", (*f.values(), cid))


def delete_clip(cid: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM clips WHERE id = ?", (cid,))


# ----------------------------------------------------------------- settings
def get_settings() -> dict:
    with _lock:
        rows = conn().execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def set_settings(values: dict) -> dict:
    with tx() as c:
        for k, v in values.items():
            if v is None:
                c.execute("DELETE FROM settings WHERE key = ?", (k,))
            else:
                c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
    return get_settings()
