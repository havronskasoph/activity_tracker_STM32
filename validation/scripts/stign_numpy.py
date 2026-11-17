"""Прямий прохід ST-IGN на NumPy — без TensorFlow.

Навіщо: тести 1, 5 і 6 мають запускатися будь-де, зокрема там, де TF не
встановлений. Ваги читаються просто з архіву .keras (це zip із model.weights.h5).
Відповідність перевірена: на всіх трьох моделях відтворює метрики з
model_meta.json до 1e-9 (це й перевіряє тест 1).

Архітектура (ml/har/model.py):
    Conv2D(24, (16,1), valid) -> ReLU -> MaxPool((3,1),(3,1)) -> Flatten
    -> Dense(12) -> Dropout(0.5) -> Dense(5, softmax)
Dropout на інференсі — тотожність.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import h5py
import numpy as np

KERNEL_T = 16
POOL_T = 3
FILTERS = 24


def load_model(keras_path: Path) -> tuple[dict, tuple[int, int, int]]:
    """Повертає (ваги, форма_входу) з файлу .keras."""
    with zipfile.ZipFile(keras_path) as z:
        blob = z.read("model.weights.h5")
        cfg = json.loads(z.read("config.json"))
    with h5py.File(io.BytesIO(blob), "r") as f:
        w = {
            "cw": f["layers/conv2d/vars/0"][:],
            "cb": f["layers/conv2d/vars/1"][:],
            "d0w": f["layers/dense/vars/0"][:],
            "d0b": f["layers/dense/vars/1"][:],
            "d1w": f["layers/dense_1/vars/0"][:],
            "d1b": f["layers/dense_1/vars/1"][:],
        }
    shape = tuple(cfg["config"]["layers"][0]["config"]["batch_shape"][1:])
    return w, shape


def predict_proba(X: np.ndarray, w: dict, batch: int = 1500) -> np.ndarray:
    """X: (N, T, C, 1) нормалізований float32 -> (N, 5) імовірності."""
    kern = w["cw"][:, 0, 0, :]
    out = []
    for i in range(0, len(X), batch):
        x = X[i:i + batch, :, :, 0]
        sw = np.lib.stride_tricks.sliding_window_view(x, KERNEL_T, axis=1)
        h = np.einsum("btck,kf->btcf", sw, kern, optimize=True) + w["cb"]
        np.maximum(h, 0, out=h)
        t = (h.shape[1] // POOL_T) * POOL_T
        h = h[:, :t].reshape(h.shape[0], t // POOL_T, POOL_T, h.shape[2], h.shape[3]).max(axis=2)
        z = h.reshape(h.shape[0], -1) @ w["d0w"] + w["d0b"]
        z = z @ w["d1w"] + w["d1b"]
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        out.append((e / e.sum(axis=1, keepdims=True)).astype(np.float32))
    return np.concatenate(out)


def normalize(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """(x - mean) / std по каналах + вісь каналу, як у ml/har/data.normalize."""
    return ((X - mean) / std).astype(np.float32)[..., np.newaxis]


def count_params(window_samples: int, channels: int = 6, num_classes: int = 5) -> int:
    flat = ((window_samples - KERNEL_T + 1) // POOL_T) * channels * FILTERS
    return (KERNEL_T * FILTERS + FILTERS) + (flat * 12 + 12) + (12 * num_classes + num_classes)


def count_macc(window_samples: int, channels: int = 6, num_classes: int = 5) -> int:
    conv_t = window_samples - KERNEL_T + 1
    flat = (conv_t // POOL_T) * channels * FILTERS
    return conv_t * channels * FILTERS * KERNEL_T + flat * 12 + 12 * num_classes


def activation_bytes(window_samples: int, channels: int = 6) -> dict:
    """Оцінка RAM під активації, float32."""
    conv_t = window_samples - KERNEL_T + 1
    pool_t = conv_t // POOL_T
    a = {
        "input": window_samples * channels * 4,
        "conv": conv_t * channels * FILTERS * 4,
        "pool": pool_t * channels * FILTERS * 4,
    }
    a["peak"] = a["conv"] + max(a["input"], a["pool"])
    return a
