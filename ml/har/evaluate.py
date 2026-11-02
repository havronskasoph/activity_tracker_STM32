"""Metrics and plots: accuracy, macro-F1, per-class report, confusion matrices, curves."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files, never open windows
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, class_names: list[str]) -> dict:
    labels = list(range(len(class_names)))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        "n_windows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)),
        "per_class": classification_report(y_true, y_pred, labels=labels, target_names=class_names,
                                           output_dict=True, zero_division=0),
        "confusion_matrix": cm.tolist(),
        "report_text": classification_report(y_true, y_pred, labels=labels, target_names=class_names,
                                             digits=3, zero_division=0),
    }


def plot_confusion_matrix(cm: np.ndarray, class_names: list[str], path: Path, title: str) -> None:
    cm = np.asarray(cm)
    row_sum = cm.sum(axis=1, keepdims=True)
    norm = np.divide(cm, row_sum, out=np.zeros_like(cm, dtype=float), where=row_sum > 0)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, data, fmt, sub in ((axes[0], cm, "d", "counts"),
                               (axes[1], norm * 100, ".1f", "% of true class (recall)")):
        im = ax.imshow(data, cmap="Blues")
        ax.set_xticks(range(len(class_names)), class_names, rotation=45, ha="right")
        ax.set_yticks(range(len(class_names)), class_names)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(sub)
        thresh = data.max() / 2 if data.max() > 0 else 0.5
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                ax.text(j, i, format(data[i, j], fmt), ha="center", va="center",
                        color="white" if data[i, j] > thresh else "black", fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_training_curves(history: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    epochs = range(1, len(history["loss"]) + 1)
    for ax, key, label in ((axes[0], "loss", "Loss"), (axes[1], "accuracy", "Accuracy")):
        ax.plot(epochs, history[key], label="train")
        if f"val_{key}" in history:
            ax.plot(epochs, history[f"val_{key}"], label="val")
        ax.set_xlabel("Epoch")
        ax.set_title(label)
        ax.grid(alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_split_report(metrics: dict, class_names: list[str], out_dir: Path, split: str) -> None:
    """Save <split>_metrics.json, <split>_report.txt, <split>_confusion_matrix.{csv,png}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cm = np.asarray(metrics["confusion_matrix"])
    np.savetxt(out_dir / f"{split}_confusion_matrix.csv", cm, fmt="%d", delimiter=",",
               header=",".join(class_names), comments="")
    (out_dir / f"{split}_report.txt").write_text(
        f"{split}: accuracy={metrics['accuracy']:.4f}  macro_f1={metrics['macro_f1']:.4f}  "
        f"n={metrics['n_windows']}\n\n{metrics['report_text']}", encoding="utf-8")
    plot_confusion_matrix(cm, class_names, out_dir / f"{split}_confusion_matrix.png",
                          f"{split}: accuracy {metrics['accuracy']:.3f}, macro-F1 {metrics['macro_f1']:.3f}")
    serializable = {k: v for k, v in metrics.items() if k != "report_text"}
    (out_dir / f"{split}_metrics.json").write_text(json.dumps(serializable, indent=2), encoding="utf-8")
