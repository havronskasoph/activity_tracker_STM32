"""Classify a board recording made with tools/log.py.

    cd ml
    python -m har.predict ../data/walk_p1_120000.csv
    python -m har.predict ../data/walk_p1_120000.csv --resample    # if the board is not at 52 Hz

Expects the 7-column log format: timestamp_ms,ax,ay,az,gx,gy,gz
(accel in m/s^2, gyro in deg/s -- what the current firmware prints).
"""
from __future__ import annotations

import argparse
from collections import Counter

import numpy as np

from .inference import DEFAULT_MODEL_DIR, HARClassifier, board_to_model_units, resample


def read_log_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line[0].isalpha():
                continue  # comments and the header
            parts = line.split(",")
            if len(parts) != 7:
                raise ValueError(f"{path}: expected 7 columns (timestamp_ms + 6 axes), got {len(parts)}: {line}")
            rows.append([float(p) for p in parts])
    if not rows:
        raise ValueError(f"{path}: no data rows")
    a = np.asarray(rows)
    return a[:, 0], a[:, 1:]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="recording from tools/log.py")
    p.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    p.add_argument("--resample", action="store_true", help="interpolate onto the model's sample rate first")
    args = p.parse_args(argv)

    clf = HARClassifier.load(args.model_dir)
    t_ms, samples = read_log_csv(args.csv)
    samples = board_to_model_units(samples)

    # Mean step (timestamps are whole ms, so a median would round 19.23 ms to 19),
    # ignoring board restarts and gaps.
    steps = np.diff(t_ms)
    steps = steps[steps > 0]
    rate = 1000.0 / steps[steps < 3 * np.median(steps)].mean()
    print(f"{len(samples)} samples, measured rate {rate:.2f} Hz (model expects {clf.sample_rate_hz:g} Hz)")
    if args.resample:
        samples = resample(t_ms, samples, clf.sample_rate_hz)
        rate = clf.sample_rate_hz
        print(f"resampled to {len(samples)} samples at {rate:g} Hz")
    elif abs(rate - clf.sample_rate_hz) / clf.sample_rate_hz > 0.03:
        print("WARNING: sample rate differs from training by >3%; windows will not span 2.0 s "
              "and predictions are unreliable. Fix the firmware ODR or pass --resample.")

    preds = clf.predict_stream(samples)
    if not preds:
        print(f"recording shorter than one window ({clf.window_samples} samples)")
        return
    for pr in preds:
        t = pr.start_sample / rate
        print(f"t={t:7.1f}s  {pr.label:<11} {pr.confidence:5.2f}")
    counts = Counter(pr.label for pr in preds)
    print("\nsummary:", ", ".join(f"{k} {v}" for k, v in counts.most_common()))


if __name__ == "__main__":
    main()
