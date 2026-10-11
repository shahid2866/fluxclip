"""End-to-end: long video -> N captioned vertical clips + metadata."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .highlights import Clip, find_highlights
from .render import RenderOptions, make_thumbnail, render_clip
from .transcribe import Transcript, transcribe
from .utils import log, resolve_input, slugify


@dataclass
class PipelineConfig:
    num_clips: int = 5
    min_len: float = 20.0
    max_len: float = 60.0
    provider: str = "auto"
    model: str | None = None
    instructions: str | None = None
    whisper_model: str = "small"
    transcriber: str = "local"
    language: str | None = None
    render: RenderOptions = field(default_factory=RenderOptions)
    thumbnails: bool = True


def process_video(
    source: str,
    output_dir: str | Path = "clips",
    config: PipelineConfig | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    cfg = config or PipelineConfig()
    say = on_progress or (lambda m: log.info(m))
    t0 = time.time()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    say(f"Loading {source}")
    video = resolve_input(source)

    say("Transcribing (word-level timestamps)…")
    transcript: Transcript = transcribe(video, cfg.whisper_model, cfg.language, cfg.transcriber)
    transcript.save(out / "transcript.json")
    (out / "transcript.txt").write_text(transcript.to_readable(), encoding="utf-8")

    say("Finding the most viral moments…")
    clips: list[Clip] = find_highlights(
        transcript, cfg.num_clips, cfg.min_len, cfg.max_len,
        cfg.provider, cfg.model, cfg.instructions,
    )
    if not clips:
        say("No suitable clips found.")

    results = []
    for i, c in enumerate(clips, 1):
        name = f"{i:02d}_{slugify(c.title)}.mp4"
        say(f"Rendering clip {i}/{len(clips)}: {c.title} ({c.duration:.0f}s, score {c.score:.0f})")
        meta = render_clip(video, c.start, c.end, out / name, transcript, cfg.render, title=c.title)
        if cfg.thumbnails:
            meta["thumbnail"] = str(make_thumbnail(meta["path"], at=min(1.0, c.duration / 2)))
        meta.update({k: v for k, v in c.to_dict().items() if k not in meta})
        meta["transcript"] = transcript.text_between(c.start, c.end)
        results.append(meta)

    summary = {
        "source": str(video),
        "language": transcript.language,
        "video_duration": round(transcript.duration, 1),
        "elapsed_seconds": round(time.time() - t0, 1),
        "output_dir": str(out),
        "clips": results,
    }
    (out / "clips.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    say(f"Done – {len(results)} clips in {out}")
    return summary
