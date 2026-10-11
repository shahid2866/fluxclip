"""Shared helpers: ffmpeg/ffprobe wrappers, downloads, caching, slugs."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("fluxclip")

CACHE_DIR = Path(os.environ.get("FLUXCLIP_CACHE", Path.home() / ".cache" / "fluxclip"))


class FluxClipError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FluxClipError(
            f"'{name}' was not found on PATH. Install FFmpeg (https://ffmpeg.org/download.html)."
        )
    return path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(map(str, cmd)))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FluxClipError(f"Command failed: {cmd[0]}\n{tail}")
    return proc


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def probe(path: str | Path) -> VideoInfo:
    require_binary("ffprobe")
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise FluxClipError(f"No video stream found in {path}")
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if not fps or fps != fps:  # 0 or NaN
        fps = 30.0
    width, height = int(video["width"]), int(video["height"])
    # Respect rotation metadata (phones record portrait as rotated landscape).
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"]))
    if rotation in (90, 270):
        width, height = height, width
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    return VideoInfo(str(path), width, height, fps, duration, has_audio)


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def resolve_input(source: str, workdir: str | Path | None = None, info_out: dict | None = None) -> Path:
    """Return a local video path, downloading URLs (YouTube, etc.) with yt-dlp."""
    if not is_url(source):
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise FluxClipError(f"File not found: {p}")
        return p
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise FluxClipError("Downloading URLs needs yt-dlp: pip install 'fluxclip[download]'") from e
    target = Path(workdir or CACHE_DIR / "downloads")
    target.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(target / "%(id)s.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    if info_out is not None:
        info_out.update({k: info.get(k) for k in ("title", "duration", "uploader", "id")})
    if not path.exists():  # format without merge
        matches = sorted(target.glob(f"{info['id']}.*"))
        if not matches:
            raise FluxClipError("Download finished but the file could not be located.")
        path = matches[0]
    return path


def file_fingerprint(path: str | Path) -> str:
    p = Path(path)
    st = p.stat()
    h = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "clip"


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return f"{h:d}:{m:02d}:{s:05.2f}" if h else f"{m:02d}:{s:05.2f}"
