"""Тест 5: паритет препроцесингу ПК і плати.

Плата проганяє потік через причинний ФНЧ 25 Гц (har_preproc.c), а навчальні дані
такого фільтра не бачили. Тест міряє, скільки точності коштує ця розбіжність.
"""
from validation.scripts import config as C


def test_filter_cost_within_limit(parity):
    limit = C.CRITERIA["parity_macro_f1_drop_pp"]
    assert parity["macro_f1_drop_pp"] <= limit, (
        f'ФНЧ плати забирає {parity["macro_f1_drop_pp"]:.2f} п. macro-F1 '
        f'(ліміт {limit} п.): навчальні дані фільтра не мали, і розбіжність завелика')


def test_same_window_count_in_both_arms(parity):
    """Обидві гілки мають порівнюватися на однаковому наборі вікон."""
    assert parity["without_filter"]["n_windows"] == parity["with_board_filter"]["n_windows"]


def test_sos_matches_board_header(parity):
    assert parity["lpf"]["sos"] == C.BOARD["lpf_sos"]
    assert parity["lpf"]["causal"] is True


def test_no_class_destroyed_by_filter(parity):
    """Жоден клас не має просісти більш ніж на 5 пунктів."""
    a = parity["without_filter"]["f1_per_class"]
    b = parity["with_board_filter"]["f1_per_class"]
    for cls in a:
        drop = (a[cls] - b[cls]) * 100
        assert drop <= 5.0, f"клас {cls}: F1 падає на {drop:.2f} п. через ФНЧ плати"
