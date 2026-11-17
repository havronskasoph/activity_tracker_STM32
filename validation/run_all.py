#!/usr/bin/env python3
"""Запускає всі тести підтвердження, зберігає метрики й малює графіки.

    python validation/run_all.py            # усе
    python validation/run_all.py --no-pytest

Потрібні TensorFlow (лише для тесту 2) і ST Edge AI Core (тести 3-4).
Якщо їх немає, ці тести позначаються skipped із причиною, решта виконується.
Див. validation/README.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.scripts import config as C          # noqa: E402
from validation.scripts import board, plotting, quantize, stedgeai, steps  # noqa: E402


def save(name: str, data: dict) -> Path:
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p = C.RESULTS_DIR / name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def banner(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\n[{n}] {title}\n{'=' * 72}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pytest", action="store_true", help="не запускати pytest наприкінці")
    ap.add_argument("--no-board", action="store_true",
                    help="не читати плату, брати збережені логи з board_logs/")
    args = ap.parse_args()
    t0 = time.monotonic()

    banner(1, "Порівняння трьох моделей на test і val")
    cmp = steps.step_model_comparison()
    save("01_model_comparison.json", cmp)
    for k in C.MODEL_ORDER:
        m = cmp["models"][k]
        print(f"  {m['label']:>9s}: test macro-F1 {m['test']['macro_f1']:.4f}  "
              f"val {m['val']['macro_f1']:.4f}  параметрів {m['params']}  "
              f"MACC {m['macc']}  відтворення {m['repro_delta_test_macro_f1']:.2e}")

    banner(2, "Квантування int8 обраної моделі")
    q = quantize.run(cmp["models"][C.CHOSEN]["test"])
    save("02_quantization.json", q)
    if q.get("status") == "ok":
        print(f"  macro-F1 {q['float32']['macro_f1']:.4f} -> {q['int8']['macro_f1']:.4f} "
              f"(падіння {q['macro_f1_drop_pp']:.2f} п.), Walking падіння "
              f"{q['walking_f1_drop_pp']:.2f} п.")
    else:
        print(f"  ПРОПУЩЕНО: {q.get('reason', '')}")

    banner(3, "ST Edge AI Core: analyze")
    tfl = C.RESULTS_DIR / f"{C.MODELS[C.CHOSEN]['name']}_int8.tflite"
    an = {"float32": stedgeai.analyze(C.MODELS[C.CHOSEN]["dir"] / "model.keras", "f32")}
    an["int8"] = (stedgeai.analyze(tfl, "int8") if tfl.exists()
                  else {"status": "skipped", "reason": "немає int8-моделі (тест 2 не виконувався)"})
    save("03_stedgeai_analyze.json", an)
    for k, v in an.items():
        print(f"  {k}: {v.get('status')}" + (f" — {v.get('reason','')}" if v.get("status") != "ok" else ""))

    banner(4, "ST Edge AI Core: validate")
    va = stedgeai.validate(tfl if tfl.exists() else C.MODELS[C.CHOSEN]["dir"] / "model.keras", "val")
    save("04_stedgeai_validate.json", va)
    print(f"  {va.get('status')}" + (f" — {va.get('reason','')}" if va.get("status") != "ok" else ""))

    banner(5, "Паритет препроцесингу: ФНЧ плати на тестових даних")
    par = steps.step_preprocessing_parity()
    save("05_preprocessing_parity.json", par)
    print(f"  без фільтра {par['without_filter']['macro_f1']:.4f} -> "
          f"з фільтром {par['with_board_filter']['macro_f1']:.4f} "
          f"(падіння {par['macro_f1_drop_pp']:.2f} п.)")

    banner(6, "Тестові вектори для прогону на платі")
    tv = steps.step_test_vectors()
    save("06_test_vectors.json", tv)
    print(f"  {tv['n_vectors']} вікон, по {tv['per_class']} на клас; файли: "
          + ", ".join(f"{k} ({v} Б)" for k, v in tv["files"].items()))

    banner(7, "Тести на платі")
    bd = board.collect(prefer_live=not args.no_board)
    save("board_summary.json", bd)
    board_files = board.split_results(bd) if bd.get("status") == "ok" else {}
    for name, d in board_files.items():
        save(name, d)
        print(f"  {name}: {'PASS' if d['passed'] else 'FAIL'}")
    if not board_files:
        print(f"  ПРОПУЩЕНО: {bd.get('reason', '')}")

    banner(8, "Виправлені метадані моделі")
    corrected = steps.step_corrected_metadata()
    save("model_meta_corrected.json", corrected)
    print("  записано results/model_meta_corrected.json")

    banner(9, "Графіки")
    figs = [
        plotting.models_macro_f1(cmp),
        plotting.models_f1_per_class(cmp),
        plotting.f1_vs_macc(cmp),
        plotting.confusion_chosen(cmp),
        plotting.f1_per_subject(cmp),
        plotting.float_vs_int8(q),
        plotting.memory_usage(cmp, q),
        plotting.preprocessing_parity(par),
    ]
    if "board_odr.json" in board_files:
        figs.append(plotting.board_odr(board_files["board_odr.json"]))
    if "board_inference.json" in board_files:
        dbg = board.from_log("selftest_debug.log") or {}
        figs.append(plotting.board_inference(
            board_files["board_inference.json"],
            (dbg.get("inference") or {}).get("ms_avg")))
    rows = summary_rows(cmp, q, an, va, par, tv, board_files)
    figs.append(plotting.validation_summary(rows))
    save("00_summary.json", {"rows": rows})
    for f in figs:
        print(f"  {f.name} ({f.stat().st_size} Б)")

    print(f"\nГотово за {time.monotonic() - t0:.1f} с.")
    if not args.no_pytest:
        banner(10, "pytest")
        # -p no:cacheprovider: не створювати .pytest_cache у корені репозиторію
        r = subprocess.run([sys.executable, "-m", "pytest", str(C.VALIDATION_DIR / "tests"),
                            "-v", "--no-header", "-rs", "-p", "no:cacheprovider"],
                           cwd=str(C.REPO_ROOT))
        return r.returncode
    return 0


def summary_rows(cmp, q, an, va, par, tv, board_files=None) -> list[dict]:
    chosen = cmp["models"][C.CHOSEN]
    worst_repro = max(cmp["models"][k]["repro_delta_test_macro_f1"] for k in C.MODEL_ORDER)
    rows = [{
        "name": "1. Порівняння трьох моделей",
        "detail": (f'обрана {chosen["label"]}: macro-F1 {chosen["test"]["macro_f1"]:.4f}; '
                   f'метрики відтворено (дельта {worst_repro:.0e})'),
        "status": "PASS" if worst_repro < 1e-9 and chosen["board_compatible"] else "FAIL",
    }]
    if q.get("status") == "ok":
        rows.append({"name": "2. Квантування int8",
                     "detail": (f'macro-F1 {-q["macro_f1_drop_pp"]:+.2f} п., '
                                f'Walking {-q["walking_f1_drop_pp"]:+.2f} п. '
                                f'(плюс = краще)'),
                     "status": "PASS" if q["passed"] else "FAIL"})
    else:
        rows.append({"name": "2. Квантування int8", "detail": "TensorFlow недоступний",
                     "status": "SKIP"})
    ok_an = [v for v in an.values() if v.get("status") == "ok"]
    rows.append({"name": "3. ST Edge AI analyze",
                 "detail": "Flash/RAM/MACC з інструменту" if ok_an else "ST Edge AI Core не встановлений",
                 "status": ("PASS" if ok_an and all(v.get("passed") for v in ok_an)
                            else ("SKIP" if not ok_an else "FAIL"))})
    rows.append({"name": "4. ST Edge AI validate",
                 "detail": (f'збіг argmax {va.get("argmax_match", 0) * 100:.1f} %'
                            if va.get("status") == "ok" else "ST Edge AI Core не встановлений"),
                 "status": ("PASS" if va.get("passed") else
                            ("SKIP" if va.get("status") == "skipped" else "FAIL"))})
    rows.append({"name": "5. Паритет препроцесингу",
                 "detail": f'ФНЧ плати: macro-F1 {-par["macro_f1_drop_pp"]:+.2f} п.',
                 "status": "PASS" if par["passed"] else "FAIL"})
    rows.append({"name": "6. Тестові вектори ПК -> MCU",
                 "detail": f'{tv["n_vectors"]} вікон згенеровано (прогін на платі — тест 7)',
                 "status": "PASS" if tv["status"] == "ok" else "FAIL"})

    bf = board_files or {}
    board_rows = [
        ("7. Плата: тестові вектори", "board_vectors.json",
         lambda d: f'{d["matched"]}/{d["total"]} збігів argmax'),
        ("8. Плата: час інференсу", "board_inference.json",
         lambda d: f'{d["ms_avg"]:.1f} мс = {d["budget_used_frac"]*100:.1f} % кроку вікна'),
        ("9. Плата: класифікація наживо", "board_live.json",
         lambda d: f'{d["count"]} передбачень, раз на {d["period_ms_median"]:.0f} мс'),
        ("10. Плата: фактичний ODR", "board_odr.json",
         lambda d: f'{d["actual_hz"]:.1f} Гц проти {d["nominal_hz"]:g} ({d["deviation_pct"]:+.1f} %)'),
    ]
    for name, fn, fmt in board_rows:
        if fn in bf:
            d = bf[fn]
            rows.append({"name": name, "detail": fmt(d),
                         "status": "PASS" if d["passed"] else "FAIL"})
        else:
            rows.append({"name": name, "detail": "плата не підключена", "status": "SKIP"})
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
