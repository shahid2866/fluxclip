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
from .utils import fmt_ts, log

SELECT_PROMPT = """You are a senior short-form video editor (TikTok, Reels, YouTube Shorts) who
finds the moments in long videos that will go viral as stand-alone vertical clips.

The transcript is split into numbered sentences: "S12 [25:14] text".
Pick clips as RANGES OF WHOLE SENTENCES (start_id..end_id, inclusive).

A great clip:
- Starts on a strong first sentence: bold claim, question, surprising number, conflict, emotion.
  Never start on filler ("so", "yeah", "and then", "like I said") or mid-story.
- Is self-contained: a stranger with zero context understands it (no unexplained "he", "that", "this").
- Delivers a payoff: insight, punchline, story resolution, contrarian take, or actionable tip.
- Ends right after the payoff, on a complete thought.
- Is not an intro, outro, sponsor read, or "like and subscribe".
- Stories with specific numbers, names and outcomes beat generic advice.

Respond with ONLY JSON:
{"clips": [{"start_id": 12, "end_id": 19, "topic": "2-4 word theme", "why": "one line"}]}"""

RANK_PROMPT = """You are the head editor reviewing candidate clips for TikTok/Reels/Shorts.
Score each candidate honestly (most candidates are NOT great):
- hook (0-25): do the first 3 seconds stop the scroll?
- flow (0-25): self-contained, coherent, no missing context, clean ending?
- value (0-25): insight, emotion, story payoff, or entertainment?
- trend (0-25): relevance to what people currently care about and share?

You may tighten a clip: set "start_id"/"end_id" to a narrower sentence range inside the candidate
if it removes a weak opening or a trailing tangent (it must stay within the length limits).

For each candidate also write:
- "title": Title Case, specific, curiosity-driven, max 60 chars (e.g. "AI Dog Portrait Business Makes $300K a Month")
- "headline": the on-screen hook for the first 5 s, 4-9 words, sentence case, a bold claim
  (e.g. "A dog-art app became a $300K-a-month business")
- "caption": 1-2 sentence post caption; "hashtags": 3-5 tags; "topic": 2-4 word theme

Respond with ONLY JSON:
{"ranked": [{"id": 0, "start_id": 12, "end_id": 18, "hook": 22, "flow": 20, "value": 21, "trend": 18,
"title": "...", "headline": "...", "caption": "...", "hashtags": ["#a"], "topic": "...",
"reason": "why it will perform"}]}"""

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
    scores: dict = field(default_factory=dict)  # hook / flow / value / trend

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
    """Snap start/end to sentence boundaries and enforce duration limits."""
    segs = t.sentences()
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
# LLM picker: sentence-range selection, then a ranking/tightening pass
# --------------------------------------------------------------------------- #
def _sentence_windows(sents, window: float = 1500.0, overlap: float = 120.0):
    """Yield (offset, sentences) windows of ~25 minutes so any model's context fits."""
    if not sents:
        return
    start = sents[0].start
    last = sents[-1].end
    while start < last:
        idx = [i for i, s in enumerate(sents) if start <= s.start < start + window]
        if idx:
            yield idx
        start += window - overlap


def _fit_range(sents, si: int, ei: int, min_len: float, max_len: float) -> tuple[int, int] | None:
    si, ei = max(0, si), min(len(sents) - 1, max(si, ei))
    while ei > si and sents[ei].end - sents[si].start > max_len:
        ei -= 1
    while sents[ei].end - sents[si].start < min_len and ei + 1 < len(sents):
        if sents[ei + 1].end - sents[si].start > max_len:
            break
        ei += 1
    if sents[ei].end - sents[si].start < min_len * 0.6:
        return None
    return si, ei


def _ids(it: dict, a: str, b: str) -> tuple[int, int] | None:
    try:
        return int(it[a]), int(it[b])
    except (KeyError, TypeError, ValueError):
        return None


