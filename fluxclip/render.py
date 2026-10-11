"""Cut, reframe and caption a single clip."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import captions as cap_mod
from .headline import FONT_DIR, render_headline_png
from .reframe import compute_track, cv2
from .transcribe import Transcript
from .utils import FluxClipError, log, probe, require_binary, run

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
LAYOUTS = ("auto", "crop", "fit")


@dataclass
class RenderOptions:
    aspect: str = "9:16"
    layout: str = "auto"              # auto | crop (follow speaker) | fit (blurred background)
    caption_style: str = "opus"       # opus | bold | neon | fire | minimal | boxed | none
    font: str = "Poppins"             # bundled Poppins Bold is always available
    words_per_caption: int = 3
    caption_position: float = 0.78    # vertical centre of captions (0 top – 1 bottom)
    headline: bool = True             # white headline box over the first seconds
    headline_seconds: float = 5.0
    headline_position: float = 0.58
    crf: int = 20
    preset: str = "veryfast"
    max_height: int | None = None     # e.g. 1280 for faster, smaller renders


def _out_size(opts: RenderOptions) -> tuple[int, int]:
    if opts.aspect not in ASPECTS:
        raise FluxClipError(f"Unsupported aspect '{opts.aspect}'. Use one of {list(ASPECTS)}")
    w, h = ASPECTS[opts.aspect]
    if opts.max_height and h > opts.max_height:
        s = opts.max_height / h
        w, h = int(w * s) // 2 * 2, int(h * s) // 2 * 2
    return w, h


def _write_cropped(src: str, start: float, end: float, crop_w: int, src_h: int,
                   out_w: int, out_h: int, centers, n_frames: int, fps: float, dst: Path) -> None:
    cap = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_w, out_h))
    if not writer.isOpened():
        raise FluxClipError("OpenCV could not open a video writer.")
    last = None
    for i in range(n_frames):
        ok, frame = cap.read()
        if not ok:
            if last is None:
                break
            frame = last
        last = frame
        x0 = int(round(centers[min(i, len(centers) - 1)] - crop_w / 2))
        x0 = max(0, min(frame.shape[1] - crop_w, x0))
        crop = frame[0:src_h, x0:x0 + crop_w]
        writer.write(cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_AREA))
    writer.release()
    cap.release()


def render_clip(
    video: str | Path,
    start: float,
    end: float,
    output: str | Path,
    transcript: Transcript | None = None,
    opts: RenderOptions | None = None,
    title: str | None = None,
    headline: str | None = None,
) -> dict:
    """Render one vertical clip. Returns metadata about what was produced."""
    require_binary("ffmpeg")
    opts = opts or RenderOptions()
    video = str(Path(video).resolve())
    info = probe(video)
    start = max(0.0, float(start))
    end = min(float(end), info.duration or float(end))
    if end - start < 1:
        raise FluxClipError(f"Clip is too short ({end - start:.2f}s).")
    out_w, out_h = _out_size(opts)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    target_ratio = out_w / out_h
    src_ratio = info.width / info.height
    crop_w = int(round(info.height * target_ratio)) // 2 * 2
    layout = opts.layout
    if layout not in LAYOUTS:
        raise FluxClipError(f"Unknown layout '{layout}'. Use one of {LAYOUTS}")
    if src_ratio <= target_ratio + 0.01:
        layout = "fit"  # source already as narrow as target: just scale/pad

    with tempfile.TemporaryDirectory(prefix="fluxclip-") as td:
        tdp = Path(td)
        post: list[str] = []  # filters applied to the composed vertical frame
        if opts.caption_style != "none" and transcript is not None:
            ass = cap_mod.build_ass(
                transcript.words_between(start, end), start, end, out_w, out_h,
                theme=opts.caption_style, font=opts.font, max_words=opts.words_per_caption,
                position=opts.caption_position,
            )
            (tdp / "subs.ass").write_text(ass, encoding="utf-8")
            shutil.copytree(FONT_DIR, tdp / "fonts")
            post.append("ass=subs.ass:fontsdir=fonts")

        head_png = None
        head_text = (headline or title or "").strip()
        if opts.headline and head_text:
            head_png = render_headline_png(head_text, out_w, tdp / "headline.png")

        track = None
        if layout in ("auto", "crop"):
            if cv2 is None:
                raise FluxClipError("opencv-python is required for the crop layout.")
            track = compute_track(video, start, end, crop_w)
            if layout == "auto" and track.face_ratio < 0.25:
                log.info("Few faces found (%.0f%%) – using blurred-background layout.", track.face_ratio * 100)
                layout = "fit"
            else:
                layout = "crop"

        enc = ["-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
        dur = end - start

        if layout == "crop":
            raw = tdp / "crop.mp4"
            _write_cropped(video, start, end, crop_w, info.height, out_w, out_h,
                           track.centers, track.n_frames, track.fps, raw)
            inputs = ["-i", str(raw), "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", video]
            audio = ["-map", "1:a:0?"] if info.has_audio else []
            base = "[0:v]null[base]"
            next_input = 2
        else:
            inputs = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", video]
            audio = ["-map", "0:a:0?"] if info.has_audio else []
            base = (f"[0:v]split=2[a][b];"
                    f"[a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                    f"crop={out_w}:{out_h},boxblur=luma_radius=30:luma_power=2,eq=brightness=-0.08[bg];"
                    f"[b]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
            next_input = 1

        chain = [base]
        last = "base"
        if head_png:
            inputs += ["-i", str(head_png)]
            hs = min(opts.headline_seconds, dur)
            y = f"{opts.headline_position}*H-h/2"
            chain.append(f"[{last}][{next_input}:v]overlay=(W-w)/2:{y}:"
                         f"enable='between(t,0,{hs:.2f})'[hd]")
            last = "hd"
        chain.append(f"[{last}]{','.join(post) if post else 'null'}[v]")
        cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chain),
               "-map", "[v]", *audio, *enc, "-t", f"{dur:.3f}", "out.mp4"]

        proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FluxClipError("ffmpeg failed:\n" + "\n".join(proc.stderr.splitlines()[-12:]))
        shutil.move(str(tdp / "out.mp4"), output)

    if transcript is not None:
        output.with_suffix(".srt").write_text(
            cap_mod.build_srt(transcript.words_between(start, end), start, end), encoding="utf-8")

    return {
        "path": str(output), "start": round(start, 2), "end": round(end, 2),
        "duration": round(end - start, 2), "layout": layout, "size": f"{out_w}x{out_h}",
    }


def make_thumbnail(clip_path: str | Path, at: float = 1.0) -> Path:
    out = Path(clip_path).with_suffix(".jpg")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(clip_path),
         "-frames:v", "1", "-q:v", "3", str(out)])
    return out
