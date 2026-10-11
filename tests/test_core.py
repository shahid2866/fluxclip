from fluxclip.captions import build_ass, build_srt, group_words
from fluxclip.highlights import Clip, dedupe, find_highlights, snap_clip
from fluxclip.llm import extract_json, resolve_provider
from fluxclip.transcribe import Segment, Transcript, Word


def make_transcript() -> Transcript:
    sentences = [
        "Welcome back to the channel everyone.",
        "Here is the biggest mistake most creators make.",
        "They post every day but never study what works.",
        "Why does that matter so much?",
        "Because your top five videos already hold the secret.",
        "That one simple habit doubled my views in 30 days.",
        "Now a quick story about money.",
        "I sent 100 cold emails and only two said yes.",
        "Those two clients paid my rent for six months.",
        "Thanks for watching and see you next time.",
    ]
    segs, t = [], 0.0
    for s in sentences:
        toks = s.split()
        words = [Word(t + i * 0.4, t + (i + 1) * 0.4, " " + w) for i, w in enumerate(toks)]
        segs.append(Segment(t, t + len(toks) * 0.4, s, words))
        t += len(toks) * 0.4 + 0.3
    return Transcript("en", t, segs)


def test_extract_json_variants():
    assert extract_json('{"clips": []}') == {"clips": []}
    assert extract_json('```json\n{"clips": [1]}\n```') == {"clips": [1]}
    assert extract_json('Sure! Here you go: [{"a": 1}] hope it helps') == [{"a": 1}]


def test_snap_respects_sentence_boundaries_and_limits():
    t = make_transcript()
    starts = {s.start for s in t.segments}
    c = snap_clip(Clip(start=3.1, end=14.0), t, min_len=5, max_len=12)
    assert c is not None
    assert any(abs(c.start - (s - 0.05)) < 0.06 or c.start == 0 for s in starts)
    assert 5 * 0.6 <= c.duration <= 12 + 0.31


def test_dedupe_keeps_best_non_overlapping():
    a = Clip(0, 10, score=90)
    b = Clip(2, 12, score=50)
    c = Clip(20, 30, score=60)
    kept = dedupe([a, b, c])
    assert [k.score for k in kept] == [90, 60]


def test_heuristic_finds_clips_offline():
    t = make_transcript()
    clips = find_highlights(t, num_clips=2, min_len=5, max_len=12, provider="heuristic")
    assert 1 <= len(clips) <= 2
    assert all(c.start < c.end for c in clips)
    assert clips == sorted(clips, key=lambda c: c.score, reverse=True)


def test_resolve_provider_explicit():
    assert resolve_provider("heuristic") == "heuristic"
    assert resolve_provider("anthropic") == "anthropic"


def test_captions_ass_and_srt():
    t = make_transcript()
    words = t.words_between(0, 8)
    ass = build_ass(words, 0, 8, 1080, 1920, theme="bold", title="Hello {world}")
    assert "PlayResX: 1080" in ass and "Dialogue:" in ass
    assert "{world}" not in ass  # braces escaped
    srt = build_srt(words, 0, 8)
    assert srt.startswith("1\n00:00:00,000 -->")


def test_group_words_limits():
    words = [Word(i * 0.3, i * 0.3 + 0.25, f" w{i}") for i in range(10)]
    groups = group_words(words, max_words=3)
    assert all(len(g) <= 3 for g in groups)
    assert sum(len(g) for g in groups) == 10


def test_transcript_roundtrip(tmp_path):
    t = make_transcript()
    p = tmp_path / "t.json"
    t.save(p)
    t2 = Transcript.load(p)
    assert t2.to_prompt_text() == t.to_prompt_text()
    assert len(t2.words) == len(t.words)


def test_llm_path_with_mocked_model(monkeypatch):
    from fluxclip import llm

    reply = '```json\n{"clips": [{"start": 3.0, "end": 12.5, "title": "The biggest mistake", ' \
            '"hook": "Here is the biggest mistake", "score": 91, "hashtags": ["#creator"], ' \
            '"caption": "Stop doing this"}]}\n```'
    monkeypatch.setattr(llm, "complete", lambda *a, **k: reply)
    t = make_transcript()
    clips = find_highlights(t, num_clips=3, min_len=5, max_len=15, provider="anthropic")
    assert len(clips) == 1
    assert clips[0].title == "The biggest mistake" and clips[0].score == 91
