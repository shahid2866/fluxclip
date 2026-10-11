"""End-to-end tests for the Studio API (no network, no Whisper download, no API key)."""
import json
import shutil
import subprocess

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fluxclip.transcribe import Segment, Transcript, Word  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")

SENTENCES = [
    "Here is the biggest mistake most creators make.",
    "They post every day but never study what works.",
    "Why does that matter so much?",
    "Because your top five videos already hold the secret.",
    "That one simple habit doubled my views in 30 days.",
    "Now a quick story about money.",
    "I sent 100 cold emails and only two said yes.",
    "Those two clients paid my rent for six months.",
]


def fake_transcript(duration: float) -> Transcript:
    segs, t = [], 0.3
    for s in SENTENCES:
        toks = s.split()
        words = [Word(t + i * 0.3, t + (i + 1) * 0.3, " " + w) for i, w in enumerate(toks)]
        segs.append(Segment(t, t + len(toks) * 0.3, s, words))
        t += len(toks) * 0.3 + 0.2
    return Transcript("en", duration, segs)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fluxclip.server import app as app_mod
    from fluxclip.server import db, jobs

    db.reset_for_tests(tmp_path / "data")
    monkeypatch.setattr(jobs, "transcribe", lambda src, *a, **k: fake_transcript(24.0))
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(jobs, "_env_baseline", {k: None for k in jobs._env_baseline})
    monkeypatch.setattr("fluxclip.llm._ollama_up", lambda: False)
    return TestClient(app_mod.app)


@pytest.fixture()
def video(tmp_path):
    path = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300", "-t", "24", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def test_full_flow(client, video):
    from fluxclip.server import jobs

    assert client.get("/api/health").json()["ok"]

    settings = {"num_clips": 2, "min_len": 6, "max_len": 12, "caption_style": "opus"}
    with video.open("rb") as fh:
        r = client.post("/api/projects/upload", files={"file": ("talk.mp4", fh, "video/mp4")},
                        data={"settings": json.dumps(settings)})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "queued"

    jobs.run_sync("project", pid)
    p = client.get(f"/api/projects/{pid}").json()
    assert p["status"] == "done", p
    assert p["thumbnail_url"]
    assert 1 <= len(p["clips"]) <= 2
    clip = p["clips"][0]
    assert clip["status"] == "ready" and clip["url"]
    assert client.get(clip["url"]).status_code == 200
    assert client.get(clip["srt_url"]).status_code == 200

    # Listing
    assert client.get("/api/projects").json()[0]["clip_count"] == len(p["clips"])

    # Search ("find keywords or moments")
    res = client.get(f"/api/projects/{pid}/search", params={"q": "cold emails"}).json()["results"]
    assert res and "cold emails" in res[0]["text"]

    # Edit -> re-render (new version, old file removed)
    old_url = clip["url"]
    r = client.patch(f"/api/clips/{clip['id']}", json={"headline": "New hook", "render": {"caption_style": "neon"}})
    assert r.json()["status"] == "pending"
    jobs.run_sync("render", clip["id"])
    c2 = client.get(f"/api/projects/{pid}").json()["clips"]
    c2 = next(c for c in c2 if c["id"] == clip["id"])
    assert c2["status"] == "ready" and c2["version"] == 2 and c2["url"] != old_url
    assert client.get(old_url.split("?")[0]).status_code == 404

    # Custom clip from a moment
    r = client.post(f"/api/projects/{pid}/clips", json={"start": res[0]["start"], "end": res[0]["end"]})
    assert r.status_code == 201
    jobs.run_sync("render", r.json()["id"])
    assert client.get(f"/api/projects/{pid}").json()["clips"][-1]["status"] in ("ready", "failed")

    # Path traversal is blocked
    assert client.get(f"/files/{pid}/../../studio.db").status_code == 404

    # Delete
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_settings_masking(client):
    r = client.put("/api/settings", json={"provider": "anthropic", "anthropic_api_key": "sk-ant-secret-1234"})
    body = r.json()
    assert body["anthropic_api_key"] == "••••1234" and body["anthropic_api_key_set"]
    # Echoing the masked value back must not overwrite the real key.
    client.put("/api/settings", json={"anthropic_api_key": "••••1234"})
    from fluxclip.server import db

    assert db.get_settings()["anthropic_api_key"] == "sk-ant-secret-1234"
    # Empty string clears it.
    assert client.put("/api/settings", json={"anthropic_api_key": ""}).json()["anthropic_api_key_set"] is False


def test_validation(client):
    r = client.post("/api/projects", json={"source": "not a url"})
    assert r.status_code == 422
    r = client.post("/api/projects", json={"source": "https://x.com/v", "settings": {"aspect": "3:2"}})
    assert r.status_code == 422
