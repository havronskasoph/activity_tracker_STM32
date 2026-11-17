"""Завантаження датасетів для кожної моделі — рівно так, як це робив train.py."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from . import config as C

# ml/har/data.py тягне лише numpy, тому імпортується без TensorFlow.
if str(C.ML_DIR) not in sys.path:
    sys.path.insert(0, str(C.ML_DIR))


def _har_data():
    from har import data as D
    return D


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_for(model_key: str):
    """Повертає об'єкт Dataset (ml.har.data.Dataset) у тому вигляді, який бачила модель.

    Для 27-герцової моделі застосовується штатна resample_dataset — та сама
    функція і той самий цільовий rate, що в configs/st_ign_realworld_imu_27hz.yaml.
    """
    spec = C.MODELS[model_key]
    d = C.dataset_dir(spec["dataset"])
    C.require(d, f"теку датасету для моделі {spec['name']}",
              "задай шлях змінною HAR_DATASET_52HZ або HAR_DATASET_104HZ, див. README.md")
    ds = _har_data().load(d)
    if spec["resample_hz"] is not None:
        ds = _har_data().resample_dataset(ds, spec["resample_hz"])
    return ds


def norm_stats(model_key: str, ds) -> tuple[np.ndarray, np.ndarray]:
    """mean/std, якими нормалізувався вхід саме цієї моделі."""
    spec = C.MODELS[model_key]
    if spec["norm_from"] == "model_meta":
        meta = json.loads((spec["dir"] / "model_meta.json").read_text(encoding="utf-8"))
        n = meta["normalization"]
        return (np.asarray(n["mean"], np.float32), np.asarray(n["std"], np.float32))
    return ds.mean, ds.std


def meta(model_key: str) -> dict:
    return json.loads((C.MODELS[model_key]["dir"] / "model_meta.json").read_text(encoding="utf-8"))


def stitch_filter_rewindow(split, stride: int, sos, window: int):
    """Склеює вікна в неперервні сегменти, фільтрує причинно, ріже вікна наново.

    Відтворює те, що робить плата: har_preproc.c проганяє ФНЧ по неперервному
    потоку, а не по кожному вікну окремо, тож фільтрувати вікна поодинці було б
    нечесно — на краях з'явилися б перехідні процеси, яких на платі немає.

    sos=None — та сама нарізка, але без фільтра: базова лінія для порівняння.
    """
    from scipy.signal import sosfilt
    D = _har_data()
    xs, ys, subs = [], [], []
    for sig, y, subj in D._stitch(split, stride):
        f = sig if sos is None else sosfilt(sos, sig, axis=0)
        for start in range(0, len(f) - window + 1, stride):
            xs.append(f[start:start + window])
            ys.append(y)
            subs.append(subj)
    return (np.asarray(xs, np.float32), np.asarray(ys, np.int64), np.asarray(subs, np.int64))
