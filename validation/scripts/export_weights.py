"""Експорт ваг моделі у C-заголовок для прошивки (float32).

Запуск:
    python -m validation.scripts.export_weights \
        ml/models/st_ign_var2_104hz/model.keras \
        ../variant_104hz/activity_tracker_STM32_var2/firmware/activity_tracker_fw/Core/Inc/har_model_weights.h

Заголовок споживає Core/Src/har_model.c. Ваги float32, порядок
conv [фільтр][такт], dense [flat][hidden], dense_1 [hidden][class]."""
import io, json, sys, zipfile
from pathlib import Path
import h5py, numpy as np

src = Path(sys.argv[1]); out = Path(sys.argv[2])
with zipfile.ZipFile(src) as z:
    blob = z.read("model.weights.h5")
    cfg = json.loads(z.read("config.json"))
shape = cfg["config"]["layers"][0]["config"]["batch_shape"][1:]
with h5py.File(io.BytesIO(blob), "r") as f:
    cw = f["layers/conv2d/vars/0"][:]      # (16,1,1,24)
    cb = f["layers/conv2d/vars/1"][:]      # (24,)
    d0w = f["layers/dense/vars/0"][:]      # (9216,12)
    d0b = f["layers/dense/vars/1"][:]
    d1w = f["layers/dense_1/vars/0"][:]    # (12,5)
    d1b = f["layers/dense_1/vars/1"][:]

T, C, _ = shape
conv_t = T - 16 + 1
pool_t = conv_t // 3
flat = pool_t * C * 24
assert d0w.shape == (flat, 12), (d0w.shape, flat)

def arr(name, a, per_line=8):
    v = np.asarray(a, np.float32).reshape(-1)
    lines = [f"static const float {name}[{v.size}] = {{"]
    for i in range(0, v.size, per_line):
        lines.append("  " + ", ".join(f"{x:+.8e}f" for x in v[i:i + per_line]) + ",")
    lines.append("};")
    return "\n".join(lines)

total = cw.size + cb.size + d0w.size + d0b.size + d1w.size + d1b.size
body = [
    "/* ЗГЕНЕРОВАНО validation/scripts/export_weights.py — не редагувати руками.",
    " *",
    f" * Джерело: ml/models/st_ign_var2_104hz/model.keras",
    f" * Архітектура ST-IGN: Conv2D(24,(16,1)) -> ReLU -> MaxPool((3,1)) -> Flatten",
    f" *                     -> Dense(12) -> Dense(5) -> softmax",
    f" * Вхід {T} x {C} x 1, виходів 5. Параметрів {total}, float32 = {total*4} Б.",
    " */",
    "#ifndef HAR_MODEL_WEIGHTS_H",
    "#define HAR_MODEL_WEIGHTS_H",
    "",
    f"#define HAR_W_TIME      {T}",
    f"#define HAR_W_CHANNELS  {C}",
    f"#define HAR_W_KERNEL_T  16",
    f"#define HAR_W_FILTERS   24",
    f"#define HAR_W_POOL_T    3",
    f"#define HAR_W_CONV_T    {conv_t}",
    f"#define HAR_W_POOL_OUT  {pool_t}",
    f"#define HAR_W_FLAT      {flat}",
    f"#define HAR_W_HIDDEN    12",
    f"#define HAR_W_CLASSES   5",
    "",
    "/* conv2d: ядро (16 за часом) на кожен з 24 фільтрів; вага спільна для всіх каналів */",
    arr("har_w_conv_kernel", cw[:, 0, 0, :].T),   # (24,16), рядок = фільтр
    "",
    arr("har_w_conv_bias", cb),
    "",
    "/* dense: (HAR_W_FLAT, 12) у порядку [flat][hidden] */",
    arr("har_w_dense0", d0w),
    "",
    arr("har_w_dense0_bias", d0b),
    "",
    "/* dense_1: (12, 5) у порядку [hidden][class] */",
    arr("har_w_dense1", d1w),
    "",
    arr("har_w_dense1_bias", d1b),
    "",
    "#endif /* HAR_MODEL_WEIGHTS_H */",
]
out.write_text("\n".join(body) + "\n", encoding="utf-8")
print(f"{out.name}: {out.stat().st_size} Б, параметрів {total}, Flash {total*4/1024:.1f} КіБ")
