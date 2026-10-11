"""Static results page (index.html) next to the rendered clips: preview, transcript,
score, timestamps, captions and one-click copy – similar to a clipping dashboard."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .utils import fmt_ts

_CSS = """
:root{--bg:#0f0f10;--card:#18181b;--line:#27272a;--text:#f4f4f5;--mute:#a1a1aa;--accent:#3cff22;--chip:#232327}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:28px 24px 8px;max-width:1100px;margin:auto}h1{font-size:22px;margin:0 0 4px}
.meta{color:var(--mute);font-size:13px}main{max-width:1100px;margin:auto;padding:8px 24px 60px}
h2{font-size:15px;color:var(--mute);font-weight:600;margin:28px 0 12px}
.card{display:grid;grid-template-columns:240px 1fr 180px;gap:20px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px}
video{width:240px;aspect-ratio:9/16;border-radius:10px;background:#000;object-fit:cover}
.title{font-weight:700;font-size:17px;margin:0 0 6px}.ts{color:var(--mute);font-size:13px;margin-bottom:8px}
.score{display:inline-block;font-weight:800;color:#000;background:var(--accent);border-radius:8px;padding:2px 8px;font-size:13px;margin-right:8px}
.tx{color:#d4d4d8;font-size:14px;max-height:260px;overflow:auto;padding-right:6px}
.why{color:var(--mute);font-size:13px;margin-top:8px}.tags{margin-top:8px;color:#7dd3fc;font-size:13px}
.actions{display:flex;flex-direction:column;gap:8px}
.btn{display:block;text-align:center;background:var(--chip);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 10px;text-decoration:none;cursor:pointer;font:inherit;font-size:14px}
.btn:hover{border-color:#52525b}.btn.primary{background:var(--text);color:#000;font-weight:700}
@media(max-width:820px){.card{grid-template-columns:1fr}video{width:100%;max-width:320px}}
"""

_JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>{
  navigator.clipboard.writeText(b.dataset.copy).then(()=>{const t=b.textContent;b.textContent='Copied!';setTimeout(()=>b.textContent=t,1200)})}));
"""


def _card(c: dict, out_dir: Path) -> str:
    e = html.escape
    rel = Path(c["path"]).name
    thumb = Path(c.get("thumbnail", "")).name if c.get("thumbnail") else ""
    post = (c.get("caption") or c.get("title", "")) + "\n\n" + " ".join(c.get("hashtags", []))
    srt = Path(rel).with_suffix(".srt").name
    return f"""
<div class="card">
  <video src="{e(rel)}" controls preload="metadata" {f'poster="{e(thumb)}"' if thumb else ''}></video>
  <div>
    <p class="title">{e(c.get('title', ''))}</p>
    <div class="ts"><span class="score">{c.get('score', 0):.0f}</span>
      [{fmt_ts(c['start'])} – {fmt_ts(c['end'])}] · {c['duration']:.0f}s · {e(c.get('layout', ''))}</div>
    <div class="tx">{e(c.get('transcript', ''))}</div>
    {f'<div class="why">💡 {e(c["reason"])}</div>' if c.get('reason') else ''}
    <div class="tags">{e(' '.join(c.get('hashtags', [])))}</div>
  </div>
  <div class="actions">
    <a class="btn primary" href="{e(rel)}" download>Download</a>
    <a class="btn" href="{e(srt)}" download>Subtitles (.srt)</a>
    <button class="btn" data-copy="{e(post)}">Copy caption</button>
    <button class="btn" data-copy="{e(c.get('title', ''))}">Copy title</button>
  </div>
</div>"""


def write_gallery(summary: dict, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    clips = summary.get("clips", [])
    groups: dict[str, list[dict]] = {}
    for c in clips:
        groups.setdefault(c.get("topic") or "Top clips", []).append(c)
    body = "".join(
        f"<h2>{html.escape(topic)} ({len(items)})</h2>" + "".join(_card(c, out_dir) for c in items)
        for topic, items in groups.items()
    )
    src = html.escape(Path(summary.get("source", "")).name)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FluxClip – {src}</title>
<style>{_CSS}</style></head><body>
<header><h1>{src}</h1><div class="meta">{len(clips)} clips · source {summary.get('video_duration', 0):.0f}s ·
language {html.escape(str(summary.get('language', '')))} · made with FluxClip</div></header>
<main>{body or '<p>No clips found.</p>'}</main>
<script>{_JS}</script>
<script type="application/json" id="data">{html.escape(json.dumps(summary))}</script>
</body></html>"""
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
