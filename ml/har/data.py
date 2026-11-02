"""Download and load the RealWorld HAR upper-arm dataset (accelerometer + gyroscope).

Source: https://github.com/alinaytsk/har-realworld-dataset (windows already cut,
split by subject, in physical units). The files are pinned to one commit so a
re-download always gives the same data.

Arrays in each split file:
    X        (N, 104, 6) float32  ax, ay, az [g], gx, gy, gz [deg/s], NOT normalized
    y        (N,)        int64    class index, see ``class_names``
    subject  (N,)        int64    participant id (train/val/test never share one)
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATASET_REPO = "alinaytsk/har-realworld-dataset"
DATASET_COMMIT = "6f24dcd14a23003fffe7f2d72e03c49f4af2a11c"
SPLITS = ("train", "val", "test")
_META_FILES = ("norm_stats.json", "label_map.json")

# .npz files live in Git LFS, so they come from the media host; JSON from raw.
_LFS_URL = f"https://media.githubusercontent.com/media/{DATASET_REPO}/{DATASET_COMMIT}/data/processed/"
_RAW_URL = f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}/data/processed/"


def download(data_dir: str | Path, force: bool = False) -> Path:
    """Fetch train/val/test .npz plus norm_stats.json and label_map.json (~125 MB)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(f"{s}.npz", _LFS_URL) for s in SPLITS] + [(f, _RAW_URL) for f in _META_FILES]
    for name, base in jobs:
        dest = data_dir / name
        if dest.exists() and not force:
            print(f"[data] {name}: already present")
            continue
        print(f"[data] downloading {name} ...")
        tmp = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(base + name, tmp)
        if name.endswith(".npz") and tmp.read_bytes()[:2] != b"PK":
            tmp.unlink()
            raise RuntimeError(f"{name}: download is not an .npz archive (Git LFS pointer?)")
        tmp.replace(dest)
    (data_dir / "SOURCE.txt").write_text(
        f"https://github.com/{DATASET_REPO} @ {DATASET_COMMIT}\n", encoding="utf-8")
    return data_dir


@dataclass
class Split:
    X: np.ndarray        # (N, T, 6), physical units
    y: np.ndarray        # (N,)
    subject: np.ndarray  # (N,)


@dataclass
class Dataset:
    train: Split
    val: Split
    test: Split
    class_names: list[str]
    channels: list[str]
    units: dict[str, str]
    fs_hz: float
    window_samples: int
    stride_samples: int
    mean: np.ndarray     # (6,) train-only channel mean
    std: np.ndarray      # (6,) train-only channel std