def _llm_clips(t: Transcript, n: int, min_len: float, max_len: float,
               provider: str, model: str | None, instructions: str | None) -> list[Clip]:
    sents = t.sentences()
    extra = f"Creator's instructions: {instructions}\n" if instructions else ""

    # Stage 1 – candidates (over-generate, then rank).
    want = max(n * 2, 6)
    cands: list[tuple[int, int, str]] = []
    for idx in _sentence_windows(sents):
        lines = "\n".join(f"S{i} [{fmt_ts(sents[i].start)}] {sents[i].text}" for i in idx)
        user = (f"Find up to {want} clip candidates, each {min_len:.0f}-{max_len:.0f} seconds long.\n"
                f"{extra}TRANSCRIPT:\n{lines}")
        data = llm.extract_json(llm.complete(SELECT_PROMPT, user, provider=provider, model=model))
        items = data.get("clips", []) if isinstance(data, dict) else data
        for it in items or []:
            if not isinstance(it, dict):
                continue
            rng = _ids(it, "start_id", "end_id")
            if rng is None and "start" in it:  # model answered in seconds – snap it
                c = snap_clip(Clip(float(it["start"]), float(it.get("end", 0))), t, min_len, max_len)
                if c:
                    si = min(range(len(sents)), key=lambda i: abs(sents[i].start - c.start))
                    ei = min(range(len(sents)), key=lambda i: abs(sents[i].end - c.end))
                    rng = (si, ei)
            if rng:
                fitted = _fit_range(sents, *rng, min_len, max_len)
                if fitted:
                    cands.append((*fitted, str(it.get("topic", ""))))
    # Remove near-duplicates before ranking.
    uniq: list[tuple[int, int, str]] = []
    for c in cands:
        if all(min(c[1], u[1]) - max(c[0], u[0]) < 0.5 * (c[1] - c[0] + 1) for u in uniq):
            uniq.append(c)
    if not uniq:
        return []

    # Stage 2 – score, tighten and write titles/headlines.
    blocks = []
    for k, (si, ei, topic) in enumerate(uniq):
        dur = sents[ei].end - sents[si].start
        body = "\n".join(f"  S{i}: {sents[i].text}" for i in range(si, ei + 1))
        blocks.append(f"CANDIDATE id={k} (S{si}-S{ei}, {dur:.0f}s, topic: {topic or '-'})\n{body}")
    user = (f"Length limits: {min_len:.0f}-{max_len:.0f} seconds. Language: {t.language} "
            f"(write titles/captions in it).\n{extra}\n" + "\n\n".join(blocks))
    data = llm.extract_json(llm.complete(RANK_PROMPT, user, provider=provider, model=model, max_tokens=8000))
    ranked = data.get("ranked", []) if isinstance(data, dict) else data

    out: list[Clip] = []
    seen = set()
    for it in ranked or []:
        try:
            k = int(it["id"])
            base = uniq[k]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if k in seen:
            continue
        seen.add(k)
        rng = _ids(it, "start_id", "end_id") or base[:2]
        # Tightening may only narrow the candidate.
        si, ei = max(base[0], rng[0]), min(base[1], rng[1])
        fitted = _fit_range(sents, si, ei, min_len, max_len) or _fit_range(sents, base[0], base[1], min_len, max_len)
        if not fitted:
            continue
        si, ei = fitted
        sc = {key: max(0.0, min(25.0, float(it.get(key, 12)))) for key in ("hook", "flow", "value", "trend")}
        out.append(Clip(
            start=round(max(0.0, sents[si].start - 0.05), 2),
            end=round(min(t.duration or sents[ei].end + 0.3, sents[ei].end + 0.3), 2),
            title=str(it.get("title", "")).strip(),
            headline=str(it.get("headline", "")).strip(),
            topic=str(it.get("topic") or base[2]).strip(),
            hook=sents[si].text,
            reason=str(it.get("reason", "")).strip(),
            score=round(sum(sc.values()), 1),
            hashtags=[str(h) for h in it.get("hashtags", [])][:6],
            caption=str(it.get("caption", "")).strip(),
            scores=sc,
        ))
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


BAD_STARTS = ("and ", "so ", "but ", "yeah", "like ", "um", "uh", "because ", "or ", "then ", "okay", "right")


def _heuristic_clips(t: Transcript, n: int, min_len: float, max_len: float) -> list[Clip]:
    segs = t.sentences()
    target = (min_len + max_len) / 2
    cands: list[Clip] = []
    for i, s in enumerate(segs):
        if s.text.lower().startswith(BAD_STARTS):
            continue  # never open a clip on a connector/filler word
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
    if provider == "heuristic":
        snapped = [c for c in (snap_clip(c, t, min_len, max_len) for c in raw) if c]
    else:
        snapped = raw  # already on exact sentence boundaries
    snapped = [c for c in snapped if c.end - c.start >= 1.0]  # guard against out-of-range picks
    clips = dedupe(snapped)[:num_clips]
    for c in clips:
        if not c.title:
            c.title = t.text_between(c.start, c.start + 6)[:60]
        if not c.headline:
            c.headline = c.title
        if not math.isfinite(c.score):
            c.score = 0
    return clips
