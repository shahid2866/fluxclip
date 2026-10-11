"""Command-line interface: ``fluxclip run video.mp4``"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__
from .captions import THEMES
from .highlights import find_highlights
from .llm import PROVIDERS
from .pipeline import PipelineConfig, process_video
from .render import ASPECTS, LAYOUTS, RenderOptions, render_clip
from .transcribe import transcribe
from .utils import FluxClipError, resolve_input


def _add_common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("transcription")
    g.add_argument("--whisper-model", default="small",
                   help="tiny | base | small | medium | large-v3 (default: small)")
    g.add_argument("--transcriber", default="local", choices=["local", "openai"])
    g.add_argument("--language", default=None, help="Force language code, e.g. en, hi, es")


def _add_ai(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("AI clip selection")
    g.add_argument("-n", "--num-clips", type=int, default=5)
    g.add_argument("--min", dest="min_len", type=float, default=20, help="Min clip seconds")
    g.add_argument("--max", dest="max_len", type=float, default=60, help="Max clip seconds")
    g.add_argument("--provider", default="auto", choices=PROVIDERS)
    g.add_argument("--model", default=None, help="LLM model name override")
    g.add_argument("--prompt", dest="instructions", default=None,
                   help='Extra guidance, e.g. "focus on money tips"')


def _add_render(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("rendering")
    g.add_argument("--aspect", default="9:16", choices=list(ASPECTS))
    g.add_argument("--layout", default="auto", choices=LAYOUTS)
    g.add_argument("--captions", default="opus", choices=[*THEMES, "none"])
    g.add_argument("--font", default="Poppins")
    g.add_argument("--words", type=int, default=3, help="Words per caption")
    g.add_argument("--caption-pos", type=float, default=0.78, help="Vertical position 0-1")
    g.add_argument("--no-headline", dest="headline", action="store_false",
                   help="Disable the white headline box shown for the first 5 s")
    g.add_argument("--headline-seconds", type=float, default=5.0)
    g.add_argument("--max-height", type=int, default=None, help="e.g. 1280 for faster renders")
    g.add_argument("--crf", type=int, default=20)


def _render_opts(a) -> RenderOptions:
    return RenderOptions(aspect=a.aspect, layout=a.layout, caption_style=a.captions, font=a.font,
                         words_per_caption=a.words, caption_position=a.caption_pos,
                         headline=a.headline, headline_seconds=a.headline_seconds, crf=a.crf, max_height=a.max_height)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fluxclip",
        description="Open-source AI video clipper: turn long videos into viral vertical shorts.",
    )
    ap.add_argument("--version", action="version", version=f"fluxclip {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="Full pipeline: transcribe -> pick clips -> render")
    p.add_argument("source", help="Video file or URL (YouTube, etc.)")
    p.add_argument("-o", "--out", default="clips", help="Output folder")
    _add_common(p); _add_ai(p); _add_render(p)

    p = sub.add_parser("transcribe", help="Transcribe only (JSON with word timings)")
    p.add_argument("source")
    p.add_argument("-o", "--out", default=None, help="Write JSON here (default: stdout)")
    p.add_argument("--text", action="store_true", help="Print readable text instead of JSON")
    _add_common(p)

    p = sub.add_parser("highlights", help="Find clip candidates and print JSON (no rendering)")
    p.add_argument("source")
    _add_common(p); _add_ai(p)

    p = sub.add_parser("render", help="Render one clip from given timestamps")
    p.add_argument("source")
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("-o", "--out", default="clip.mp4")
    p.add_argument("--title", default=None, help="Headline text shown on the clip")
    _add_common(p); _add_render(p)

    sub.add_parser("mcp", help="Start the MCP server (for Claude Desktop, Claude Code, Cursor…)")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(message)s", stream=sys.stderr)

    try:
        if a.cmd == "mcp":
            from .mcp_server import main as mcp_main
            mcp_main()
            return 0

        if a.cmd == "run":
            cfg = PipelineConfig(
                num_clips=a.num_clips, min_len=a.min_len, max_len=a.max_len, provider=a.provider,
                model=a.model, instructions=a.instructions, whisper_model=a.whisper_model,
                transcriber=a.transcriber, language=a.language, render=_render_opts(a),
            )
            res = process_video(a.source, a.out, cfg, on_progress=lambda m: print("▸ " + m, file=sys.stderr))
            for c in res["clips"]:
                print(f"  [{c['score']:>3.0f}] {c['duration']:>5.1f}s  {c['title']}\n        {c['path']}")
            return 0

        video = resolve_input(a.source)
        t = transcribe(video, a.whisper_model, a.language, a.transcriber)

        if a.cmd == "transcribe":
            data = t.to_readable() if a.text else json.dumps(t.to_dict(), ensure_ascii=False, indent=1)
            if a.out:
                open(a.out, "w", encoding="utf-8").write(data)
            else:
                print(data)
        elif a.cmd == "highlights":
            clips = find_highlights(t, a.num_clips, a.min_len, a.max_len, a.provider, a.model, a.instructions)
            print(json.dumps([c.to_dict() for c in clips], indent=2, ensure_ascii=False))
        elif a.cmd == "render":
            meta = render_clip(video, a.start, a.end, a.out, t, _render_opts(a), title=a.title)
            print(json.dumps(meta, indent=2))
        return 0
    except FluxClipError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
