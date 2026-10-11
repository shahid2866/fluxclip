"""Find the most "viral" moments in a transcript.

Uses an LLM (Claude / OpenAI / Ollama) when available, otherwise an offline
heuristic scorer. Clip boundaries are always snapped to sentence boundaries so
clips never start or end mid-word.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from . import llm
from .transcribe import Transcript
from .utils import log

SYSTEM_PROMPT = """You are a world-class short-form video editor (TikTok, Reels, YouTube Shorts).
Given a timestamped transcript of a long video, you pick the moments most likely to go viral as
stand-alone vertical clips.

A great clip:
- Opens with a strong HOOK in the first 3 seconds (bold claim, question, surprising fact, conflict, emotion).
- Is self-contained: a viewer with zero context understands it.
- Has a payoff: an insight, punchline, story resolution, or actionable tip.
- Starts at the beginning of a sentence and ends at the end of a thought.
- Avoids intros, outros, sponsor reads, and "like and subscribe".

Respond with ONLY valid JSON, no prose, in this exact shape:
{"summary": "one sentence describing what this part of the video covers",
"clips": [{"start": 12.3, "end": 48.9,
"title": "Title Case YouTube-Shorts title, specific and curiosity-driven (max 60 chars)",
"headline": "on-screen hook shown for the first 5 seconds, 4-9 words, sentence case",
"topic": "2-4 word theme used to group related clips",
"hook": "the opening line that grabs attention", "reason": "why this will perform",
"score": 87, "hashtags": ["#tag1", "#tag2", "#tag3"],
"caption": "a 1-2 sentence social media caption for posting"}]}

