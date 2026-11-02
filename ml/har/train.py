"""Train ST-IGN on 6-axis (accel + gyro) windows and write all artifacts.

    cd ml
    python -m har.train --config configs/st_ign_realworld_imu.yaml --download

Writes to <output_root>/<run_name>/:
    model.keras                     trained model (best epoch by val_loss)
    model_meta.json                 everything inference needs: classes, channels, units,
                                    sample rate, window, normalization mean/std
    config.yaml                     the exact config used
    history.csv, training_curves.png
    {val,test}_metrics.json, {val,test}_report.txt,
    {val,test}_confusion_matrix.{csv,png}
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tensorflow as tf
import yaml
from sklearn.utils.class_weight import compute_class_weight

from . import data as data_lib
from .evaluate import compute_metrics, plot_training_curves, write_split_report
from .model import get_ign


class TimeLimit(tf.keras.callbacks.Callback):
    """Stop after the epoch during which the wall-clock budget runs out."""

    def __init__(self, max_seconds: float):
        super().__init__()
        self.max_seconds = max_seconds
        self.start = 0.0
        self.triggered = False

    def on_train_begin(self, logs=None):
        self.start = time.monotonic()

    def on_epoch_end(self, epoch, logs=None):
        if time.monotonic() - self.start >= self.max_seconds:
            self.triggered = True
            self.model.stop_training = True
            print(f"\n[train] time limit of {self.max_seconds / 60:.1f} min reached after epoch {epoch + 1}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="configs/st_ign_realworld_imu.yaml")
    p.add_argument("--download", action="store_true", help="download the dataset first if missing")
    p.add_argument("--max-minutes", type=float, help="override training.max_train_minutes")
    p.add_argument("--epochs", type=int, help="override training.epochs")
    p.add_argument("--output-dir", help="override <output_root>/<run_name>")
    args = p.parse_args(argv)

    cfg_path = Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    tr = cfg["training"]
    if args.max_minutes is not None:
        tr["max_train_minutes"] = args.max_minutes
    if args.epochs is not None:
        tr["epochs"] = args.epochs
    out_dir = Path(args.output_dir or Path(cfg["output_root"]) / cfg["run_name"])
    out_dir.mkdir(parents=True, exist_ok=True)

    tf.keras.utils.set_random_seed(cfg["seed"])

    data_dir = Path(cfg["dataset"]["data_dir"])
    if args.download:
        data_lib.download(data_dir)
    ds = data_lib.load(data_dir)
    source_hz = ds.fs_hz
    target_hz = cfg["dataset"].get("sample_rate_hz")
    if target_hz is not None and abs(target_hz - source_hz) > 1e-6:
        print(f"[train] resampling windows {source_hz:g} Hz -> {target_hz:g} Hz")
        ds = data_lib.resample_dataset(ds, target_hz)
    print(f"[train] {ds.fs_hz:g} Hz, window {ds.window_samples}x{len(ds.channels)} {ds.channels}, "
          f"classes {ds.class_names}")
    print(f"[train] windows: train {len(ds.train.y)}, val {len(ds.val.y)}, test {len(ds.test.y)}")

    x_train = data_lib.normalize(ds.train.X, ds.mean, ds.std)
    x_val = data_lib.normalize(ds.val.X, ds.mean, ds.std)
    x_test = data_lib.normalize(ds.test.X, ds.mean, ds.std)

    class_weight = None
    if tr.get("class_weight") == "balanced":
        classes = np.arange(len(ds.class_names))
        w = compute_class_weight("balanced", classes=classes, y=ds.train.y)
        class_weight = {int(c): float(v) for c, v in zip(classes, w)}
        print("[train] class weights:", {ds.class_names[c]: round(v, 3) for c, v in class_weight.items()})

    input_shape = (ds.window_samples, len(ds.channels), 1)
    model = get_ign(input_shape, num_classes=len(ds.class_names), dropout=cfg["model"]["dropout"])
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=tr["learning_rate"]),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.summary()

    best_path = out_dir / "model.keras"
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(best_path, monitor="val_loss", mode="min", save_best_only=True),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=tr["early_stopping_patience"]),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=tr["reduce_lr_factor"],
                                             patience=tr["reduce_lr_patience"],
                                             min_lr=tr["min_learning_rate"]),
        tf.keras.callbacks.CSVLogger(out_dir / "history.csv"),
    ]
    time_limit = None
    if tr.get("max_train_minutes"):
        time_limit = TimeLimit(tr["max_train_minutes"] * 60)
        callbacks.append(time_limit)

    t0 = time.monotonic()
    history = model.fit(x_train, ds.train.y, validation_data=(x_val, ds.val.y),
                        batch_size=tr["batch_size"], epochs=tr["epochs"], class_weight=class_weight,
                        callbacks=callbacks, shuffle=True, verbose=2)
    train_seconds = time.monotonic() - t0
    hist = {k: [float(v) for v in vals] for k, vals in history.history.items()}
    epochs_run = len(hist["loss"])
    best_epoch = int(np.argmin(hist["val_loss"])) + 1
    if time_limit and time_limit.triggered:
        stop_reason = "time_limit"
    elif epochs_run < tr["epochs"]:
        stop_reason = "early_stopping"
    else:
        stop_reason = "max_epochs"

    # Evaluate the checkpoint we ship, not whatever the last epoch was.
    model = tf.keras.models.load_model(best_path)
    results = {}
    for split, x, y in (("val", x_val, ds.val.y), ("test", x_test, ds.test.y)):
        y_pred = model.predict(x, batch_size=1024, verbose=0).argmax(axis=1)
        m = compute_metrics(y, y_pred, ds.class_names)
        write_split_report(m, ds.class_names, out_dir, split)
        results[split] = {"accuracy": m["accuracy"], "macro_f1": m["macro_f1"], "weighted_f1": m["weighted_f1"]}
        print(f"\n[{split}] accuracy {m['accuracy']:.4f}  macro-F1 {m['macro_f1']:.4f}\n{m['report_text']}")
    plot_training_curves(hist, out_dir / "training_curves.png")

    meta = {
        "model_file": "model.keras",
        "architecture": cfg["model"]["name"],
        "input_shape": list(input_shape),
        "class_names": ds.class_names,
        "channels": ds.channels,
        "units": ds.units,
        "sample_rate_hz": ds.fs_hz,
        "dataset_native_rate_hz": source_hz,
        "window_samples": ds.window_samples,
        "stride_samples": ds.stride_samples,
        "normalization": {"mean": ds.mean.tolist(), "std": ds.std.tolist(),
                          "formula": "(x - mean) / std, per channel, in the units above"},
        "params": int(model.count_params()),
        "dataset": {"repo": f"https://github.com/{data_lib.DATASET_REPO}",
                    "commit": data_lib.DATASET_COMMIT,
                    "train_subjects": sorted(int(s) for s in set(ds.train.subject)),
                    "val_subjects": sorted(int(s) for s in set(ds.val.subject)),
                    "test_subjects": sorted(int(s) for s in set(ds.test.subject))},
        "training": {"finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "epochs_run": epochs_run, "best_epoch": best_epoch, "stop_reason": stop_reason,
                     "train_seconds": round(train_seconds, 1), "tensorflow": tf.__version__},
        "results": results,
    }
    (out_dir / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if cfg_path.resolve() != (out_dir / "config.yaml").resolve():
        shutil.copyfile(cfg_path, out_dir / "config.yaml")
    print(f"\n[train] {epochs_run} epochs in {train_seconds:.0f}s (stop: {stop_reason}, best epoch {best_epoch})")
    print(f"[train] artifacts in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
