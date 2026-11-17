"""Обчислювальні кроки тестів 1, 5, 6 і виправлені метадані моделі."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import config as C
from . import datasets, metrics
from .stign_numpy import (activation_bytes, count_macc, count_params,
                          load_model, normalize, predict_proba)


def _eval_split(w, split, mean, std):
    x = normalize(split.X, mean, std)
    pred = predict_proba(x, w).argmax(1)
    return metrics.compute(split.y, pred, split.subject)


# ── Тест 1: порівняння трьох моделей ─────────────────────────────────────────
def step_model_comparison() -> dict:
    out = {"models": {}, "board": C.BOARD, "chosen": C.CHOSEN}
    for key in C.MODEL_ORDER:
        spec = C.MODELS[key]
        C.require(spec["dir"] / "model.keras", f"модель {spec['name']}")
        print(f"  {spec['label']}: завантаження даних ...", flush=True)
        ds = datasets.load_for(key)
        mean, std = datasets.norm_stats(key, ds)
        w, in_shape = load_model(spec["dir"] / "model.keras")
        if tuple(in_shape[:2]) != (ds.window_samples, len(ds.channels)):
            raise ValueError(f"{spec['name']}: вхід {in_shape} не збігається з даними "
                             f"({ds.window_samples}, {len(ds.channels)})")
        print(f"  {spec['label']}: інференс test/val ...", flush=True)
        m_test = _eval_split(w, ds.test, mean, std)
        m_val = _eval_split(w, ds.val, mean, std)
        meta = datasets.meta(key)
        act = activation_bytes(ds.window_samples, len(ds.channels))
        params = count_params(ds.window_samples, len(ds.channels))
        out["models"][key] = {
            "name": spec["name"],
            "label": spec["label"],
            "input_shape": list(in_shape),
            "fs_hz": float(ds.fs_hz),
            "window_samples": int(ds.window_samples),
            "stride_samples": int(ds.stride_samples),
            "params": params,
            "params_meta": meta.get("params"),
            "macc": count_macc(ds.window_samples, len(ds.channels)),
            "weights_bytes_f32": params * 4,
            "activation_bytes": act,
            "test": m_test,
            "val": m_val,
            # Відтворюваність: мої числа проти записаних автором моделі.
            "reported": meta.get("results", {}),
            "repro_delta_test_macro_f1": abs(
                m_test["macro_f1"] - meta.get("results", {}).get("test", {}).get("macro_f1", float("nan"))),
            "board_compatible": (int(ds.window_samples) == C.BOARD["window_samples"]
                                 and abs(float(ds.fs_hz) - C.BOARD["fs_hz"]) < 1e-6),
        }
    out["header_cross_check"] = _check_header()
    return out


def _check_header() -> dict:
    """Якщо заголовок прошивки доступний — звіряє константи плати з config.BOARD."""
    p = C.FIRMWARE_HEADER
    if not p.exists():
        return {"status": "skipped", "reason": f"заголовок прошивки не знайдено: {p}"}
    text = p.read_text(encoding="utf-8", errors="replace")

    def grab(macro, cast=float):
        m = re.search(rf"#define\s+{macro}\s+([-\d.eEf+]+)", text)
        return cast(m.group(1).rstrip("f")) if m else None

    found = {"fs_hz": grab("HAR_FS_HZ"), "window_samples": grab("HAR_WINDOW_SAMPLES", int),
             "hop_samples": grab("HAR_HOP_SAMPLES", int), "lpf_hz": grab("HAR_LPF_HZ")}
    mismatches = {k: (v, C.BOARD[k]) for k, v in found.items()
                  if v is not None and abs(float(v) - float(C.BOARD[k])) > 1e-6}
    return {"status": "ok", "header": str(p), "found": found,
            "mismatches": mismatches, "passed": not mismatches}


# ── Тест 5: паритет препроцесингу ────────────────────────────────────────────
def step_preprocessing_parity() -> dict:
    key = C.CHOSEN
    spec = C.MODELS[key]
    ds = datasets.load_for(key)
    mean, std = datasets.norm_stats(key, ds)
    w, _ = load_model(spec["dir"] / "model.keras")
    sos = C.board_sos()

    # Базова лінія з тим самим склеюванням і нарізкою, але без фільтра —
    # інакше порівнювалися б різні набори вікон.
    def rewindow(apply_filter: bool):
        use = sos if apply_filter else None
        return datasets.stitch_filter_rewindow(ds.test, ds.stride_samples, use, ds.window_samples)

    res = {}
    for tag, flt in (("without_filter", False), ("with_board_filter", True)):
        print(f"  паритет: {tag} ...", flush=True)
        X, y, subj = rewindow(flt)
        pred = predict_proba(normalize(X, mean, std), w).argmax(1)
        res[tag] = metrics.compute(y, pred, subj)

    drop = (res["without_filter"]["macro_f1"] - res["with_board_filter"]["macro_f1"]) * 100.0
    return {
        "status": "ok",
        "model": spec["name"],
        "lpf": {"hz": C.BOARD["lpf_hz"], "order": C.BOARD["lpf_order"],
                "sos": C.BOARD["lpf_sos"], "causal": True,
                "source": "HAR_LPF_SOS у har_model_config.h, застосовано scipy.signal.sosfilt"},
        "without_filter": res["without_filter"],
        "with_board_filter": res["with_board_filter"],
        "macro_f1_drop_pp": drop,
        "criteria": {"macro_f1_drop_pp_max": C.CRITERIA["parity_macro_f1_drop_pp"]},
        "passed": bool(drop <= C.CRITERIA["parity_macro_f1_drop_pp"]),
    }


# ── Тест 6: тестові вектори для плати ────────────────────────────────────────
def step_test_vectors(seed: int = 123) -> dict:
    key = C.CHOSEN
    spec = C.MODELS[key]
    per_class = C.CRITERIA["vectors_per_class"]
    ds = datasets.load_for(key)
    mean, std = datasets.norm_stats(key, ds)
    w, _ = load_model(spec["dir"] / "model.keras")

    rng = np.random.default_rng(seed)
    picks = []
    for c in range(len(C.CLASS_NAMES)):
        idx = np.flatnonzero(ds.test.y == c)
        if len(idx) < per_class:
            raise ValueError(f"у test лише {len(idx)} вікон класу {C.CLASS_NAMES[c]}")
        picks.append(rng.choice(idx, size=per_class, replace=False))
    sel = np.concatenate(picks)

    raw = ds.test.X[sel].astype(np.float32)
    xn = normalize(raw, mean, std)
    proba = predict_proba(xn, w)
    pred = proba.argmax(1)
    y = ds.test.y[sel]
    subj = ds.test.subject[sel]

    C.VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    npz = C.VECTORS_DIR / "test_vectors.npz"
    np.savez_compressed(npz, x_normalized=xn[..., 0], x_raw=raw, y_true=y,
                        y_pred=pred, proba=proba, subject=subj,
                        class_names=np.array(C.CLASS_NAMES), mean=mean, std=std)
    _write_c_header(C.VECTORS_DIR / "har_test_vectors.h", xn[..., 0], y, pred, proba)
    _write_expected_csv(C.VECTORS_DIR / "expected.csv", y, pred, proba, subj)

    return {
        "status": "ok",
        "model": spec["name"],
        "n_vectors": int(len(sel)),
        "per_class": per_class,
        "window_shape": [int(xn.shape[1]), int(xn.shape[2])],
        "input": "нормалізовані вікна (x - mean) / std — подаються прямо в модель, "
                 "минаючи har_preproc: цей тест перевіряє лише C-модель",
        "pc_argmax_matches_expected": True,
        "pc_self_agreement": float((pred == proba.argmax(1)).mean()),
        "class_distribution": {C.CLASS_NAMES[c]: int((y == c).sum())
                               for c in range(len(C.CLASS_NAMES))},
        "pc_accuracy_on_vectors": float((pred == y).mean()),
        "files": {f.name: f.stat().st_size for f in sorted(C.VECTORS_DIR.glob("*"))
                  if f.is_file()},
        "board_criterion": {"argmax_match_min": C.CRITERIA["board_argmax_match"],
                            "status": "очікує прогону на платі"},
    }


def _write_c_header(path: Path, x, y, pred, proba) -> None:
    n, t, c = x.shape
    lines = [
        "/* ЗГЕНЕРОВАНО validation/run_all.py — не редагувати руками.",
        " *",
        f" * {n} тестових вікон ({C.CRITERIA['vectors_per_class']} на клас)",
        " * для звірки виходів C-моделі на платі з моделлю на ПК.",
        " *",
        " * Вікна ВЖЕ нормалізовані ((x - mean) / std), тобто подаються прямо в модель,",
        " * минаючи har_preproc. Так перевіряється саме C-модель, а не препроцесинг.",
        " */",
        "#ifndef HAR_TEST_VECTORS_H",
        "#define HAR_TEST_VECTORS_H",
        "",
        f"#define HAR_TV_COUNT   {n}",
        f"#define HAR_TV_SAMPLES {t}",
        f"#define HAR_TV_CHANNELS {c}",
        "",
        "/* [вікно][час][канал] */",
        f"static const float har_tv_input[HAR_TV_COUNT][HAR_TV_SAMPLES][HAR_TV_CHANNELS] = {{",
    ]
    for i in range(n):
        lines.append("  {")
        for ti in range(t):
            vals = ", ".join(f"{v:+.6e}f" for v in x[i, ti])
            lines.append(f"    {{{vals}}},")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    lines.append("/* Очікуваний клас (argmax моделі на ПК) */")
    lines.append("static const unsigned char har_tv_expected[HAR_TV_COUNT] = {")
    lines.append("  " + ", ".join(str(int(v)) for v in pred))
    lines.append("};")
    lines.append("")
    lines.append("/* Істинна мітка з датасету — для довідки, у звірці не використовується */")
    lines.append("static const unsigned char har_tv_true[HAR_TV_COUNT] = {")
    lines.append("  " + ", ".join(str(int(v)) for v in y))
    lines.append("};")
    lines.append("")
    lines.append("#endif /* HAR_TEST_VECTORS_H */")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_expected_csv(path: Path, y, pred, proba, subj) -> None:
    head = ["index", "subject", "true_class", "expected_class"] + [f"p_{c}" for c in C.CLASS_NAMES]
    rows = [",".join(head)]
    for i in range(len(y)):
        rows.append(",".join([str(i), str(int(subj[i])), C.CLASS_NAMES[int(y[i])],
                              C.CLASS_NAMES[int(pred[i])]]
                             + [f"{v:.6f}" for v in proba[i]]))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ── Виправлені метадані ──────────────────────────────────────────────────────
def step_corrected_metadata() -> dict:
    key = C.CHOSEN
    spec = C.MODELS[key]
    meta = datasets.meta(key)
    d = C.dataset_dir(spec["dataset"])
    files = {}
    for fn in ("train.npz", "val.npz", "test.npz", "norm_stats.json", "label_map.json"):
        p = d / fn
        if p.exists():
            files[fn] = {"sha256": datasets.sha256(p), "bytes": p.stat().st_size}
    corrected = dict(meta)
    corrected["dataset"] = {
        "repo": "https://github.com/alinaytsk/har-dataset_var2",
        "local_dir": "ml/data/har_var2",
        "fs_hz": 104.0,
        "window_samples": 208,
        "stride_samples": 104,
        "files_sha256": files,
        "train_subjects": meta["dataset"]["train_subjects"],
        "val_subjects": meta["dataset"]["val_subjects"],
        "test_subjects": meta["dataset"]["test_subjects"],
    }
    corrected["_correction_note"] = (
        "Оригінальний model_meta.json записує repo=har-realworld-dataset і "
        "commit=6f24dcd... — це 52-герцовий датасет, на якому ця модель навчена бути "
        "не могла: її вхід (208, 6, 1). Причина — захардкоджені DATASET_REPO і "
        "DATASET_COMMIT у ml/har/data.py, які train.py копіює в метадані незалежно "
        "від фактичного dataset.data_dir. Тут поле замінено на фактичне джерело, "
        "ідентифіковане sha256 файлів датасету."
    )
    corrected["_original_dataset_field"] = meta["dataset"]
    return corrected