def load(data_dir: str | Path) -> Dataset:
    data_dir = Path(data_dir)
    missing = [f for f in [f"{s}.npz" for s in SPLITS] + list(_META_FILES)
               if not (data_dir / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing {missing} in {data_dir}. Run: python -m har.train --download")

    raw = {s: np.load(data_dir / f"{s}.npz") for s in SPLITS}
    splits = {s: Split(r["X"].astype(np.float32), r["y"].astype(np.int64),
                       r["subject"].astype(np.int64)) for s, r in raw.items()}
    ref = raw["train"]
    stats = json.loads((data_dir / "norm_stats.json").read_text(encoding="utf-8"))
    label_map = json.loads((data_dir / "label_map.json").read_text(encoding="utf-8"))

    ds = Dataset(
        **splits,
        class_names=[str(c) for c in ref["class_names"]],
        channels=[str(c) for c in ref["channels"]],
        units=dict(label_map["units"]),
        fs_hz=float(ref["fs"]),
        window_samples=int(ref["window_samples"]),
        stride_samples=int(ref["stride_samples"]),
        mean=np.asarray(stats["mean"], dtype=np.float32),
        std=np.asarray(stats["std"], dtype=np.float32),
    )
    _sanity_check(ds, stats)
    return ds


def _sanity_check(ds: Dataset, stats: dict) -> None:
    if stats.get("computed_on") != "train":
        raise ValueError("norm_stats.json must be computed on the train split only")
    for name in SPLITS:
        s = getattr(ds, name)
        if s.X.shape[1:] != (ds.window_samples, len(ds.channels)):
            raise ValueError(f"{name}: unexpected window shape {s.X.shape}")
        if not np.isfinite(s.X).all():
            raise ValueError(f"{name}: contains NaN/inf")
    shared = (set(ds.train.subject) & set(ds.val.subject)) | \
             (set(ds.train.subject) & set(ds.test.subject)) | \
             (set(ds.val.subject) & set(ds.test.subject))
    if shared:
        raise ValueError(f"subjects leak between splits: {sorted(shared)}")
    # The published stats must match what the train split actually contains.
    mean = ds.train.X.mean(axis=(0, 1))
    if not np.allclose(mean, ds.mean, rtol=1e-3, atol=1e-3):
        raise ValueError(f"norm_stats.json mean {ds.mean} != train mean {mean}")


def resample_dataset(ds: Dataset, target_hz: float | None) -> Dataset:
    """Return a copy of ``ds`` re-windowed at ``target_hz``.

    The dataset's windows overlap by 50 %, so consecutive windows are stitched
    back into continuous segments, each segment is resampled as one signal, and
    new windows are cut from it -- the same thing the board does on its live
    stream, so window edges carry no resampling artifacts. Window duration is
    kept (104 samples at 52 Hz -> 55 at 27.45 Hz), and so is the 50 % overlap.

    Polyphase resampling low-pass filters before decimating (no aliasing). Only
    downsampling is allowed: nothing above the native rate can be recovered.
    Normalization mean/std are recomputed on the resampled train split.
    """
    if target_hz is None or abs(target_hz - ds.fs_hz) < 1e-6:
        return ds
    from fractions import Fraction
    from scipy.signal import resample_poly

    if target_hz > ds.fs_hz:
        raise ValueError(f"sample_rate_hz {target_hz} > dataset rate {ds.fs_hz}; only downsampling is possible")
    ratio = Fraction(target_hz / ds.fs_hz).limit_denominator(2000)
    if abs(float(ratio) * ds.fs_hz - target_hz) > 1e-3:
        raise ValueError(f"cannot express {target_hz}/{ds.fs_hz} as a small integer ratio")

    win = int(round(ds.window_samples * float(ratio)))
    stride = int(round(ds.stride_samples * float(ratio)))

    def rs(split: Split) -> Split:
        xs, ys, subs = [], [], []
        for sig, y, subj in _stitch(split, ds.stride_samples):
            # padtype="line" extrapolates the trend at segment ends instead of zero-padding.
            r = resample_poly(sig, ratio.numerator, ratio.denominator, axis=0, padtype="line")
            for start in range(0, len(r) - win + 1, stride):
                xs.append(r[start:start + win])
                ys.append(y)
                subs.append(subj)
        return Split(np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int64),
                     np.asarray(subs, dtype=np.int64))

    train, val, test = rs(ds.train), rs(ds.val), rs(ds.test)
    std = train.X.std(axis=(0, 1))
    std[std < 1e-6] = 1.0
    return Dataset(
        train=train, val=val, test=test,
        class_names=ds.class_names, channels=ds.channels, units=ds.units,
        fs_hz=float(target_hz),
        window_samples=win,
        stride_samples=stride,
        mean=train.X.mean(axis=(0, 1)).astype(np.float32),
        std=std.astype(np.float32),
    )


def _stitch(split: Split, stride: int):
    """Yield (signal (L, C), label, subject) for each run of windows that continue one another.

    Window j continues window i when it has the same label and subject and its
    first T-stride samples equal window i's last T-stride samples. Matching is by
    content, not row order, because the train split is stored shuffled.
    """
    X, y, subj = split.X, split.y, split.subject
    overlap = X.shape[1] - stride
    heads: dict[bytes, int] = {}
    dup: set[bytes] = set()
    for i in range(len(X)):
        k = X[i, :overlap].tobytes()
        if k in heads:
            dup.add(k)  # ambiguous (e.g. identical flat data): never link through it
        heads[k] = i
    succ = np.full(len(X), -1)
    has_pred = np.zeros(len(X), dtype=bool)
    for i in range(len(X)):
        k = X[i, stride:].tobytes()
        j = heads.get(k, -1)
        if j >= 0 and j != i and k not in dup and y[j] == y[i] and subj[j] == subj[i] and not has_pred[j]:
            succ[i] = j
            has_pred[j] = True
    for start in np.flatnonzero(~has_pred):
        chain = [start]
        while succ[chain[-1]] >= 0:
            chain.append(succ[chain[-1]])
        sig = np.concatenate([X[chain[0]]] + [X[k, overlap:] for k in chain[1:]])
        yield sig, int(y[start]), int(subj[start])
    if has_pred.all() and len(X):
        raise ValueError("window chain has no start (cycle)")


def normalize(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """(x - mean) / std per channel, then add the trailing channel dim the CNN expects."""
    return ((X - mean) / std).astype(np.float32)[..., np.newaxis]
