"""Compare FluxClip's picks with clips from another tool (e.g. OpusClip).

Usage:
  python scripts/compare_clips.py clips/clips.json "25:14-25:44" "26:54-27:19" "25:51-26:30"

For each reference range it prints the best-overlapping FluxClip clip and the overlap
(IoU: 100% = identical boundaries).
"""
import json
import sys


def secs(ts: str) -> float:
    parts = [float(p) for p in ts.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def iou(a, b) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    clips = data["clips"]
    refs = [tuple(secs(x) for x in r.split("-")) for r in sys.argv[2:]]
    found = 0
    for r in refs:
        best = max(clips, key=lambda c: iou(r, (c["start"], c["end"])), default=None)
        score = iou(r, (best["start"], best["end"])) if best else 0
        found += score > 0.3
        label = f'{best["title"]!r} [{best["start"]:.0f}-{best["end"]:.0f}s]' if best and score > 0 else "no match"
        print(f"reference {r[0]:.0f}-{r[1]:.0f}s -> {label}  overlap {score:.0%}")
    print(f"\n{found}/{len(refs)} reference moments also found by FluxClip (overlap > 30%).")


if __name__ == "__main__":
    main()
