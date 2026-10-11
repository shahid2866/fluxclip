# FluxClip ✂️

**Open-source AI video clipper.** Turn one long video (podcast, interview, YouTube video, webinar) into ready-to-post vertical shorts for TikTok, Reels and YouTube Shorts — with speaker-tracking reframing and animated word-by-word captions.

A free, self-hosted alternative to OpusClip-style tools. Use it from the command line, or let **Claude (or any MCP-compatible AI)** drive it for you.

```bash
fluxclip run "https://youtube.com/watch?v=..." -n 5
```

```
▸ Transcribing (word-level timestamps)…
▸ Finding the most viral moments…
▸ Rendering clip 1/5: The biggest mistake creators make (34s, score 92)
...
  [ 92]  34.1s  The biggest mistake creators make
        clips/01_the-biggest-mistake-creators-make.mp4
```

## Features

| | |
|---|---|
| 🎙️ **Transcription** | Local [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with word-level timestamps (free, offline, 90+ languages) or the OpenAI Whisper API |
| 🧠 **AI clip picker** | Finds hooks, stories and payoffs. Works with **Claude**, **OpenAI** (or any OpenAI-compatible API: Groq, OpenRouter, LM Studio), **Ollama** (local), or an offline heuristic — no key required |
| 🎯 **Speaker tracking** | Face detection + a "virtual camera" with dead-zone smoothing and hard cuts when the speaker changes |
| 🌫️ **Blurred-background layout** | Automatic fallback for screen recordings / slides / no faces |
| 💬 **Animated captions** | Uppercase word-by-word captions with the active word highlighted. Styles: `opus` (default, green highlight), `bold`, `neon`, `fire`, `minimal`, `boxed` |
| 📰 **Auto headline** | A white rounded headline box with a scroll-stopping hook for the first 5 seconds of every clip |
| 🗂️ **Results page** | `index.html` in the output folder: preview every clip with its score, timestamps, transcript, reason and one-click copy of title/caption |
| 🤖 **MCP server** | Plug into Claude Desktop, Claude Code, Cursor, etc. Claude reads the transcript, picks the moments, and renders them |
| 📦 **Ready to post** | MP4 (H.264/AAC), `.srt` subtitles, thumbnails, and `clips.json` with titles, hooks, captions and hashtags |
| 📐 **Any format** | `9:16`, `1:1`, `4:5`, `16:9` |

## Install

Requirements: **Python 3.10+** and **FFmpeg** (`brew install ffmpeg`, `sudo apt install ffmpeg`, or `winget install ffmpeg`).

```bash
pip install "fluxclip[all] @ git+https://github.com/OWNER/fluxclip"
```

Or from source:

```bash
git clone https://github.com/OWNER/fluxclip && cd fluxclip
pip install -e ".[all]"
```

Docker:

```bash
docker build -t fluxclip .
docker run --rm -v "$PWD:/work" -e ANTHROPIC_API_KEY fluxclip run /work/video.mp4 -o /work/clips
```

## Quick start

```bash
# Pick an AI (optional – without one, the offline heuristic is used)
export ANTHROPIC_API_KEY=sk-ant-...      # Claude
# or: export OPENAI_API_KEY=sk-...       # OpenAI / compatible (set OPENAI_BASE_URL for Groq, OpenRouter…)
# or: run Ollama locally                 # auto-detected at localhost:11434

fluxclip run podcast.mp4 -n 5 --min 20 --max 60
```

### Useful options

```bash
fluxclip run video.mp4 \
  -n 8 --min 15 --max 45 \
  --prompt "focus on actionable money tips" \  # steer the AI
  --captions neon --words 2 --no-headline \    # caption look
  --layout crop \                              # auto | crop | fit
  --aspect 9:16 \                              # 9:16 | 1:1 | 4:5 | 16:9
  --whisper-model medium --language hi \       # better accuracy / force language
  --provider anthropic --model claude-sonnet-4-5
```

Other commands:

```bash
fluxclip transcribe video.mp4 --text            # readable transcript
fluxclip highlights video.mp4 -n 5              # JSON clip suggestions, no rendering
fluxclip render video.mp4 --start 62.4 --end 101 --title "My hook"   # render exact timestamps + headline
fluxclip mcp                                    # start MCP server
```

## Use with Claude (MCP)

FluxClip ships an MCP server, so Claude itself becomes your video editor — **no extra API key needed**: Claude reads the transcript, chooses the moments, and calls the renderer.

**Claude Desktop** → `Settings → Developer → Edit config` (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fluxclip": {
      "command": "fluxclip-mcp"
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add fluxclip -- fluxclip-mcp
```

**Cursor / other clients:** run `fluxclip-mcp` as a stdio server.

Then just ask:

> Make 5 viral shorts from ~/Videos/podcast-ep12.mp4 focused on business advice, neon captions.

Tools exposed:

| Tool | What it does |
|---|---|
| `get_transcript` | Transcribe a file/URL → timestamped transcript |
| `find_clips` | Built-in clip suggestions (heuristic / any provider) |
| `render_clips` / `render_clip` | Render clips from exact start/end seconds |
| `process_video` | One-shot full pipeline |
| `list_caption_styles` | Caption style names |

There's also a `make_shorts` prompt that walks the assistant through the workflow.

## Output

```
clips/
├── index.html        # open in a browser to review, download and copy captions
├── 01_the-biggest-mistake-creators-make.mp4
├── 01_the-biggest-mistake-creators-make.srt
├── 01_the-biggest-mistake-creators-make.jpg
├── ...
├── clips.json        # titles, hooks, scores, captions, hashtags, timestamps
├── transcript.json   # full transcript with word timings
└── transcript.txt
```

## How it works

```
video ─► ffmpeg audio ─► Whisper (word timestamps) ─► LLM / heuristic picks moments
      ─► snap to sentence boundaries ─► face tracking + virtual camera ─► crop 9:16
      ─► ASS karaoke captions ─► ffmpeg (H.264) ─► clips + metadata
```

- **Reframing:** faces are detected every 0.2 s (YuNet if it can be downloaded, otherwise OpenCV Haar cascades). A median filter removes noise; a virtual camera with a dead-zone eases on small moves and hard-cuts (with look-ahead) when the speaker changes. If faces appear in fewer than 25% of samples, the clip uses the blurred-background layout.
- **Clip selection:** long transcripts are split into ~25-minute windows so any model's context is enough. Results are deduplicated and snapped to sentence boundaries.

## Configuration

| Env var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Use Claude for clip selection |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI or any compatible API |
| `OLLAMA_HOST` | Ollama URL (default `http://localhost:11434`) |
| `FLUXCLIP_MODEL` | Default model name for the chosen provider |
| `FLUXCLIP_DEVICE` | Whisper device: `auto`, `cpu`, `cuda` |
| `FLUXCLIP_CACHE` | Cache folder (transcripts, models, downloads) |
| `FLUXCLIP_FACE_DETECTOR=haar` | Skip the YuNet download |

## Roadmap

- [ ] Web UI (Next.js) for upload, preview and caption editing
- [ ] Split-screen layout for two speakers
- [ ] B-roll and emoji suggestions
- [ ] Filler-word and silence removal
- [ ] Direct publishing to YouTube / Instagram / TikTok

PRs welcome!

## Development

```bash
pip install -e ".[all,dev]"
pytest
```

## License

MIT — free for personal and commercial use. Respect the copyright of videos you clip.
