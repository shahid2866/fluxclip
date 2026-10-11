"""MCP server so Claude (Desktop / Code), Cursor, or any MCP client can make clips.

Two ways for the AI to work:
  1. "AI-native": call ``get_transcript`` -> the assistant itself picks the best
     moments -> ``render_clips``. No extra API key needed – the assistant IS the editor.
  2. "One shot": call ``process_video`` and let FluxClip's own provider pick clips.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

try:  # MCP Python SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK v1
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

from .captions import THEMES
from .highlights import find_highlights
from .pipeline import PipelineConfig, process_video as _process
from .render import RenderOptions, make_thumbnail, render_clip as _render
from .transcribe import transcribe
from .utils import resolve_input, slugify

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")

mcp = _Server(
    "fluxclip",
    instructions=(
        "FluxClip turns long videos into short vertical clips with animated captions. "
        "Preferred workflow: get_transcript -> choose the strongest self-contained moments "
        "(hook in first 3s, clear payoff, 20-60s) -> render_clips with exact start/end seconds "
        "taken from the transcript. Paths are local to the machine running this server."
    ),
)


def _opts(aspect: str, layout: str, caption_style: str, title_overlay: bool,
          font: str = "Poppins", max_height: int | None = None) -> RenderOptions:
    return RenderOptions(aspect=aspect, layout=layout, caption_style=caption_style,
                         title_overlay=title_overlay, font=font, max_height=max_height)


@mcp.tool()
def get_transcript(source: str, whisper_model: str = "small", language: str | None = None) -> dict[str, Any]:
    """Transcribe a local video file or URL. Returns a timestamped transcript
    ("[start-end] text", seconds) you can use to choose clip boundaries.
    Results are cached, so calling render tools afterwards is fast."""
    video = resolve_input(source)
    t = transcribe(video, whisper_model, language)
    return {
        "video_path": str(video),
        "language": t.language,
        "duration_seconds": round(t.duration, 1),
        "transcript": t.to_prompt_text(),
    }


@mcp.tool()
def find_clips(source: str, num_clips: int = 5, min_seconds: float = 20, max_seconds: float = 60,
               provider: str = "heuristic", instructions: str | None = None,
               whisper_model: str = "small") -> list[dict[str, Any]]:
    """Suggest clip candidates using FluxClip's built-in picker.
    provider: heuristic (offline) | anthropic | openai | ollama | auto."""
    video = resolve_input(source)
    t = transcribe(video, whisper_model)
    clips = find_highlights(t, num_clips, min_seconds, max_seconds, provider, None, instructions)
    return [{**c.to_dict(), "text": t.text_between(c.start, c.end)} for c in clips]


@mcp.tool()
def render_clips(source: str, clips: list[dict[str, Any]], output_dir: str = "fluxclip_output",
                 aspect: str = "9:16", layout: str = "auto", caption_style: str = "bold",
                 title_overlay: bool = False, whisper_model: str = "small") -> list[dict[str, Any]]:
    """Render several clips. Each item in `clips` needs "start" and "end" (seconds)
    and may include "title". layout: auto | crop (follow speaker) | fit (blurred bg).
    caption_style: bold | neon | fire | minimal | boxed | none. aspect: 9:16 | 1:1 | 4:5 | 16:9."""
    video = resolve_input(source)
    t = transcribe(video, whisper_model) if caption_style != "none" else None
    out = Path(output_dir).expanduser().resolve()
    opts = _opts(aspect, layout, caption_style, title_overlay)
    results = []
    for i, c in enumerate(clips, 1):
        title = str(c.get("title") or f"clip {i}")
        path = out / f"{i:02d}_{slugify(title)}.mp4"
        meta = _render(video, float(c["start"]), float(c["end"]), path, t, opts, title=title)
        meta["thumbnail"] = str(make_thumbnail(path))
        meta["title"] = title
        results.append(meta)
    return results


@mcp.tool()
def render_clip(source: str, start: float, end: float, title: str | None = None,
                output_dir: str = "fluxclip_output", aspect: str = "9:16", layout: str = "auto",
                caption_style: str = "bold", title_overlay: bool = False) -> dict[str, Any]:
    """Render a single clip between start and end (seconds)."""
    return render_clips(source, [{"start": start, "end": end, "title": title}], output_dir,
                        aspect, layout, caption_style, title_overlay)[0]


@mcp.tool()
def process_video(source: str, num_clips: int = 5, min_seconds: float = 20, max_seconds: float = 60,
                  provider: str = "auto", instructions: str | None = None,
                  output_dir: str = "fluxclip_output", aspect: str = "9:16", layout: str = "auto",
                  caption_style: str = "bold", whisper_model: str = "small") -> dict[str, Any]:
    """One-shot pipeline: transcribe, pick the best clips, render them with captions."""
    cfg = PipelineConfig(num_clips=num_clips, min_len=min_seconds, max_len=max_seconds,
                         provider=provider, instructions=instructions, whisper_model=whisper_model,
                         render=_opts(aspect, layout, caption_style, False))
    return _process(source, output_dir, cfg)


@mcp.tool()
def list_caption_styles() -> list[str]:
    """Available caption styles."""
    return [*THEMES, "none"]


@mcp.prompt()
def make_shorts(video: str, count: int = 5, focus: str = "") -> str:
    """Turn a long video into viral shorts, with the assistant acting as the editor."""
    return (
        f"Make {count} viral vertical shorts from: {video}\n"
        f"{'Focus on: ' + focus if focus else ''}\n"
        "1. Call get_transcript.\n"
        "2. Pick moments 20-60s long that open with a strong hook, are self-contained and end on a payoff. "
        "Start/end on sentence boundaries using the transcript timestamps.\n"
        "3. Call render_clips with start, end and a punchy title for each.\n"
        "4. Report each file path with a suggested caption and 3-5 hashtags."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
