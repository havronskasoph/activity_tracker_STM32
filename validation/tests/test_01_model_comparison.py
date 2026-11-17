"""Тест 1: порівняння трьох моделей на test і val."""
from validation.scripts import config as C


def test_all_three_models_evaluated(comparison):
    assert set(comparison["models"]) == set(C.MODEL_ORDER)


def test_metrics_reproduce_reported(comparison):
    """Мої числа мають збігатися з results у model_meta.json кожної моделі.

    Це перевірка відтворюваності: якщо розійдеться — або модель перезаписали,
    або змінився датасет, або зламався препроцесинг.
    """
    for key, m in comparison["models"].items():
        assert m["repro_delta_test_macro_f1"] < 1e-9, (
            f'{m["name"]}: macro-F1 {m["test"]["macro_f1"]:.6f} не збігається з '
            f'записаним {m["reported"].get("test", {}).get("macro_f1")}')


def test_param_counts_match_metadata(comparison):
    for m in comparison["models"].values():
        if m["params_meta"] is not None:
            assert m["params"] == m["params_meta"], m["name"]


def test_chosen_model_fits_board(comparison):
    m = comparison["models"][C.CHOSEN]
    assert m["board_compatible"], (
        f'{m["name"]}: вікно {m["window_samples"]} при {m["fs_hz"]} Гц не відповідає '
        f'платі ({C.BOARD["window_samples"]} при {C.BOARD["fs_hz"]} Гц)')


def test_other_models_are_not_board_compatible(comparison):
    """Фіксує причину вибору: інші дві моделі на цю плату не стають без переробки."""
    for key in C.MODEL_ORDER:
        if key != C.CHOSEN:
            assert not comparison["models"][key]["board_compatible"]


def test_chosen_model_beats_52hz(comparison):
    assert (comparison["models"][C.CHOSEN]["test"]["macro_f1"]
            > comparison["models"]["52hz"]["test"]["macro_f1"])


def test_firmware_header_matches_board_constants(comparison):
    import pytest
    h = comparison["header_cross_check"]
    if h["status"] != "ok":
        pytest.skip(h["reason"])
    assert h["passed"], f'константи розійшлися: {h["mismatches"]}'