Good titles use concrete numbers, names and outcomes, e.g. "AI Dog Portrait Business Makes $300K a Month".
Good headlines read like a bold claim, e.g. "A dog-art app became a $300K-a-month business".
"score" is 0-100 virality. Use the transcript timestamps (seconds) for start/end."""


@dataclass
class Clip:
    start: float
    end: float
    title: str = ""
    headline: str = ""
    topic: str = ""
    hook: str = ""
    reason: str = ""
    score: float = 0.0
    hashtags: list[str] = field(default_factory=list)
    caption: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 2)
        return d


# --------------------------------------------------------------------------- #
# Boundary handling
# --------------------------------------------------------------------------- #
def snap_clip(clip: Clip, t: Transcript, min_len: float, max_len: float) -> Clip | None:
    """Snap start/end to segment boundaries and enforce duration limits."""
    segs = t.segments
    if not segs:
        return None
    starts = [s.start for s in segs]
    ends = [s.end for s in segs]

    # Start: nearest segment start to the requested start.
    si = min(range(len(segs)), key=lambda i: abs(starts[i] - clip.start))
    start = starts[si]
    # End: nearest segment end at/after the start.
    candidates = [i for i in range(si, len(segs))]
    ei = min(candidates, key=lambda i: abs(ends[i] - clip.end))

    # Enforce max length by dropping trailing segments.
    while ei > si and ends[ei] - start > max_len:
        ei -= 1
    # Enforce min length by adding segments.
    while ends[ei] - start < min_len and ei + 1 < len(segs):
        if ends[ei + 1] - start > max_len:
            break
        ei += 1

    end = ends[ei]
    # A single very long segment: hard-cut at a word boundary.
    if end - start > max_len:
        words = [w for w in t.words_between(start, start + max_len) if w.end <= start + max_len]
        end = words[-1].end if words else start + max_len
    if end - start < min_len * 0.6:
        return None
    clip.start = round(max(0.0, start - 0.05), 2)
    clip.end = round(min(t.duration or end + 0.3, end + 0.3), 2)
    return clip


def _overlap(a: Clip, b: Clip) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / max(1e-6, min(a.duration, b.duration))


def dedupe(clips: list[Clip], max_overlap: float = 0.3) -> list[Clip]:
    kept: list[Clip] = []
    for c in sorted(clips, key=lambda c: c.score, reverse=True):
        if all(_overlap(c, k) <= max_overlap for k in kept):
            kept.append(c)
    return kept


# --------------------------------------------------------------------------- #
# LLM picker
# --------------------------------------------------------------------------- #
def _chunks(t: Transcript, window: float = 1500.0, overlap: float = 90.0):
    """Split long transcripts into ~25-minute windows so they fit any context."""
    if not t.segments:
        return
    start = t.segments[0].start
    last = t.segments[-1].end
    while start < last:
        end = start + window
        segs = [s for s in t.segments if s.start >= start and s.start < end]
        if segs:
            yield Transcript(t.language, t.duration, segs)
        start = end - overlap


def _llm_clips(t: Transcript, n: int, min_len: float, max_len: float,
               provider: str, model: str | None, instructions: str | None) -> list[Clip]:
    out: list[Clip] = []
    for chunk in _chunks(t):
        user = (
            f"Find the {n} best clips, each between {min_len:.0f} and {max_len:.0f} seconds long.\n"
            + (f"Extra instructions from the creator: {instructions}\n" if instructions else "")
            + f"Transcript language: {t.language}. Write titles/captions in that language.\n\n"
            + "TRANSCRIPT:\n" + chunk.to_prompt_text()
        )
        reply = llm.complete(SYSTEM_PROMPT, user, provider=provider, model=model)
        data = llm.extract_json(reply)
        items = data.get("clips", []) if isinstance(data, dict) else data
        for it in items or []:
            try:
                out.append(Clip(
                    start=float(it["start"]), end=float(it["end"]),
                    title=str(it.get("title", "")).strip(),
                    headline=str(it.get("headline", "")).strip(),
                    topic=str(it.get("topic", "")).strip(),
                    hook=str(it.get("hook", "")).strip(),
                    reason=str(it.get("reason", "")).strip(),
                    score=float(it.get("score", 50)),
                    hashtags=[str(h) for h in it.get("hashtags", [])][:8],
                    caption=str(it.get("caption", "")).strip(),
                ))
            except (KeyError, TypeError, ValueError):
                continue
    return out


# --------------------------------------------------------------------------- #
# Heuristic picker (offline, no API key)
# --------------------------------------------------------------------------- #
HOOK_WORDS = {
    "secret", "mistake", "never", "always", "truth", "why", "how", "best", "worst",
    "stop", "nobody", "everyone", "actually", "crazy", "insane", "money", "million",
    "biggest", "simple", "problem", "wrong", "important", "realized", "learned",
    "first", "only", "most", "hack", "trick", "easy", "fast", "free", "dangerous",
    "shocking", "surprising", "love", "hate", "fail", "failed", "success", "rich",
}
FILLER = {"um", "uh", "like", "you know", "so", "basically"}


def _score_text(text: str, duration: float, first_sentence: str) -> float:
    words = re.findall(r"[a-zA-Z']+|\d+", text.lower())
    if not words:
        return 0.0
    hooks = sum(1 for w in words if w in HOOK_WORDS)
    numbers = sum(1 for w in words if w.isdigit())
    you = sum(1 for w in words if w in ("you", "your", "you're"))
    filler = sum(1 for w in words if w in FILLER)
    wps = len(words) / max(duration, 1)  # speech density
    hook_open = first_sentence.strip().endswith("?") or any(
        w in HOOK_WORDS for w in re.findall(r"[a-z']+", first_sentence.lower())[:8]
    )
    score = (
        25 * min(1.0, hooks / 6)
        + 15 * min(1.0, numbers / 3)
        + 15 * min(1.0, you / 6)
        + 20 * min(1.0, wps / 3.0)
        + 15 * (1.0 if hook_open else 0.0)
        + 10 * (text.count("?") + text.count("!") > 0)
        - 10 * min(1.0, filler / max(len(words) / 20, 1))
    )
    return max(0.0, min(100.0, score))


def _heuristic_clips(t: Transcript, n: int, min_len: float, max_len: float) -> list[Clip]:
    segs = t.segments
    target = (min_len + max_len) / 2
    cands: list[Clip] = []
    for i, s in enumerate(segs):
        j = i
        while j + 1 < len(segs) and segs[j].end - s.start < target:
            j += 1
        dur = segs[j].end - s.start
        if dur < min_len * 0.6:
            continue
        text = " ".join(x.text.strip() for x in segs[i:j + 1])
        sc = _score_text(text, dur, s.text)
        first = s.text.strip()
        cands.append(Clip(
            start=s.start, end=segs[j].end,
            title=(first[:57] + "…") if len(first) > 60 else first,
            headline=" ".join(first.split()[:9]),
            hook=first, reason="Selected by offline heuristic (hook words, pacing, questions).",
            score=round(sc, 1), hashtags=["#shorts", "#viral", "#podcast"],
            caption=text[:140],
        ))
    return dedupe(cands)[: n * 2]


# --------------------------------------------------------------------------- #
def find_highlights(
    t: Transcript,
    num_clips: int = 5,
    min_len: float = 20.0,
    max_len: float = 60.0,
    provider: str = "auto",
    model: str | None = None,
    instructions: str | None = None,
) -> list[Clip]:
    """Return up to ``num_clips`` clips sorted by score (best first)."""
    if not t.segments:
        return []
    provider = llm.resolve_provider(provider)
    if provider == "heuristic":
        log.info("No LLM configured – using the offline heuristic picker.")
        raw = _heuristic_clips(t, num_clips, min_len, max_len)
    else:
        raw = _llm_clips(t, num_clips, min_len, max_len, provider, model, instructions)
    snapped = [c for c in (snap_clip(c, t, min_len, max_len) for c in raw) if c]
    clips = dedupe(snapped)[:num_clips]
    for c in clips:
        if not c.title:
            c.title = t.text_between(c.start, c.start + 6)[:60]
        if not c.headline:
            c.headline = c.title
        if not math.isfinite(c.score):
            c.score = 0
    return clips
