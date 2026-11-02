"""Load the trained HAR model and classify accelerometer + gyroscope windows.

    from har import HARClassifier

    clf = HARClassifier.load()                       # default: ml/models/st_ign_realworld_imu
    pred = clf.predict(window)                       # window: (104, 6) -> Prediction
    preds = clf.predict_batch(windows)               # windows: (N, 104, 6) -> list[Prediction]
    preds = clf.predict_stream(samples)              # samples: (M, 6) continuous recording

Input contract (also in model_meta.json):
    * channel order ax, ay, az, gx, gy, gz
    * accelerometer in g, gyroscope in deg/s  (board logs m/s^2 -> use board_to_model_units)
    * sampled at 52 Hz, windows of 104 samples (2 s)
    * raw physical values; normalization is applied here, do not normalize yourself
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

STANDARD_GRAVITY = 9.80665
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "st_ign_realworld_imu"


@dataclass
class Prediction:
    label: str                      # most likely class name
    index: int                      # its index in class_names
    confidence: float               # its softmax probability
    probabilities: dict[str, float] = field(repr=False)
    start_sample: int | None = None  # set by predict_stream: first sample of the window


class HARClassifier:
    def __init__(self, model, meta: dict):
        self.model = model
        self.meta = meta
        self.class_names: list[str] = meta["class_names"]
        self.channels: list[str] = meta["channels"]
        self.window_samples: int = meta["window_samples"]
        self.stride_samples: int = meta["stride_samples"]
        self.sample_rate_hz: float = meta["sample_rate_hz"]
        self._mean = np.asarray(meta["normalization"]["mean"], dtype=np.float32)
        self._std = np.asarray(meta["normalization"]["std"], dtype=np.float32)

    @classmethod
    def load(cls, model_dir: str | Path = DEFAULT_MODEL_DIR) -> "HARClassifier":
        import tensorflow as tf  # imported here so `import har` stays light

        model_dir = Path(model_dir)
        meta = json.loads((model_dir / "model_meta.json").read_text(encoding="utf-8"))
        model = tf.keras.models.load_model(model_dir / meta["model_file"], compile=False)
        return cls(model, meta)

    @property
    def n_channels(self) -> int:
        return len(self.channels)

    def preprocess(self, windows: np.ndarray) -> np.ndarray:
        """(N, 104, 6) physical units -> (N, 104, 6, 1) normalized float32 model input."""
        w = np.asarray(windows, dtype=np.float32)
        expected = (self.window_samples, self.n_channels)
        if w.ndim != 3 or w.shape[1:] != expected:
            raise ValueError(f"expected windows of shape (N, {expected[0]}, {expected[1]}), got {w.shape}")
        return ((w - self._mean) / self._std)[..., np.newaxis]

    def predict_proba(self, windows: np.ndarray) -> np.ndarray:
        """(N, 104, 6) -> (N, n_classes) softmax probabilities."""
        x = self.preprocess(windows)
        return self.model.predict(x, batch_size=1024, verbose=0)

    def predict_batch(self, windows: np.ndarray) -> list[Prediction]:
        return [self._to_prediction(p) for p in self.predict_proba(windows)]

    def predict(self, window: np.ndarray) -> Prediction:
        """One window of shape (104, 6)."""
        return self.predict_batch(np.asarray(window)[np.newaxis])[0]

    def predict_stream(self, samples: np.ndarray, stride: int | None = None) -> list[Prediction]:
        """Slide a window over a continuous (M, 6) recording, same stride as training by default."""
        s = np.asarray(samples, dtype=np.float32)
        if s.ndim != 2 or s.shape[1] != self.n_channels:
            raise ValueError(f"expected samples of shape (M, {self.n_channels}), got {s.shape}")
        stride = stride or self.stride_samples
        starts = list(range(0, len(s) - self.window_samples + 1, stride))
        if not starts:
            return []
        windows = np.stack([s[i:i + self.window_samples] for i in starts])
        preds = self.predict_batch(windows)
        for p, i in zip(preds, starts):
            p.start_sample = i
        return preds

    def _to_prediction(self, proba: np.ndarray) -> Prediction:
        i = int(np.argmax(proba))
        return Prediction(label=self.class_names[i], index=i, confidence=float(proba[i]),
                          probabilities={c: float(v) for c, v in zip(self.class_names, proba)})


def board_to_model_units(samples: np.ndarray) -> np.ndarray:
    """Convert firmware/log.py units to model units: accel m/s^2 -> g; gyro already deg/s."""
    out = np.array(samples, dtype=np.float32, copy=True)
    out[:, :3] /= STANDARD_GRAVITY
    return out


def resample(timestamps_ms: np.ndarray, samples: np.ndarray, target_hz: float) -> np.ndarray:
    """Linear interpolation onto a uniform grid. Fine for small rate errors (e.g. 49 -> 52 Hz);
    upsampling from ~26 Hz cannot recreate the missing high-frequency content."""
    t = (np.asarray(timestamps_ms, dtype=np.float64) - timestamps_ms[0]) / 1000.0
    grid = np.arange(0.0, t[-1], 1.0 / target_hz)
    return np.stack([np.interp(grid, t, samples[:, c]) for c in range(samples.shape[1])], axis=1)
