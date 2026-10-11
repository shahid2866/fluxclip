"""Animated word-by-word captions (the "Hormozi / OpusClip" style) as ASS subtitles."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transcribe import Word


@dataclass
class CaptionTheme:
    primary: str      # ASS colour &HAABBGGRR
    highlight: str
    outline: str
    outline_w: float
    shadow: float
    uppercase: bool
    size_ratio: float  # font size relative to video width
    border_style: int = 1  # 1 = outline, 3 = opaque box
    back: str = "&H80000000"
    pop: bool = True


THEMES: dict[str, CaptionTheme] = {
    # Default: uppercase white, active word bright green, thick outline + soft shadow.
    "opus": CaptionTheme("&H00FFFFFF", "&H0022FF3C", "&H00000000", 5, 3, True, 0.072,
                         back="&H90000000", pop=False),
    "bold": CaptionTheme("&H00FFFFFF", "&H0000E5FF", "&H00000000", 6, 2, True, 0.075),
    "neon": CaptionTheme("&H00FFFFFF", "&H0066FF33", "&H00000000", 6, 3, True, 0.075),
    "fire": CaptionTheme("&H00FFFFFF", "&H00245BFF", "&H00000000", 6, 2, True, 0.075),
    "minimal": CaptionTheme("&H00FFFFFF", "&H00FFFFFF", "&H00000000", 3, 1, False, 0.058, pop=False),
    "boxed": CaptionTheme("&H00FFFFFF", "&H0000E5FF", "&H00000000", 14, 0, False, 0.06,
                          border_style=3, back="&H99000000"),
}


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _display(word: str, uppercase: bool) -> str:
    """Caption text for one word: no trailing commas/periods (cleaner, like OpusClip)."""
    txt = _esc(word.strip())
    if len(txt) > 1:
        txt = txt.rstrip(".,;:")
    return txt.upper() if uppercase else txt


def group_words(words: list[Word], max_words: int = 4, max_chars: int = 22,
                max_gap: float = 0.6) -> list[list[Word]]:
    """Group words into caption chunks.

    1. Split into phrases at punctuation and pauses.
    2. Split each phrase into balanced chunks (7 words -> 4+3, never a lone orphan word
       when it can be avoided), respecting the character limit.
    """
    phrases: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        text = w.word.strip()
        if not text:
            continue
        if cur and w.start - cur[-1].end > max_gap:
            phrases.append(cur)
            cur = []
        cur.append(w)
        if text[-1] in ".?!,;:":
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)

    def chars(ws: list[Word]) -> int:
        return sum(len(x.word.strip()) for x in ws) + len(ws) - 1

    groups: list[list[Word]] = []
    for ph in phrases:
        n_chunks = max(-(-len(ph) // max_words), -(-chars(ph) // max_chars), 1)
        n_chunks = min(n_chunks, len(ph))
        base, extra = divmod(len(ph), n_chunks)
        i = 0
        for k in range(n_chunks):
            size = base + (1 if k < extra else 0)
            groups.append(ph[i:i + size])
            i += size
    # Merge a lone short word into its neighbour when the result still fits.
    merged: list[list[Word]] = []
    for g in groups:
        if (merged and len(g) == 1 and len(merged[-1]) < max_words
                and chars(merged[-1] + g) <= max_chars and g[0].start - merged[-1][-1].end < max_gap
                and merged[-1][-1].word.strip()[-1:] not in ".?!"):
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    return merged


def build_ass(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    width: int,
    height: int,
    theme: str = "bold",
    font: str = "Poppins",
    max_words: int = 3,
    position: float = 0.72,
    title: str | None = None,
    title_seconds: float = 3.0,
) -> str:
    """Return the ASS document for one clip. ``position`` = vertical centre as fraction of height."""
    th = THEMES.get(theme, THEMES["bold"])
    size = int(width * th.size_ratio)
    margin_v = int(height * (1 - position) - size / 2)
    title_size = int(width * 0.06)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},{th.primary},{th.highlight},{th.outline},{th.back},-1,0,0,0,100,100,0,0,{th.border_style},{th.outline_w},{th.shadow},2,60,60,{margin_v},1
Style: Title,{font},{title_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,{int(height * 0.12)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []
    if title:
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(min(title_seconds, clip_end - clip_start))},Title,,0,0,0,,"
            f"{{\\fad(150,250)}}{_esc(title)}"
        )

    rel = [Word(max(0.0, w.start - clip_start), min(clip_end, w.end) - clip_start, w.word)
           for w in words if w.end > clip_start and w.start < clip_end]
    groups = group_words(rel, max_words=max_words, max_chars=22)
    for gi, g in enumerate(groups):
        # Two balanced lines when the group is long (e.g. "EVERYONE IS / FREAKING OUT").
        texts = [_display(x.word, th.uppercase) for x in g]
        total = sum(len(x) for x in texts) + len(texts) - 1
        brk = -1
        if len(g) >= 3 and total > 15:
            best = None
            for k in range(1, len(g)):
                left = sum(len(x) for x in texts[:k]) + k - 1
                diff = abs(left - (total - left - 1))
                if best is None or diff <= best:
                    best, brk = diff, k
        g_end = g[-1].end
        # Hold the group on screen until the next group starts (avoids flicker), max +0.5 s.
        if gi + 1 < len(groups):
            g_end = min(max(g_end, groups[gi + 1][0].start), g[-1].end + 0.5)
        for wi, w in enumerate(g):
            start = g[0].start if wi == 0 else w.start
            end = g[wi + 1].start if wi + 1 < len(g) else g_end
            if end <= start:
                end = start + 0.05
            parts = []
            for k, txt in enumerate(texts):
                if k == brk:
                    parts.append("\\N")
                if k == wi:
                    pop = "\\fscx112\\fscy112" if th.pop else ""
                    parts.append(f"{{\\c{th.highlight}{pop}}}{txt}{{\\r}}")
                else:
                    parts.append(txt)
            intro = "{\\fad(40,0)}" if wi == 0 else ""
            text = " ".join(parts).replace(" \\N ", "\\N")
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{intro}{text}")
    return header + "\n".join(lines) + "\n"


def build_srt(words: list[Word], clip_start: float, clip_end: float, max_words: int = 6) -> str:
    rel = [Word(max(0.0, w.start - clip_start), min(clip_end, w.end) - clip_start, w.word)
           for w in words if w.end > clip_start and w.start < clip_end]

    def ts(t: float) -> str:
        ms = int(round(max(0.0, t) * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, g in enumerate(group_words(rel, max_words=max_words, max_chars=42), 1):
        text = " ".join(w.word.strip() for w in g)
        out.append(f"{i}\n{ts(g[0].start)} --> {ts(g[-1].end)}\n{text}\n")
    return "\n".join(out)


def write_ass(path: str | Path, content: str) -> Path:
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    return p
