"""Speaker-aware auto-reframing (landscape -> vertical) using OpenCV face detection.

The "virtual camera" follows the dominant face with a dead-zone so it doesn't jitter,
eases on small movements, and hard-cuts (like a human editor) when the speaker changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .utils import log

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class Track:
    centers: np.ndarray   # per-frame crop centre x in pixels (source coordinates)
    face_ratio: float     # fraction of sampled frames where a face was found
    n_frames: int
    fps: float


YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
_state: dict = {}


def _yunet_model() -> str | None:
    """Path to the YuNet face model (downloaded once, ~230 KB). None if unavailable."""
    import os
    import urllib.request

    from .utils import CACHE_DIR

    if os.environ.get("FLUXCLIP_FACE_DETECTOR", "").lower() == "haar":
        return None
    if not hasattr(cv2, "FaceDetectorYN"):
        return None
    path = CACHE_DIR / "models" / "face_detection_yunet_2023mar.onnx"
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, path)
        except Exception as e:  # offline, firewall…
            log.debug("YuNet download failed: %s", e)
            path.unlink(missing_ok=True)
            return None
    return str(path)


def _init_detector() -> str:
    """Pick the best available detector: YuNet (accurate) > Haar cascades > none."""
    if "kind" in _state:
        return _state["kind"]
    model = _yunet_model()
    if model:
        try:
            _state["yunet"] = cv2.FaceDetectorYN.create(model, "", (320, 320), 0.6, 0.3, 50)
            _state["kind"] = "yunet"
            return "yunet"
        except Exception as e:
            log.debug("YuNet init failed: %s", e)
    if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
        base = cv2.data.haarcascades
        _state["front"] = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        _state["profile"] = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
        if not _state["front"].empty():
            _state["kind"] = "haar"
            return "haar"
    log.warning("No face detector available – clips will use the blurred-background layout.")
    _state["kind"] = "none"
    return "none"


def detect_faces(frame: np.ndarray, det_width: int = 640) -> list[tuple[float, float, float, float]]:
    """Return faces as (cx, cy, w, h) in source pixel coordinates."""
    kind = _init_detector()
    if kind == "none":
        return []
    h, w = frame.shape[:2]
    scale = det_width / w if w > det_width else 1.0
    small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
    sh, sw = small.shape[:2]
    found: list = []
    if kind == "yunet":
        det = _state["yunet"]
        det.setInputSize((sw, sh))
        _, faces = det.detect(small)
        if faces is not None:
            found = [(f[0], f[1], f[2], f[3]) for f in faces]
    else:
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        front, profile = _state["front"], _state["profile"]
        min_size = (max(20, sw // 32),) * 2
        found = list(front.detectMultiScale(gray, 1.1, 6, minSize=min_size))
        if not found:
            found = list(profile.detectMultiScale(gray, 1.1, 6, minSize=min_size))
            if not found:  # profile cascade only detects one direction; try mirrored
                flipped = cv2.flip(gray, 1)
                for (x, y, fw, fh) in profile.detectMultiScale(flipped, 1.1, 6, minSize=min_size):
                    found.append((sw - x - fw, y, fw, fh))
    return [((x + fw / 2) / scale, (y + fh / 2) / scale, fw / scale, fh / scale)
            for (x, y, fw, fh) in found]


def _median_filter(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) < 3:
        return x
    k = min(k | 1, (len(x) // 2) * 2 - 1 or 1)
    pad = k // 2
    xp = np.pad(x, pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(xp, k)
    return np.median(windows, axis=1)


def compute_track(path: str, start: float, end: float, crop_w: int,
                  sample_every: float = 0.2) -> Track:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for reframing")
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    n_frames = max(1, int(round((end - start) * fps)))
    step = max(1, int(round(sample_every * fps)))

    sample_idx, sample_x = [], []
    hits = samples = 0
    prev_x = src_w / 2
    for i in range(n_frames):
        if i % step:
            if not cap.grab():
                n_frames = i
                break
            continue
        ok, frame = cap.read()
        if not ok:
            n_frames = i
            break
        samples += 1
        faces = detect_faces(frame)
        if faces:
            hits += 1
            # Prefer big faces, slightly prefer the one we're already on (stability).
            best = max(faces, key=lambda f, px=prev_x: f[2] * f[3]
                       * (1.3 if abs(f[0] - px) < crop_w * 0.3 else 1.0))
            prev_x = best[0]
            sample_idx.append(i)
            sample_x.append(best[0])
    cap.release()
    n_frames = max(1, n_frames)

    if not sample_idx:
        centers = np.full(n_frames, src_w / 2.0)
        return Track(centers, 0.0, n_frames, fps)

    # Step-hold interpolation (preserves cuts) then median filter to kill noise.
    idx = np.arange(n_frames)
    pos = np.searchsorted(sample_idx, idx, side="right") - 1
    pos = np.clip(pos, 0, len(sample_x) - 1)
    raw = np.asarray(sample_x, dtype=float)[pos]
    target = _median_filter(raw, int(fps * 0.8))

    # Virtual camera: dead-zone + easing + hard cuts on big persistent jumps.
    dead = crop_w * 0.08
    cut = crop_w * 0.45
    hold_frames = int(fps * 0.5)
    cam = np.empty(n_frames)
    c = target[0]
    for i, t in enumerate(target):
        d = t - c
        if abs(d) > cut:
            # We process offline, so look ahead: if the subject stays away for
            # `hold_frames`, cut right now instead of lagging behind.
            ahead = target[i:i + hold_frames]
            if np.all(np.abs(ahead - c) > cut):
                c = t
        elif abs(d) > dead:
            c += (d - np.sign(d) * dead) * 0.06
        cam[i] = c
    half = crop_w / 2
    cam = np.clip(cam, half, src_w - half)
    ratio = hits / max(1, samples)
    log.debug("face ratio %.2f over %d samples", ratio, samples)
    return Track(cam, ratio, n_frames, fps)
