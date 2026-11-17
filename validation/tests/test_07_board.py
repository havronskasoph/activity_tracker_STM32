"""Тести на платі: ODR, час інференсу, тестові вектори, живий лог.

Беруть показники з board_*.json, які пише run_all.py — з живої плати, якщо вона
підключена, або зі збережених логів board_logs/. Якщо немає ні того, ні того —
SKIP із причиною.
"""
import json

import pytest

from validation.scripts import config as C


def _load(name):
    p = C.RESULTS_DIR / name
    if not p.exists():
        pytest.skip(f"{name} немає: плата не підключена і логів у board_logs/ немає")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("status") != "ok":
        pytest.skip(d.get("reason", "дані з плати недоступні"))
    return d


def test_test_vectors_match_on_board():
    """Головна перевірка: C-модель на платі дає ті самі класи, що модель на ПК."""
    d = _load("board_vectors.json")
    need = C.CRITERIA["board_argmax_match"]
    assert d["ratio"] >= need, (
        f'збіг {d["matched"]}/{d["total"]} = {d["ratio"]*100:.1f} % < {need*100:.0f} %')


def test_inference_fits_window_budget():
    d = _load("board_inference.json")
    assert d["ms_avg"] < 0.5 * d["hop_budget_ms"], (
        f'інференс {d["ms_avg"]:.1f} мс займає {d["budget_used_frac"]*100:.1f} % '
        f'кроку вікна {d["hop_budget_ms"]:.0f} мс')


def test_model_classifies_in_real_time():
    d = _load("board_live.json")
    assert d["count"] > 0, "плата не видала жодного передбачення"
    assert d["period_ms_median"] is None or d["period_ms_median"] < 1500, (
        f'передбачення раз на {d["period_ms_median"]:.0f} мс — надто рідко')


def test_actual_odr_within_tolerance():
    """Очікуваний FAIL: датчик іде на ~5.6 % швидше за номінал.

    Це не дефект коду, а властивість ISM330DHCX на цій платі: те саме
    відхилення виміряне й на 26 Гц (27.45 замість 26). Наслідок — вікно
    208 відліків триває 1.89 с замість 2.00 с, на яких навчена модель.
    """
    d = _load("board_odr.json")
    assert abs(d["deviation_pct"]) <= 2.0, (
        f'фактичний ODR {d["actual_hz"]:.1f} Гц проти номіналу {d["nominal_hz"]:g} Гц '
        f'({d["deviation_pct"]:+.1f} %); вікно триває {d["window_seconds"]:.2f} с '
        f'замість 2.00 с — модель бачить стиснуту в часі динаміку')
