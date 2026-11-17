"""Генерує har_model_config.h із model_meta.json навченої моделі.

Відрізняється від scripts/export_firmware_constants.py у репозиторії датасету
тим, що бере всі числа з самої моделі, а не з config.yaml. Це потрібно для
моделей, навчених на передискретизованих у пам'яті даних, у яких окремого
репозиторію датасету не існує (наприклад 27.45 Гц).

Запуск:
    python -m validation.scripts.export_firmware_config \
        ml/models/st_ign_realworld_imu_27hz/model_meta.json \
        <куди>/har_model_config.h --lpf-hz 12
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter

MAX_GAP_SECONDS = 0.5


def build(meta: dict, lpf_hz: float, lpf_order: int) -> str:
    fs = float(meta["sample_rate_hz"])
    win = int(meta["window_samples"])
    hop = int(meta["stride_samples"])
    classes = list(meta["class_names"])
    ch = list(meta["channels"])
    units = meta["units"]
    norm = meta["normalization"]
    gap = int(round(MAX_GAP_SECONDS * fs))

    nyq = fs / 2.0
    if lpf_hz >= nyq:
        raise ValueError(f"зріз {lpf_hz} Гц не менший за Найквіста {nyq:.2f} Гц")
    sos = butter(lpf_order, lpf_hz / nyq, btype="low", output="sos")

    L = []
    a = L.append
    a("/* ЗГЕНЕРОВАНО validation/scripts/export_firmware_config.py — не редагувати руками.")
    a(" *")
    a(f" * Джерело: {meta.get('model_file', 'model.keras')}, архітектура {meta.get('architecture')}")
    a(" * Усі числа взяті з model_meta.json моделі, тому заголовок і модель")
    a(" * не можуть розійтися.")
    a(" *")
    a(f" * Формат входу: {fs:g} Гц, вікно {win} x {len(ch)}, канали "
      + ", ".join(ch) + f", acc у {units['acc']}, gyro у {units['gyr']}.")
    a(" */")
    a("#ifndef HAR_MODEL_CONFIG_H")
    a("#define HAR_MODEL_CONFIG_H")
    a("")
    a("/* ── Формат входу моделі ─────────────────────────────────────────── */")
    a(f"#define HAR_FS_HZ            {fs:.2f}f")
    a(f"#define HAR_CHANNELS         {len(ch)}")
    a(f"#define HAR_WINDOW_SAMPLES   {win}      /* {win/fs:.2f} с */")
    a(f"#define HAR_HOP_SAMPLES      {hop}      /* перекриття {100*(1-hop/win):.0f} % */")
    a(f"#define HAR_MAX_GAP_SAMPLES  {gap}      /* {MAX_GAP_SECONDS} с: більший розрив рве вікно */")
    a(f'#define HAR_ACC_UNIT         "{units["acc"]}"')
    a(f'#define HAR_GYR_UNIT         "{units["gyr"]}"')
    a("")
    a("/* Порядок каналів у вікні (рядок = момент часу): */")
    a("/*   " + ", ".join(f"{i}:{c}" for i, c in enumerate(ch)) + " */")
    a("")
    a("/* ── Класи ───────────────────────────────────────────────────────── */")
    a(f"#define HAR_CLASS_COUNT      {len(classes)}")
    a("#define HAR_CLASS_LIST       " + ", ".join(f'"{c}"' for c in classes))
    a("")
    for i, c in enumerate(classes):
        a(f"#define HAR_CLASS_{c.upper():<12s} {i}")
    a("")
    a("/* ── ФНЧ перед інференсом ────────────────────────────────────────── */")
    a(f"/* Баттерворт {lpf_order}-го порядку, зріз {lpf_hz:g} Гц при {fs:g} Гц,")
    a(f" * каскад біквадів (SOS). Частота Найквіста {nyq:.2f} Гц.")
    a(" * Призначення: привести смугу сигналу з датчика до тієї, яку модель")
    a(" * бачила в навчальних даних. */")
    a(f"#define HAR_LPF_HZ           {lpf_hz:.2f}f")
    a(f"#define HAR_LPF_ORDER        {lpf_order}")
    a(f"#define HAR_LPF_SECTIONS     {len(sos)}")
    a("")
    a("/* {b0, b1, b2, a1, a2} на секцію; a0 нормалізований до 1. */")
    a("#define HAR_LPF_SOS { \\")
    for i, s in enumerate(sos):
        vals = ", ".join(f"{v:+.9e}f" for v in (s[0], s[1], s[2], s[4], s[5]))
        a(f"    {{{vals}}}" + (", \\" if i < len(sos) - 1 else " \\"))
    a("}")
    a("")
    a("/* ── Нормалізація ────────────────────────────────────────────────── */")
    a(f"/* {norm.get('formula', '(x - mean) / std')} */")
    a("#define HAR_NORM_MEAN { " + ", ".join(f"{v:+.9e}f" for v in norm["mean"]) + " }")
    a("#define HAR_NORM_STD  { " + ", ".join(f"{v:+.9e}f" for v in norm["std"]) + " }")
    a("")
    a("#endif /* HAR_MODEL_CONFIG_H */")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meta", type=Path, help="model_meta.json моделі")
    ap.add_argument("out", type=Path, help="куди писати har_model_config.h")
    ap.add_argument("--lpf-hz", type=float, required=True, help="частота зрізу ФНЧ")
    ap.add_argument("--lpf-order", type=int, default=4)
    args = ap.parse_args(argv)

    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    args.out.write_text(build(meta, args.lpf_hz, args.lpf_order), encoding="utf-8")
    print(f"{args.out.name}: {args.out.stat().st_size} Б, "
          f"{meta['sample_rate_hz']:g} Гц, вікно {meta['window_samples']}, "
          f"ФНЧ {args.lpf_hz:g} Гц")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
