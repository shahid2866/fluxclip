"""Speech-to-text with word-level timestamps.

Backends:
  * ``local``  – faster-whisper (free, runs on CPU or GPU)  [default]
  * ``openai`` – OpenAI Whisper API (needs OPENAI_API_KEY; fast, no GPU needed)
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .utils import CACHE_DIR, FluxClipError, file_fingerprint, fmt_ts, log, run


@dataclass
class Word:
    start: float
    end: float
    word: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[Segment]

    # ---- helpers -------------------------------------------------------
    @property
    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    def text_between(self, start: float, end: float) -> str:
        return " ".join(
            w.word.strip() for w in self.words if w.end > start and w.start < end
        ).strip()

    def words_between(self, start: float, end: float) -> list[Word]:
        return [w for w in self.words if w.end > start and w.start < end]

    def to_prompt_text(self) -> str:
        """Compact, timestamped transcript for LLMs."""
        return "\n".join(
            f"[{s.start:.1f}-{s.end:.1f}] {s.text.strip()}" for s in self.segments
        )

    def to_readable(self) -> str:
        return "\n".join(f"[{fmt_ts(s.start)}] {s.text.strip()}" for s in self.segments)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs = [
            Segment(s["start"], s["end"], s["text"], [Word(**w) for w in s.get("words", [])])
            for s in d["segments"]
        ]
        return cls(d.get("language", "en"), d.get("duration", 0.0), segs)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "Transcript":
        return cls.from_dict(json.loads(Path(path).read_text()))


def _extract_audio(video: Path, out_wav: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav)])


def _fill_missing_words(seg: Segment) -> None:
    """If a backend returned no word timings, spread words evenly over the segment."""
    if seg.words:
        return
    tokens = seg.text.split()
    if not tokens:
        return
    step = (seg.end - seg.start) / len(tokens)
    seg.words = [
        Word(seg.start + i * step, seg.start + (i + 1) * step, " " + t)
        for i, t in enumerate(tokens)
    ]


def _transcribe_local(audio: Path, model_size: str, language: str | None) -> tuple[list[Segment], str]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise FluxClipError("Local transcription needs faster-whisper: pip install faster-whisper") from e
    device = os.environ.get("FLUXCLIP_DEVICE", "auto")
    compute = os.environ.get("FLUXCLIP_COMPUTE_TYPE", "default")
    log.info("Loading Whisper model '%s' (first run downloads it)…", model_size)
    model = WhisperModel(model_size, device=device, compute_type=compute)
    segs_iter, info = model.transcribe(
        str(audio), language=language, word_timestamps=True, vad_filter=True, beam_size=5
    )
    segments = []
    for s in segs_iter:
        words = [Word(float(w.start), float(w.end), w.word) for w in (s.words or [])]
        segments.append(Segment(float(s.start), float(s.end), s.text, words))
    return segments, info.language


def _transcribe_openai(audio: Path, language: str | None) -> tuple[list[Segment], str]:
    import urllib.request
    import uuid

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise FluxClipError("OPENAI_API_KEY is not set (needed for --transcriber openai).")
    # Compress to mp3 to stay under the 25 MB API limit.
    mp3 = audio.with_suffix(".mp3")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(audio), "-b:a", "48k", str(mp3)])
    if mp3.stat().st_size > 25 * 1024 * 1024:
        raise FluxClipError("Audio is larger than 25 MB; use the local transcriber for long videos.")
    boundary = uuid.uuid4().hex
    fields = {
        "model": "whisper-1",
        "response_format": "verbose_json",
    }
    if language:
        fields["language"] = language
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for g in ("word", "segment"):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"timestamp_granularities[]\"\r\n\r\n{g}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp3\"\r\n"
             f"Content-Type: audio/mpeg\r\n\r\n").encode() + mp3.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    req = urllib.request.Request(
        f"{base}/audio/transcriptions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
    all_words = [Word(float(w["start"]), float(w["end"]), " " + w["word"]) for w in data.get("words", [])]
    segments = []
    for s in data.get("segments", []):
        st, en = float(s["start"]), float(s["end"])
        ws = [w for w in all_words if w.start >= st - 0.01 and w.start < en]
        segments.append(Segment(st, en, s["text"], ws))
    return segments, data.get("language", language or "en")


def transcribe(
    video: str | Path,
    model_size: str = "small",
    language: str | None = None,
    backend: str = "local",
    use_cache: bool = True,
) -> Transcript:
    """Transcribe a video file. Results are cached per file + model."""
    from .utils import probe

    video = Path(video)
    cache = CACHE_DIR / "transcripts" / f"{file_fingerprint(video)}-{backend}-{model_size}-{language or 'auto'}.json"
    if use_cache and cache.exists():
        log.info("Using cached transcript %s", cache)
        return Transcript.load(cache)

    info = probe(video)
    if not info.has_audio:
        raise FluxClipError("This video has no audio track, so there is nothing to transcribe.")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        _extract_audio(video, wav)
        if backend == "openai":
            segments, lang = _transcribe_openai(wav, language)
        elif backend == "local":
            segments, lang = _transcribe_local(wav, model_size, language)
        else:
            raise FluxClipError(f"Unknown transcriber backend '{backend}' (use local|openai)")
    for s in segments:
        _fill_missing_words(s)
    t = Transcript(lang, info.duration, segments)
    cache.parent.mkdir(parents=True, exist_ok=True)
    t.save(cache)
    return t
