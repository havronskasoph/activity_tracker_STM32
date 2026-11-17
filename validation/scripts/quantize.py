"""Тест 2: квантування обраної моделі в int8 (PTQ) і порівняння з float32.

Потребує TensorFlow. Якщо його немає — повертає статус "skipped" із причиною,
а pytest перетворює це на SKIP, а не на FAIL.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from . import config as C
from . import datasets, metrics


def available() -> tuple[bool, str]:
    try:
        import tensorflow  # noqa: F401
    except Exception as e:
        return False, (f"TensorFlow недоступний ({type(e).__name__}). "
                       "Створи середовище за інструкцією у validation/README.md "
                       "і запускай run_all.py його інтерпретатором.")
    return True, ""


def _to_tflite_int8(keras_path: Path, rep_data: np.ndarray, out_path: Path) -> None:
    import tensorflow as tf

    model = tf.keras.models.load_model(keras_path)

    def representative():
        for i in range(len(rep_data)):
            yield [rep_data[i:i + 1].astype(np.float32)]

    def _convert(conv):
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = representative
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        return conv.convert()

    try:
        blob = _convert(tf.lite.TFLiteConverter.from_keras_model(model))
    except Exception:
        # Keras 3 не завжди конвертується напряму — через проміжний SavedModel.
        with tempfile.TemporaryDirectory() as td:
            model.export(td)
            blob = _convert(tf.lite.TFLiteConverter.from_saved_model(td))
    out_path.write_bytes(blob)


def _run_tflite(path: Path, X: np.ndarray, batch_log: int = 2000) -> np.ndarray:
    import tensorflow as tf

    interp = tf.lite.Interpreter(model_path=str(path))
    interp.allocate_tensors()
    inp, out = interp.get_input_details()[0], interp.get_output_details()[0]
    in_scale, in_zp = inp["quantization"]
    preds = np.empty(len(X), dtype=np.int64)
    for i in range(len(X)):
        q = np.round(X[i] / in_scale + in_zp).astype(inp["dtype"])
        interp.set_tensor(inp["index"], q[np.newaxis, ...])
        interp.invoke()
        preds[i] = int(np.argmax(interp.get_tensor(out["index"])[0]))
        if batch_log and (i + 1) % batch_log == 0:
            print(f"    int8: {i + 1}/{len(X)}", flush=True)
    return preds


def run(float_metrics: dict, n_representative: int = 300, seed: int = 123) -> dict:
    ok, why = available()
    if not ok:
        return {"status": "skipped", "reason": why}

    from .stign_numpy import load_model, normalize

    key = C.CHOSEN
    spec = C.MODELS[key]
    ds = datasets.load_for(key)
    mean, std = datasets.norm_stats(key, ds)

    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ds.train.X), size=min(n_representative, len(ds.train.X)), replace=False)
    rep = normalize(ds.train.X[idx], mean, std)
    x_test = normalize(ds.test.X, mean, std)

    out_path = C.RESULTS_DIR / f"{spec['name']}_int8.tflite"
    print(f"  конвертація в int8 (PTQ, {len(rep)} вікон з train) ...", flush=True)
    _to_tflite_int8(spec["dir"] / "model.keras", rep, out_path)
    print(f"  інференс int8 на {len(x_test)} вікнах ...", flush=True)
    pred = _run_tflite(out_path, x_test)
    m = metrics.compute(ds.test.y, pred, ds.test.subject)

    f_mf1 = float_metrics["macro_f1"]
    f_walk = float_metrics["f1_per_class"]["Walking"]
    drop_macro = (f_mf1 - m["macro_f1"]) * 100.0
    drop_walk = (f_walk - m["f1_per_class"]["Walking"]) * 100.0
    return {
        "status": "ok",
        "model": spec["name"],
        "tflite_file": out_path.name,
        "tflite_bytes": out_path.stat().st_size,
        "representative_windows": int(len(rep)),
        "float32": {"macro_f1": f_mf1, "accuracy": float_metrics["accuracy"],
                    "f1_per_class": float_metrics["f1_per_class"]},
        "int8": {"macro_f1": m["macro_f1"], "accuracy": m["accuracy"],
                 "f1_per_class": m["f1_per_class"]},
        "macro_f1_drop_pp": drop_macro,
        "walking_f1_drop_pp": drop_walk,
        "criteria": {"macro_f1_drop_pp_max": C.CRITERIA["quant_macro_f1_drop_pp"],
                     "walking_f1_drop_pp_max": C.CRITERIA["quant_walking_drop_pp"]},
        "passed": bool(drop_macro <= C.CRITERIA["quant_macro_f1_drop_pp"]
                       and drop_walk <= C.CRITERIA["quant_walking_drop_pp"]),
    }
