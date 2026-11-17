"""Обчислення метрик — ті самі формули, що в ml/har/evaluate.py."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix,
                             classification_report, f1_score)

from . import config as C


def compute(y_true: np.ndarray, y_pred: np.ndarray, subjects: np.ndarray | None = None) -> dict:
    labels = list(range(len(C.CLASS_NAMES)))
    rep = classification_report(y_true, y_pred, labels=labels, target_names=C.CLASS_NAMES,
                                output_dict=True, zero_division=0)
    out = {
        "n_windows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)),
        "f1_per_class": {c: float(rep[c]["f1-score"]) for c in C.CLASS_NAMES},
        "precision_per_class": {c: float(rep[c]["precision"]) for c in C.CLASS_NAMES},
        "recall_per_class": {c: float(rep[c]["recall"]) for c in C.CLASS_NAMES},
        "support_per_class": {c: int(rep[c]["support"]) for c in C.CLASS_NAMES},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }
    if subjects is not None:
        per = {}
        for s in sorted(set(int(v) for v in subjects)):
            m = subjects == s
            per[str(s)] = {
                "macro_f1": float(f1_score(y_true[m], y_pred[m], labels=labels,
                                           average="macro", zero_division=0)),
                "accuracy": float(accuracy_score(y_true[m], y_pred[m])),
                "n_windows": int(m.sum()),
            }
        out["per_subject"] = per
    return out
