"""Шляхи, реєстр моделей, константи плати і стиль графіків.

Єдине місце, де задані зовнішні шляхи. Датасети лежать поза цим репозиторієм,
тому кожен можна перевизначити змінною оточення — див. validation/README.md.
"""
from __future__ import annotations

import os
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = VALIDATION_DIR.parent
ML_DIR = REPO_ROOT / "ml"
MODELS_DIR = ML_DIR / "models"

RESULTS_DIR = VALIDATION_DIR / "results"
FIGURES_DIR = VALIDATION_DIR / "figures"
VECTORS_DIR = VALIDATION_DIR / "test_vectors"

# ── Зовнішні шляхи ───────────────────────────────────────────────────────────
# Датасети в git цього репозиторію не лежать: вони в окремих репозиторіях
# har-realworld-dataset (52 Гц) і har-dataset_var2 (104 Гц).
_DEFAULT_52 = REPO_ROOT.parent / "har-dataset" / "data" / "processed"
_DEFAULT_104 = (REPO_ROOT.parent / "variant_104hz" / "har-dataset_var2"
                / "data" / "processed")
_DEFAULT_HEADER = (REPO_ROOT.parent / "variant_104hz" / "activity_tracker_STM32_var2"
                   / "firmware" / "activity_tracker_fw" / "Core" / "Inc"
                   / "har_model_config.h")

DATASET_52HZ = Path(os.environ.get("HAR_DATASET_52HZ", _DEFAULT_52))
DATASET_104HZ = Path(os.environ.get("HAR_DATASET_104HZ", _DEFAULT_104))
FIRMWARE_HEADER = Path(os.environ.get("HAR_FIRMWARE_HEADER", _DEFAULT_HEADER))
STEDGEAI = os.environ.get("STEDGEAI_PATH", "stedgeai")

# ── Реєстр моделей ───────────────────────────────────────────────────────────
# resample_hz=None означає «брати датасет як є»; інакше вікна передискретизуються
# штатною ml.har.data.resample_dataset, як це робив train.py.
MODELS = {
    "27hz": {
        "name": "st_ign_realworld_imu_27hz",
        "label": "27.45 Гц",
        "dir": MODELS_DIR / "st_ign_realworld_imu_27hz",
        "dataset": "52hz",
        "resample_hz": 27.45,
        # Після передискретизації mean/std перераховуються, тому беруться
        # з model_meta.json моделі, а не з norm_stats.json датасету.
        "norm_from": "model_meta",
    },
    "52hz": {
        "name": "st_ign_realworld_imu",
        "label": "52 Гц",
        "dir": MODELS_DIR / "st_ign_realworld_imu",
        "dataset": "52hz",
        "resample_hz": None,
        "norm_from": "dataset",
    },
    "104hz": {
        "name": "st_ign_var2_104hz",
        "label": "104 Гц",
        "dir": MODELS_DIR / "st_ign_var2_104hz",
        "dataset": "104hz",
        "resample_hz": None,
        "norm_from": "dataset",
    },
}

CHOSEN = "104hz"
MODEL_ORDER = ["27hz", "52hz", "104hz"]
CLASS_NAMES = ["Lying", "Stationary", "Walking", "Running", "Stairs"]
TEST_SUBJECTS = [12, 14, 15]

# ── Константи плати ──────────────────────────────────────────────────────────
# Джерело: Core/Inc/har_model_config.h у прошивці activity_tracker_STM32_var2,
# згенерований scripts/export_firmware_constants.py із har-dataset_var2.
# Якщо заголовок доступний, test_01 звіряє ці числа з ним.
BOARD = {
    "fs_hz": 104.0,
    "window_samples": 208,
    "hop_samples": 104,
    "channels": 6,
    "lpf_hz": 25.0,
    "lpf_order": 4,
    # HAR_LPF_SOS: Баттерворт 4-го порядку, зріз 25 Гц при 104 Гц, каскад біквадів.
    # {b0, b1, b2, a1, a2} на секцію, a0 нормалізований до 1.
    "lpf_sos": [
        [8.308933554e-02, 1.661786711e-01, 8.308933554e-02, -6.282248154e-02, 4.047772339e-02],
        [1.000000000e+00, 2.000000000e+00, 1.000000000e+00, -8.737936609e-02, 4.471934516e-01],
    ],
}
MCU = {"name": "STM32U585AII", "flash_kib": 2048, "ram_kib": 768}

# ── Критерії тестів ──────────────────────────────────────────────────────────
CRITERIA = {
    "quant_macro_f1_drop_pp": 1.5,    # тест 2: падіння macro-F1, пункти
    "quant_walking_drop_pp": 3.0,     # тест 2: падіння F1 Walking, пункти
    "memory_headroom_frac": 0.50,     # тест 3: запас від Flash/RAM плати
    "validate_argmax_match": 1.00,    # тест 4: збіг argmax C-моделі
    "parity_macro_f1_drop_pp": 1.0,   # тест 5: падіння від ФНЧ плати, пункти
    "board_argmax_match": 0.98,       # тест 6: критерій для прогону на платі
    "vectors_per_class": 10,          # тест 6: вікон на клас
}

# ── Стиль графіків ───────────────────────────────────────────────────────────
# Категорійні слоти 1-3 валідованої палітри (validate_palette.js, light,
# --pairs all: ALL CHECKS PASS). Колір закріплений за моделлю, не за рангом.
SERIES = {"27hz": "#2a78d6", "52hz": "#eb6834", "104hz": "#1baf7a"}
STATUS = {"PASS": "#0ca30c", "FAIL": "#d03b3b", "SKIP": "#fab219"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#dcdbd6"
DPI = 150


def board_sos():
    """HAR_LPF_SOS у формат scipy.

    У har_model_config.h секція записана п'ятьма числами {b0, b1, b2, a1, a2}:
    a0 нормалізований до 1 і не зберігається. scipy.signal.sosfilt чекає шість
    колонок {b0, b1, b2, a0, a1, a2}, тому a0 = 1 вставляється назад.
    """
    import numpy as np
    sos = np.asarray(BOARD["lpf_sos"], dtype=np.float64)
    return np.column_stack([sos[:, 0:3], np.ones(len(sos)), sos[:, 3:5]])


def dataset_dir(key: str) -> Path:
    return DATASET_52HZ if key == "52hz" else DATASET_104HZ


def require(path: Path, what: str, hint: str = "") -> Path:
    if not path.exists():
        msg = f"не знайдено {what}: {path}"
        if hint:
            msg += f"\n  {hint}"
        raise FileNotFoundError(msg)
    return path
